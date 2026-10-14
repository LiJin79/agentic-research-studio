"""将数据库中的真实回答生成办公文档；接口遵守应用已有访问口令保护。"""

import asyncio
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.api.dependencies import DatabaseSession
from app.cache.coordination import enforce_rate_limit
from app.core.exceptions import UpstreamServiceError
from app.db.models import Message
from app.llm.base import LLMProviderError
from app.llm.factory import get_llm_client
from app.schemas.artifacts import ArtifactRequest
from app.services.artifact_service import ArtifactService

router = APIRouter()


@router.post("", response_class=Response)
async def create_artifact(payload: ArtifactRequest, database: DatabaseSession) -> Response:
    """读取已完成的助手回答，生成文件并直接下载，不接受客户端服务器路径。"""
    message = await database.get(Message, payload.message_id)
    if message is None:
        raise HTTPException(404, "回答不存在，请刷新会话后重试")
    if message.role != "assistant" or message.message_metadata.get("status") in {
        "failed",
        "cancelled",
        "pending",
    }:
        raise HTTPException(409, "只能导出已完成的助手回答")
    content, metadata, session_id = (
        message.content,
        dict(message.message_metadata),
        message.session_id,
    )
    await database.rollback()  # 模型生成期间不占用数据库事务或连接。
    await enforce_rate_limit(session_id)
    try:
        async with asyncio.timeout(180):
            # PPT 沿用该回答实际使用的模型，避免切换菜单后悄悄换供应商。
            model_id = metadata.get("model_id")
            llm = (
                get_llm_client(model_id) if model_id not in {None, "default"} else get_llm_client()
            )
            artifact = await ArtifactService(llm).create(
                title=payload.title,
                content=content,
                format=payload.format,
                sources=metadata.get("sources", []),
                verified=metadata.get("verified", False),
            )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (TimeoutError, LLMProviderError) as exc:
        raise UpstreamServiceError("办公文档生成失败，请检查模型服务或稍后重试") from exc
    return Response(
        artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(artifact.filename)}",
            "Cache-Control": "no-store",
        },
    )
