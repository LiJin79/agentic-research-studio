import uuid

from qdrant_client import models

from app.core.config import get_settings
from app.vector.chunking import TextChunk
from app.vector.embeddings import BaseEmbeddingClient, get_embedding_client
from app.vector.qdrant import get_qdrant_client


class VectorIndexService:
    """负责 Qdrant collection 生命周期和文档向量的写入、删除。"""

    def __init__(self, embedding: BaseEmbeddingClient | None = None) -> None:
        """允许测试注入假的 Embedding 客户端。"""
        self.settings = get_settings()
        self.client = get_qdrant_client()
        self.embedding = embedding or get_embedding_client()

    async def ensure_collection(self) -> None:
        """首次入库时创建 collection，已存在时保持原数据不变。"""
        if await self.client.collection_exists(self.settings.vector_collection):
            info = await self.client.get_collection(self.settings.vector_collection)
            if info.config.params.vectors.size != self.embedding.dimensions:
                raise ValueError("已有集合维度不匹配，请使用新集合并重新索引")
            if "document_id" not in info.payload_schema:
                await self.client.create_payload_index(
                    self.settings.vector_collection,
                    "document_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                    wait=True,
                )
            return
        await self.client.create_collection(
            collection_name=self.settings.vector_collection,
            vectors_config=models.VectorParams(
                size=self.embedding.dimensions,
                distance=models.Distance.COSINE,
            ),
        )
        await self.client.create_payload_index(
            self.settings.vector_collection,
            "document_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )

    async def index_document(
        self,
        *,
        document_id: uuid.UUID,
        filename: str,
        chunks: list[TextChunk],
    ) -> int:
        """批量向量化文本块，并以可过滤的 payload 写入 Qdrant。"""
        await self.ensure_collection()
        vectors = await self.embedding.embed([chunk.content for chunk in chunks])
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(document_id, str(chunk.index))),
                vector=vector,
                payload={
                    "document_id": str(document_id),
                    "filename": filename,
                    "chunk_index": chunk.index,
                    "content": chunk.content,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        if points:
            await self.client.upsert(
                collection_name=self.settings.vector_collection,
                points=points,
                wait=True,
            )
        return len(points)

    async def delete_document(self, document_id: uuid.UUID, collection: str | None = None) -> None:
        """按 payload 中的 document_id 删除该文档的全部向量块。"""
        name = collection or self.settings.vector_collection
        if not await self.client.collection_exists(name):
            return
        await self.client.delete(
            collection_name=name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=str(document_id)),
                        )
                    ]
                )
            ),
            wait=True,
        )
