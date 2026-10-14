from app.main import app


def test_openapi_contains_chat_and_document_workflows() -> None:
    """防止新增业务路由遗漏注册到总路由。"""
    paths = app.openapi()["paths"]

    assert "/api/v1/chat" in paths
    assert "/api/v1/chat/stream" in paths
    assert "/api/v1/documents/upload" in paths
    assert "/api/v1/documents/search/test" in paths
