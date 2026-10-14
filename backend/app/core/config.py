import hashlib
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """集中读取并校验环境变量，作为整个应用唯一的配置入口。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Agentic RAG"
    app_version: str = "0.1.0"
    app_env: str = "development"
    app_debug: bool = False
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )

    # 公开默认配置仅使用占位值，实际连接凭据由本机 .env 或容器环境注入。
    postgres_dsn: str = "postgresql+asyncpg://agent_user:change-this-password@postgres:5432/agent_db"
    langgraph_postgres_dsn: str = "postgresql://agent_user:change-this-password@postgres:5432/agent_db"
    redis_url: str = "redis://redis:6379/0"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "agent_documents"

    # mock 让学习者在没有模型或 API Key 时也能跑通完整业务链路。
    llm_provider: str = "dashscope"
    llm_model: str = "qwen-plus"
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 120.0
    llm_temperature: float = 0.2

    # 可选生成模型各用自己的密钥；不会修改 Embedding 模型或向量集合。
    dashscope_api_key: str = Field(default="", repr=False)
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    deepseek_api_key: str = Field(default="", repr=False)
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    minimax_api_key: str = Field(default="", repr=False)
    minimax_model: str = "MiniMax-M3"
    minimax_base_url: str = "https://api.minimax.cn/v1"
    minimax_max_tokens: int = Field(default=8192, ge=256, le=32768)
    zhipu_api_key: str = Field(default="", repr=False)
    zhipu_model: str = "glm-4.7"
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    ollama_enabled: bool = False
    ollama_model: str = "qwen2.5:1.5b"
    ollama_base_url: str = "http://localhost:11435"

    embedding_provider: str = "dashscope"
    embedding_model: str = "text-embedding-v4"
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_api_key: str = ""
    embedding_dimensions: int = Field(default=1024, ge=1, le=4096)

    upload_dir: Path = Path("data/uploads")
    max_upload_bytes: int = 10 * 1024 * 1024
    chunk_size: int = Field(default=800, ge=100, le=8000)
    chunk_overlap: int = Field(default=120, ge=0, le=2000)
    retrieval_top_k: int = Field(default=5, ge=1, le=20)

    tavily_api_key: str = ""
    web_search_provider: str = "bocha"
    bocha_api_key: str = ""
    bocha_base_url: str = "https://api.bocha.cn"
    web_search_max_results: int = Field(default=5, ge=1, le=10)
    agent_max_revisions: int = Field(default=2, ge=0, le=5)
    chat_rate_limit_per_minute: int = Field(default=30, ge=1, le=1000)

    # 边界限制同时约束工具、上下文和网络开销。
    app_access_token: str = ""
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_max_tokens: int = Field(default=4096, ge=256, le=32768)
    chat_timeout_seconds: int = Field(default=300, ge=30, le=900)
    agent_max_tool_iterations: int = Field(default=3, ge=1, le=8)
    history_max_characters: int = Field(default=12000, ge=1000, le=100000)
    context_max_characters: int = Field(default=16000, ge=1000, le=100000)
    context_max_sources: int = Field(default=12, ge=1, le=30)
    evidence_max_characters: int = Field(default=2400, ge=100, le=10000)
    retrieval_min_score: float = Field(default=0.25, ge=0, le=1)
    search_cache_seconds: int = Field(default=300, ge=1, le=3600)
    # 可选工具只在服务端读凭据；没有 Key 时不会绑定给模型。
    github_token: str = Field(default="", repr=False)
    context7_api_key: str = Field(default="", repr=False)
    amap_api_key: str = Field(default="", repr=False)
    qweather_api_key: str = Field(default="", repr=False)
    qweather_api_host: str = ""
    tool_timeout_seconds: float = Field(default=15, ge=3, le=30)
    tool_max_response_bytes: int = Field(default=2_000_000, ge=10000, le=5_000_000)
    tool_max_calls: int = Field(default=9, ge=1, le=20)
    embedding_batch_size: int = Field(default=10, ge=1, le=10)
    worker_poll_seconds: float = 2.0
    ingestion_timeout_seconds: int = 600

    @property
    def embedding_fingerprint(self) -> str:
        """模型和维度生成独立索引版本，避免混用不同向量空间。"""
        value = f"{self.embedding_provider}:{self.embedding_model}:{self.embedding_dimensions}"
        return hashlib.sha256(value.encode()).hexdigest()[:12]

    @property
    def vector_collection(self) -> str:
        """使用带模型指纹的集合名，切换模型不会破坏已有集合。"""
        return f"{self.qdrant_collection}_{self.embedding_fingerprint}"

    @property
    def web_search_configured(self) -> bool:
        """界面只获知当前搜索供应商是否配置，不返回任何密钥。"""
        return bool(
            self.bocha_api_key if self.web_search_provider == "bocha" else self.tavily_api_key
        )


@lru_cache
def get_settings() -> Settings:
    """每个进程只构建一次配置对象，避免重复解析环境变量。"""
    return Settings()
