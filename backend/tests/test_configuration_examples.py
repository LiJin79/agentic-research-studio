"""公开配置入口与测试覆盖文件回归，不访问网络或读取真实 .env。"""

from pathlib import Path

from app.core.config import Settings
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def test_single_public_environment_example():
    """根目录只提供一个配置样例，模拟配置位于测试目录且不会自动加载。"""
    assert sorted(path.name for path in ROOT.glob(".env*.example")) == [".env.example"]
    assert (ROOT / "backend/tests/fixtures/env.demo.example").is_file()


def test_public_example_has_only_supported_fields_and_no_keys():
    """公开样例只列出支持的字段，密钥为空，数据库为明确占位值。"""
    values = dotenv_values(ROOT / ".env.example")
    fields = {name.upper() for name in Settings.model_fields}
    assert set(values) <= fields | {
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "OLLAMA_BASE_URL_DOCKER",
    }
    for name, value in values.items():
        if name.endswith(("API_KEY", "TOKEN")):
            assert value == "", name
    assert values["POSTGRES_PASSWORD"] == "change-this-password"
    assert "OPENALEX_API_KEY" not in values
    assert "openalex_api_key" not in Settings.model_fields


def test_explicit_demo_override_does_not_inherit_cloud_credentials():
    """模拟覆盖清空外部服务凭据，并显式使用不收费的测试模型。"""
    public = dotenv_values(ROOT / ".env.example")
    overrides = dotenv_values(ROOT / "backend/tests/fixtures/env.demo.example")
    cloud = {
        name: "not-a-real-secret" if name.endswith(("API_KEY", "TOKEN")) else value
        for name, value in public.items()
    }
    merged = cloud | overrides
    # APP_ACCESS_TOKEN protects the test workspace itself, not an external service.
    for name in public:
        if name.endswith(("API_KEY", "TOKEN")) and name != "APP_ACCESS_TOKEN":
            assert merged[name] == "", name
    settings = Settings(_env_file=None, **{name.lower(): value for name, value in merged.items()})
    assert settings.llm_provider == "mock"
    assert settings.embedding_provider == "hash"
    assert settings.embedding_dimensions == 384
    assert not settings.ollama_enabled
