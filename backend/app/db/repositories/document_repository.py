from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, IngestionJob


class DocumentRepository:
    """集中保存文档和入库任务的 SQLAlchemy 查询。"""

    def __init__(self, database: AsyncSession) -> None:
        """复用当前 HTTP 请求持有的数据库事务。"""
        self.database = database

    async def create(
        self,
        *,
        filename: str,
        content_type: str | None,
        checksum: str,
        owner_id: uuid.UUID | None,
    ) -> Document:
        """建立 pending 文档记录，文件内容和向量稍后写入。"""
        document = Document(
            filename=filename,
            content_type=content_type,
            checksum=checksum,
            owner_id=owner_id,
            status="pending",
        )
        self.database.add(document)
        await self.database.flush()
        return document

    async def get_by_id(self, document_id: uuid.UUID) -> Document | None:
        """根据主键读取一个文档。"""
        return await self.database.get(Document, document_id)

    async def get_by_checksum(
        self,
        checksum: str,
        owner_id: uuid.UUID | None,
    ) -> Document | None:
        """查找相同用户已经成功索引的同内容文件，用于去重。"""
        query = select(Document).where(
            Document.checksum == checksum,
            Document.owner_id == owner_id,
        )
        return await self.database.scalar(query.order_by(Document.created_at.desc()).limit(1))

    async def list(
        self,
        *,
        owner_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Document], int]:
        """按创建时间倒序返回一页文档和总数。"""
        filters = [Document.owner_id == owner_id] if owner_id is not None else []
        query = (
            select(Document)
            .where(*filters)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_query = select(func.count(Document.id)).where(*filters)
        items = list((await self.database.scalars(query)).all())
        total = int((await self.database.scalar(count_query)) or 0)
        return items, total

    async def set_status(
        self,
        document: Document,
        *,
        status: str,
        source_uri: str | None = None,
        error_message: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """更新入库状态；重新赋值 JSON 字典可确保 SQLAlchemy 检测到变化。"""
        document.status = status
        document.error_message = error_message
        if source_uri is not None:
            document.source_uri = source_uri
        if metadata is not None:
            document.document_metadata = dict(metadata)
        await self.database.flush()

    async def create_job(self, document_id: uuid.UUID) -> IngestionJob:
        """为一次文档处理建立可追踪的任务记录。"""
        job = IngestionJob(document_id=document_id, status="queued", progress=0.0)
        self.database.add(job)
        await self.database.flush()
        return job

    async def update_job(
        self,
        job: IngestionJob,
        *,
        status: str,
        progress: float,
        error_message: str | None = None,
    ) -> None:
        """更新任务进度，进度值约束在 0 到 1 之间。"""
        job.status = status
        job.progress = min(1.0, max(0.0, progress))
        job.error_message = error_message
        await self.database.flush()

    async def delete(self, document_id: uuid.UUID) -> bool:
        """删除业务记录；数据库外键会同步删除入库任务。"""
        result = await self.database.execute(delete(Document).where(Document.id == document_id))
        return bool(result.rowcount)
