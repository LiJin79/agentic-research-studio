"""服务器端生成模型目录：前端只能选择 ID，不能提交地址或供应商密钥。"""

from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.exceptions import ModelSelectionError


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """一次模型调用的不可变配置，密钥不参与 repr 或公开接口。"""

    id: str
    label: str
    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    configured: bool
    key_env: str

    def public(self) -> dict:
        """仅公开选择菜单需要的信息，不返回密钥、端点或其他服务器配置。"""
        return {
            "id": self.id,
            "label": self.label,
            "provider": self.provider,
            "model": self.model,
            "configured": self.configured,
            "key_env": self.key_env,
        }


def model_catalog() -> list[ModelProfile]:
    """保留当前默认配置，追加国内供应商及需要显式启用的 Ollama 入口。"""
    s = get_settings()
    qwen_key = s.dashscope_api_key or (s.llm_api_key if s.llm_provider == "dashscope" else "")
    qwen_url = s.llm_base_url if s.llm_provider == "dashscope" else s.dashscope_base_url
    deepseek_key = s.deepseek_api_key or (s.llm_api_key if s.llm_provider == "deepseek" else "")
    minimax_key = s.minimax_api_key or (s.llm_api_key if s.llm_provider == "minimax" else "")
    zhipu_key = s.zhipu_api_key or (s.llm_api_key if s.llm_provider == "zhipu" else "")
    return [
        ModelProfile(
            "default",
            "当前默认",
            s.llm_provider,
            s.llm_model,
            s.llm_base_url,
            s.llm_api_key,
            s.llm_provider in {"mock", "ollama"} or bool(s.llm_api_key),
            "LLM_API_KEY",
        ),
        ModelProfile(
            "qwen-plus",
            "通义 Qwen Plus",
            "dashscope",
            "qwen-plus",
            qwen_url,
            qwen_key,
            bool(qwen_key),
            "DASHSCOPE_API_KEY / LLM_API_KEY",
        ),
        ModelProfile(
            "qwen-flash",
            "通义 Qwen Flash",
            "dashscope",
            "qwen-flash",
            qwen_url,
            qwen_key,
            bool(qwen_key),
            "DASHSCOPE_API_KEY / LLM_API_KEY",
        ),
        ModelProfile(
            "deepseek",
            "DeepSeek",
            "deepseek",
            s.deepseek_model,
            s.deepseek_base_url,
            deepseek_key,
            bool(deepseek_key),
            "DEEPSEEK_API_KEY",
        ),
        ModelProfile(
            "minimax",
            "MiniMax",
            "minimax",
            s.minimax_model,
            s.minimax_base_url,
            minimax_key,
            bool(minimax_key),
            "MINIMAX_API_KEY",
        ),
        ModelProfile(
            "zhipu",
            "智谱 GLM",
            "zhipu",
            s.zhipu_model,
            s.zhipu_base_url,
            zhipu_key,
            bool(zhipu_key),
            "ZHIPU_API_KEY",
        ),
        ModelProfile(
            "ollama",
            "Ollama 本地",
            "ollama",
            s.ollama_model,
            s.ollama_base_url,
            "",
            s.ollama_enabled,
            "OLLAMA_ENABLED",
        ),
    ]


def get_model_profile(model_id: str | None = None) -> ModelProfile:
    """只允许服务器目录中的 ID，未知 ID 不能用于拼接任意模型请求。"""
    for profile in model_catalog():
        if profile.id == (model_id or "default"):
            return profile
    raise ModelSelectionError("未知生成模型，请刷新页面后重新选择")


def validate_model_selection(model_id: str | None) -> None:
    """非默认模型必须先配置，失败时在创建消息和扣用量之前拒绝请求。"""
    profile = get_model_profile(model_id)
    if model_id not in {None, "default"} and not profile.configured:
        raise ModelSelectionError(f"{profile.label} 尚未配置 {profile.key_env}")
