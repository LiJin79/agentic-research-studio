import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    """返回已上传文档及其当前索引状态。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID | None
    filename: str
    content_type: str | None
    checksum: str
    status: Literal["pending", "processing", "ready", "failed"]
    version: int
    error_message: str | None
    document_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    """文档分页列表，同时返回总数和分页参数。"""

    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int


class DocumentUploadResponse(BaseModel):
    """上传结果额外说明是否命中了同内容文档。"""

    document: DocumentResponse
    deduplicated: bool = False


class RetrievalTestRequest(BaseModel):
    """用于 Swagger 调试向量检索，不经过完整 Agent。"""

    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)


class RetrievalHit(BaseModel):
    """一条 Qdrant 相似度检索结果。"""

    document_id: uuid.UUID
    filename: str
    chunk_index: int
    content: str
    score: float
