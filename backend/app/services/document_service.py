import asyncio
import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.coordination import ConversationBusyError
from app.cache.redis import get_redis_client
from app.core.config import get_settings
from app.core.exceptions import DocumentNotFoundError, UserNotFoundError
from app.db.models import Document, IngestionJob
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.user_repository import UserRepository
from app.vector.chunking import split_text
from app.vector.indexing import VectorIndexService
from app.vector.parsing import extract_text
from app.vector.retrieval import KnowledgeRetriever, RetrievedChunk

logger = logging.getLogger(__name__)


class DocumentService:
    """上传只保存文件并建立持久任务，worker 完成耗时解析与向量化。"""

    def __init__(self, database: AsyncSession) -> None:
        """复用请求或 worker 的独立数据库会话。"""
        self.database, self.settings = database, get_settings()
        self.documents, self.users = DocumentRepository(database), UserRepository(database)
        self.index, self.retriever = VectorIndexService(), KnowledgeRetriever()

    async def upload(
        self, *, filename: str, content_type: str | None, content: bytes, owner_id: uuid.UUID | None
    ) -> tuple[Document, bool]:
        """校验大小与格式，按校验和去重，然后排队；网络模型不占上传请求。"""
        if not content or len(content) > self.settings.max_upload_bytes:
            raise ValueError("文件为空或超过上传大小限制")
        safe_name = Path(filename.replace("\\", "/")).name[:255]
        if Path(safe_name).suffix.lower() not in {
            ".txt",
            ".md",
            ".csv",
            ".json",
            ".pdf",
            ".docx",
            ".pptx",
        }:
            raise ValueError("仅支持 txt、md、csv、json、pdf、docx、pptx")
        if owner_id is not None and await self.users.get_by_id(owner_id) is None:
            raise UserNotFoundError(owner_id)
        checksum = hashlib.sha256(content).hexdigest()
        # 数据库事务锁让同时上传同一内容只有一个文档记录。
        lock_id = int.from_bytes(
            hashlib.sha256(f"{owner_id}:{checksum}".encode()).digest()[:8], "big", signed=True
        )
        await self.database.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
        existing = await self.documents.get_by_checksum(checksum, owner_id)
        if existing:
            if existing.status in {"pending", "processing"} or (
                existing.status == "ready"
                and existing.document_metadata.get("embedding_fingerprint")
                == self.settings.embedding_fingerprint
            ):
                await self.database.commit()
                return existing, True
            await self._enqueue(existing)
            return existing, True
        document = await self.documents.create(
            filename=safe_name, content_type=content_type, checksum=checksum, owner_id=owner_id
        )
        target_dir = self.settings.upload_dir / str(document.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / safe_name
        await asyncio.to_thread(target_path.write_bytes, content)
        document.source_uri = target_path.as_posix()
        await self._enqueue(document)
        return document, False

    async def _enqueue(self, document: Document) -> IngestionJob:
        """建立可恢复入库任务，job id 同时写入文档以便页面轮询。"""
        job = await self.documents.create_job(document.id)
        document.status, document.error_message = "pending", None
        document.document_metadata = document.document_metadata | {
            "job_id": str(job.id),
            "progress": 0.0,
            "stage": "queued",
        }
        await self.database.commit()
        await self.database.refresh(document)
        return job

    async def reindex(self, document_id: uuid.UUID) -> Document:
        """重试失败文档或为新向量模型重建索引，保留原文和旧集合。"""
        document = await self.get_document(document_id)
        if document.status in {"pending", "processing"}:
            raise ConversationBusyError("文档已经在入库队列中")
        if not document.source_uri or not Path(document.source_uri).is_file():
            raise ValueError("原文件不存在，请重新上传")
        await self._enqueue(document)
        return document

    async def process_job(self, job_id: uuid.UUID) -> None:
        """worker 在超时内解析、切块、向量化；失败清理部分索引并记录可重试状态。"""
        job = await self.database.get(IngestionJob, job_id)
        document = await self.database.get(Document, job.document_id) if job else None
        if not document or not job:
            return
        document_id, old_meta = document.id, dict(document.document_metadata)
        try:
            document.status = "processing"
            await self.database.commit()
            await self._publish_progress(job_id, 0.1, "parsing")
            async with asyncio.timeout(self.settings.ingestion_timeout_seconds):
                path = self.original_path(document)
                content = await asyncio.to_thread(path.read_bytes)
                source = await asyncio.to_thread(extract_text, document.filename, content)
                chunks = await asyncio.to_thread(
                    split_text,
                    source,
                    chunk_size=self.settings.chunk_size,
                    overlap=self.settings.chunk_overlap,
                )
                if not chunks:
                    raise ValueError("文件没有可索引文本，扫描版 PDF 需要先进行 OCR")
                await self._publish_progress(job_id, 0.35, "embedding")
                # 重试使用相同点 id，不产生重复向量。
                count = await self.index.index_document(
                    document_id=document_id, filename=document.filename, chunks=chunks
                )
            collections = list(
                dict.fromkeys(old_meta.get("collections", []) + [self.settings.vector_collection])
            )
            document.status, document.error_message = "ready", None
            document.document_metadata = old_meta | {
                "chunk_count": count,
                "character_count": len(source),
                "progress": 1.0,
                "stage": "completed",
                "embedding_fingerprint": self.settings.embedding_fingerprint,
                "collections": collections,
            }
            job.status, job.progress = "completed", 1.0
            await self.database.commit()
            await self._publish_progress(job_id, 1.0, "completed")
        except Exception as exc:
            await self.database.rollback()
            try:
                await self.index.delete_document(document_id)
            except Exception:
                logger.warning("partial_index_cleanup_failed document=%s", document_id)
            document = await self.documents.get_by_id(document_id)
            job = await self.database.get(IngestionJob, job_id)
            error = str(exc)[:500]
            if document:
                document.status, document.error_message = "failed", error
                document.document_metadata = old_meta | {"progress": 1.0, "stage": "failed"}
            if job:
                job.status, job.progress, job.error_message = "failed", 1.0, error
            await self.database.commit()
            await self._publish_progress(job_id, 1.0, "failed")
            logger.warning("ingestion_failed document=%s type=%s", document_id, type(exc).__name__)

    def original_path(self, document: Document) -> Path:
        """限制原文件访问在受控上传根目录内，下载和重建都使用同一检查。"""
        path = Path(document.source_uri or "").resolve()
        if not path.is_relative_to(self.settings.upload_dir.resolve()) or not path.is_file():
            raise ValueError("原文件路径无效或文件已丢失")
        return path

    async def list_documents(
        self, *, owner_id: uuid.UUID | None, limit: int, offset: int
    ) -> tuple[list[Document], int]:
        """返回持久状态，再叠加可丢失的 Redis 实时进度与索引版本提示。"""
        items, total = await self.documents.list(owner_id=owner_id, limit=limit, offset=offset)
        for item in items:
            meta = dict(item.document_metadata)
            meta["needs_reindex"] = (
                item.status == "ready"
                and meta.get("embedding_fingerprint") != self.settings.embedding_fingerprint
            )
            try:
                if meta.get("job_id"):
                    progress = await get_redis_client().hgetall(f"ingestion:{meta['job_id']}")
                    if progress:
                        meta |= {
                            "progress": float(progress["progress"]),
                            "stage": progress["stage"],
                        }
            except Exception:
                pass
            # 返回展示值，不赋回 ORM JSON 字段，以免一次列表请求修改业务数据。
            from sqlalchemy.orm.attributes import set_committed_value

            set_committed_value(item, "document_metadata", meta)
        return items, total

    async def get_document(self, document_id: uuid.UUID) -> Document:
        """读取文档，不存在时转换成统一业务异常。"""
        document = await self.documents.get_by_id(document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        return document

    async def delete_document(self, document_id: uuid.UUID) -> None:
        """删除全部已登记集合中的向量，再删除记录及原文件；入库中禁止删除。"""
        document = await self.get_document(document_id)
        if document.status in {"pending", "processing"}:
            raise ConversationBusyError("文档正在处理，请结束后再删除")
        source_uri = document.source_uri
        collections = set(document.document_metadata.get("collections", []))
        collections.update([self.settings.vector_collection, self.settings.qdrant_collection])
        for collection in collections:
            await self.index.delete_document(document_id, collection)
        await self.documents.delete(document_id)
        await self.database.commit()
        if source_uri:
            path, root = Path(source_uri).resolve(), self.settings.upload_dir.resolve()
            if path.is_relative_to(root) and path.is_file():
                await asyncio.to_thread(path.unlink)
                if path.parent != root and not any(path.parent.iterdir()):
                    path.parent.rmdir()

    async def search(self, query: str, *, limit: int) -> list[RetrievedChunk]:
        """检索调试接口不触发生成模型。"""
        return await self.retriever.search(query, limit=limit)

    async def _publish_progress(self, job_id: uuid.UUID, progress: float, stage: str) -> None:
        """短期实时进度写入 Redis，持久最终状态以 PostgreSQL 为准。"""
        try:
            redis = get_redis_client()
            await redis.hset(
                f"ingestion:{job_id}", mapping={"progress": str(progress), "stage": stage}
            )
            await redis.expire(f"ingestion:{job_id}", 3600)
        except Exception:
            logger.warning("ingestion_progress_cache_unavailable")
