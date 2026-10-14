import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.cache.redis import close_redis
from app.core.config import get_settings
from app.db.models import ChatRun, Document, IngestionJob, Message
from app.db.session import close_postgres, session_factory
from app.services.document_service import DocumentService
from app.vector.qdrant import close_qdrant

logger = logging.getLogger(__name__)


async def claim_job():
    """SKIP LOCKED 支持多个 worker；过期 running 任务重排，重启不丢队列。"""
    settings = get_settings()
    stale = datetime.now(UTC) - timedelta(seconds=settings.ingestion_timeout_seconds + 60)
    async with session_factory() as database:
        abandoned = list(
            (
                await database.scalars(
                    select(ChatRun.id).where(
                        ChatRun.status == "running",
                        ChatRun.updated_at
                        < datetime.now(UTC) - timedelta(seconds=settings.chat_timeout_seconds + 60),
                    )
                )
            ).all()
        )
        if abandoned:
            await database.execute(
                update(ChatRun)
                .where(ChatRun.id.in_(abandoned))
                .values(status="failed", error_message="服务中断后恢复为失败状态")
            )
            await database.execute(
                update(Message)
                .where(
                    Message.message_metadata["request_id"].astext.in_([str(x) for x in abandoned])
                )
                .values(message_metadata=Message.message_metadata.op("||")({"status": "failed"}))
            )
        await database.execute(
            update(IngestionJob)
            .where(IngestionJob.status == "running", IngestionJob.updated_at < stale)
            .values(status="queued")
        )
        job = await database.scalar(
            select(IngestionJob)
            .where(IngestionJob.status == "queued")
            .order_by(IngestionJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job_id = None
        if job:
            job.status, job.progress, job.updated_at = "running", 0.1, datetime.now(UTC)
            job_id = job.id
            document = await database.get(Document, job.document_id)
            if document:
                document.status = "processing"
        await database.commit()
        return job_id


async def run_worker() -> None:
    """持续领取持久任务；单个文件失败不终止整个 worker 进程。"""
    logging.basicConfig(level=logging.INFO)
    try:
        while True:
            try:
                job_id = await claim_job()
                if job_id:
                    async with session_factory() as database:
                        await DocumentService(database).process_job(job_id)
                else:
                    await asyncio.sleep(get_settings().worker_poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker_poll_failed")
                await asyncio.sleep(5)
    finally:
        await close_redis()
        await close_qdrant()
        await close_postgres()


if __name__ == "__main__":
    from app.main import configure_windows_event_loop

    configure_windows_event_loop()
    asyncio.run(run_worker())
