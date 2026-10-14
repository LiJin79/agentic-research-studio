import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_agent_graph
from app.cache.coordination import ConversationBusyError, conversation_lock, enforce_rate_limit
from app.core.config import get_settings
from app.core.exceptions import ModelSelectionError, RateLimitExceededError, UpstreamServiceError
from app.db.checkpointer import create_checkpointer_context
from app.db.models import ChatRun
from app.db.repositories.session_repository import SessionRepository
from app.llm.base import LLMProviderError
from app.llm.catalog import get_model_profile, validate_model_selection
from app.llm.factory import get_llm_client
from app.schemas.chat import ChatResponse
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)


class ChatService:
    """统一流式/非流式问答，协调请求幂等、会话锁、持久化与 Agent 执行。"""

    def __init__(self, database: AsyncSession) -> None:
        """绑定本请求数据库会话，长耗时模型调用期间不持有数据库事务。"""
        self.database = database
        self.sessions = SessionRepository(database)
        self.session_service = SessionService(database)
        self.settings = get_settings()

    async def ask(
        self,
        *,
        session_id: uuid.UUID,
        message: str,
        use_web_search: bool,
        request_id: uuid.UUID | None = None,
        model_id: str | None = None,
    ) -> ChatResponse:
        """复用同一执行管线，非流式接口只返回最终的完整响应。"""
        execution = self._execute(
            session_id, message, use_web_search, request_id or uuid.uuid4(), model_id
        )
        try:
            async for item in execution:
                if item["event"] == "done":
                    return ChatResponse.model_validate(item["data"])
        finally:
            await execution.aclose()
        raise UpstreamServiceError("请求没有产生完成结果")

    async def stream(
        self,
        *,
        session_id: uuid.UUID,
        message: str,
        use_web_search: bool,
        request_id: uuid.UUID | None = None,
        model_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """将运行异常转成 SSE error 事件，响应头已发送时仍可告知前端失败。"""
        execution = self._execute(
            session_id, message, use_web_search, request_id or uuid.uuid4(), model_id
        )
        try:
            async for item in execution:
                yield item
        except (Exception,) as exc:
            logger.warning("chat_failed session=%s type=%s", session_id, type(exc).__name__)
            yield {
                "event": "error",
                "data": {
                    "message": str(exc)[:300],
                    "retryable": not isinstance(exc, (RateLimitExceededError, ModelSelectionError)),
                },
            }
        finally:
            await execution.aclose()

    async def _execute(
        self,
        session_id: uuid.UUID,
        message: str,
        use_web_search: bool,
        request_id: uuid.UUID,
        model_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """运行一次有截止时间的完整图；每轮显式重置全部 State 字段。"""
        model_id = None if model_id in {None, "default"} else model_id
        validate_model_selection(model_id)
        profile = get_model_profile(model_id)
        llm = get_llm_client(model_id) if model_id else get_llm_client()
        await self.session_service.get_session(session_id)
        await self.database.rollback()  # 结束只读事务，释放数据库连接。
        try:
            async with conversation_lock(session_id):
                old = await self.database.get(ChatRun, request_id)
                request_hash = hashlib.sha256(
                    json.dumps(
                        {"message": message, "use_web_search": use_web_search}
                        | ({"model_id": model_id} if model_id else {}),
                        sort_keys=True,
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                if old:
                    if old.session_id != session_id:
                        raise ConversationBusyError("请求 ID 已用于其他会话")
                    previous_hash = old.result.get("request_hash") or old.result.get(
                        "metadata", {}
                    ).get("request_hash")
                    if previous_hash and previous_hash != request_hash:
                        raise ConversationBusyError("同一请求 ID 不允许更改提问内容")
                    if old.status == "completed":
                        yield {"event": "done", "data": old.result}
                        return
                    raise ConversationBusyError("该请求已执行，请使用新的请求 ID 重试")
                await enforce_rate_limit(session_id)
                recent = await self.sessions.list_recent_messages(session_id=session_id, limit=30)
                history, size = [], 0
                for row in reversed(recent):
                    if row.message_metadata.get("status") in {"failed", "cancelled", "pending"}:
                        continue
                    if size + len(row.content) > self.settings.history_max_characters:
                        break
                    history.insert(0, {"role": row.role, "content": row.content})
                    size += len(row.content)
                user_message = await self.sessions.add_message(
                    session_id=session_id,
                    role="user",
                    content=message,
                    message_metadata={"request_id": str(request_id), "status": "pending"},
                )
                run = ChatRun(
                    id=request_id,
                    session_id=session_id,
                    status="running",
                    result={"request_hash": request_hash},
                )
                self.database.add(run)
                await self.database.commit()
                user_message_id = user_message.id
                initial = {
                    "question": message,
                    "history": history,
                    "use_web_search": use_web_search,
                    "context": [],
                    "sources": [],
                    "trace": [],
                    "revision_count": 0,
                    "route": "",
                    "route_reason": "",
                    "answer": "",
                    "answer_supported": False,
                    "verification_feedback": "",
                    "tool_events": [],
                    "search_domains": [],
                }
                result, started = dict(initial), time.monotonic()
                try:
                    yield {
                        "event": "status",
                        "data": {
                            "stage": "start",
                            "message": "开始分析",
                            "request_id": str(request_id),
                        },
                    }
                    async with asyncio.timeout(self.settings.chat_timeout_seconds):
                        async with create_checkpointer_context() as checkpointer:
                            graph = (
                                get_agent_graph(checkpointer, model_id)
                                if model_id
                                else get_agent_graph(checkpointer)
                            )
                            config = {
                                "configurable": {"thread_id": str(session_id)},
                                "recursion_limit": 40,
                            }
                            graph_stream = graph.astream(
                                initial, config=config, stream_mode=["custom", "updates"]
                            )
                            try:
                                async for mode, chunk in graph_stream:
                                    if mode == "custom":
                                        yield chunk
                                    else:
                                        for update in chunk.values():
                                            if isinstance(update, dict):
                                                result.update(update)
                            finally:
                                await graph_stream.aclose()
                    metadata = {
                        "route": result["route"],
                        "route_reason": result["route_reason"],
                        "revision_count": result["revision_count"],
                        "verified": result["answer_supported"],
                        "verification_status": (
                            "general_review"
                            if result["route"] == "direct"
                            else "insufficient_evidence"
                            if not result["context"]
                            else "evidence_checked"
                            if result["answer_supported"]
                            else "needs_review"
                        ),
                        "web_search_enabled": use_web_search,
                        "search_domains": result["search_domains"],
                        "tool_events": result["tool_events"],
                        "verification_feedback": result["verification_feedback"],
                        "duration_ms": round((time.monotonic() - started) * 1000),
                        "request_id": str(request_id),
                        "request_hash": request_hash,
                        "status": "completed",
                        "model_id": profile.id,
                        "model": profile.model,
                        "prompt_version": "2026-10-13-tools-v1",
                    }
                    response = ChatResponse(
                        session_id=session_id,
                        answer=result["answer"],
                        sources=result["sources"],
                        trace=result["trace"],
                        provider=llm.provider_name,
                        metadata=metadata,
                    )
                    stored = response.model_dump(mode="json")
                    assistant_message = await self.sessions.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=response.answer,
                        message_metadata=metadata
                        | {"sources": stored["sources"], "trace": stored["trace"]},
                    )
                    stored["metadata"]["message_id"] = str(assistant_message.id)
                    assistant_message.message_metadata = assistant_message.message_metadata | {
                        "message_id": str(assistant_message.id)
                    }
                    user_message.message_metadata = user_message.message_metadata | {
                        "status": "completed"
                    }
                    run.status, run.result = "completed", stored
                    await self.database.commit()
                except BaseException as exc:
                    failure_type = type(exc).__name__
                    await self.database.rollback()
                    status = (
                        "cancelled"
                        if isinstance(exc, (asyncio.CancelledError, GeneratorExit))
                        else "failed"
                    )

                    async def record_failure() -> None:
                        """中断也写入终态，失败问题不会污染后续模型历史。"""
                        failed_run = await self.database.get(ChatRun, request_id)
                        if failed_run:
                            failed_run.status = status
                            failed_run.error_message = failure_type
                        from app.db.models import Message

                        row = await self.database.get(Message, user_message_id)
                        if row:
                            row.message_metadata = row.message_metadata | {"status": status}
                        await self.database.commit()

                    await asyncio.shield(record_failure())
                    if isinstance(exc, TimeoutError):
                        raise UpstreamServiceError(
                            "本次 Agent 执行超时，请缩小问题范围后重试"
                        ) from exc
                    if isinstance(exc, LLMProviderError):
                        raise UpstreamServiceError(str(exc)) from exc
                    raise
                yield {"event": "done", "data": stored}
        except RedisError as exc:
            raise UpstreamServiceError("Redis 暂不可用，无法保证会话并发安全，请检查服务") from exc
