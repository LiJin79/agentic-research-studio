import hashlib
import math
from abc import ABC, abstractmethod
from functools import lru_cache

from app.core.config import get_settings
from app.llm.http import post_json


class BaseEmbeddingClient(ABC):
    """向量模型统一接口，屏蔽 Ollama、云 API 和本地实现的差异。"""

    dimensions: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """把一批文本转换成相同维度的浮点向量。"""


class HashEmbeddingClient(BaseEmbeddingClient):
    """零依赖教学向量器；适合跑通流程，不用于生产语义检索。"""

    def __init__(self, dimensions: int) -> None:
        """dimensions 决定 Qdrant collection 中每个向量的长度。"""
        self.dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """使用字符片段的稳定哈希构造归一化向量。"""
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        """把单段文字映射到固定桶中，并做 L2 归一化。"""
        vector = [0.0] * self.dimensions
        normalized = "".join(text.lower().split())
        tokens = [normalized[index : index + 3] for index in range(max(1, len(normalized) - 2))]
        if not tokens:
            tokens = [text or "empty"]

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self.dimensions
            vector[bucket] += 1.0

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class OllamaEmbeddingClient(BaseEmbeddingClient):
    """通过 Ollama `/api/embed` 调用本地 Embedding 模型。"""

    def __init__(self, *, base_url: str, model: str, dimensions: int, timeout: float) -> None:
        """保存 Ollama 地址及 Qdrant 预期的向量维度。"""
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量请求向量，并在入库前验证模型实际输出维度。"""
        if not texts:
            return []
        body = await post_json(
            f"{self.base_url}/api/embed", payload={"model": self.model, "input": texts}
        )
        vectors = body["embeddings"]
        # 每条向量都必须与输入一一对应，不能只校验第一条。
        if len(vectors) != len(texts) or any(
            len(v) != self.dimensions or not all(math.isfinite(x) for x in v) for v in vectors
        ):
            raise ValueError("Ollama Embedding 输出条数、维度或数字无效")
        return vectors


class OpenAICompatibleEmbeddingClient(BaseEmbeddingClient):
    """调用通义等 OpenAI 兼容的 `/embeddings` 接口。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        timeout: float,
    ) -> None:
        """保存云端 Embedding API 的连接配置。"""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """按响应中的 index 恢复与输入一致的向量顺序。"""
        if not self.api_key:
            raise ValueError("云端 Embedding 尚未配置 EMBEDDING_API_KEY")
        vectors = []
        batch_size = get_settings().embedding_batch_size
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            body = await post_json(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                payload={
                    "model": self.model,
                    "input": batch,
                    "dimensions": self.dimensions,
                    "encoding_format": "float",
                },
            )
            data = sorted(body["data"], key=lambda item: item["index"])
            if [item["index"] for item in data] != list(range(len(batch))):
                raise ValueError("Embedding 返回条数或顺序不正确")
            values = [item["embedding"] for item in data]
            if any(
                len(v) != self.dimensions or not all(math.isfinite(x) for x in v) for v in values
            ):
                raise ValueError("Embedding 输出维度不匹配或包含非有限数字")
            vectors.extend(values)
        return vectors


@lru_cache
def get_embedding_client() -> BaseEmbeddingClient:
    """根据配置创建一个可复用的 Embedding 客户端。"""
    settings = get_settings()
    provider = settings.embedding_provider.lower()
    if provider in {"hash", "local"}:
        return HashEmbeddingClient(settings.embedding_dimensions)
    if provider == "ollama":
        return OllamaEmbeddingClient(
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout=settings.llm_timeout_seconds,
        )
    if provider in {"dashscope", "openai-compatible"}:
        return OpenAICompatibleEmbeddingClient(
            # 根地址可对应不同地域/工作空间，不在这里覆盖用户配置。
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout=settings.llm_timeout_seconds,
        )
    raise ValueError(f"未知 EMBEDDING_PROVIDER: {provider}")
