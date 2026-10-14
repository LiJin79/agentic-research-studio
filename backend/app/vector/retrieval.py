import uuid
from dataclasses import dataclass

from qdrant_client import models
from sqlalchemy import select

from app.cache.coordination import cached_search, search_cache_key
from app.core.config import get_settings
from app.db.models import Document
from app.db.session import session_factory
from app.vector.embeddings import BaseEmbeddingClient, get_embedding_client
from app.vector.qdrant import get_qdrant_client


@dataclass(slots=True)
class RetrievedChunk:
    """Qdrant 检索结果在业务层使用的稳定结构。"""

    document_id: uuid.UUID
    filename: str
    chunk_index: int
    content: str
    score: float


class KnowledgeRetriever:
    """把用户问题向量化，并从 Qdrant 查询最相近的文档片段。"""

    def __init__(self, embedding: BaseEmbeddingClient | None = None) -> None:
        """允许通过依赖注入替换真实 Embedding，便于单元测试。"""
        self.settings = get_settings()
        self.client = get_qdrant_client()
        self.embedding = embedding or get_embedding_client()

    async def search(self, query: str, *, limit: int | None = None) -> list[RetrievedChunk]:
        """执行向量相似度查询；collection 尚未创建时返回空列表。"""
        if not await self.client.collection_exists(self.settings.vector_collection):
            return []
        async with session_factory() as database:
            ids = list(
                (
                    await database.scalars(
                        select(Document.id).where(
                            Document.status == "ready",
                            Document.document_metadata["embedding_fingerprint"].astext
                            == self.settings.embedding_fingerprint,
                        )
                    )
                ).all()
            )
        if not ids:
            return []

        async def vectorize():
            """只缓存查询向量，不缓存文档正文，删文档后不会返回旧资料。"""
            return await self.embedding.embed([query])

        query_vector = (await cached_search(search_cache_key("query-vector", query), vectorize))[0]
        result = await self.client.query_points(
            collection_name=self.settings.vector_collection,
            query=query_vector,
            limit=limit or self.settings.retrieval_top_k,
            with_payload=True,
            score_threshold=self.settings.retrieval_min_score,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id", match=models.MatchAny(any=[str(value) for value in ids])
                    )
                ]
            ),
        )
        hits: list[RetrievedChunk] = []
        for point in result.points:
            payload = point.payload or {}
            hits.append(
                RetrievedChunk(
                    document_id=uuid.UUID(str(payload["document_id"])),
                    filename=str(payload.get("filename", "未知文件")),
                    chunk_index=int(payload.get("chunk_index", 0)),
                    content=str(payload.get("content", "")),
                    score=float(point.score),
                )
            )
        return hits
