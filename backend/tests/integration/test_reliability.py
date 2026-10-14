import asyncio
import uuid

import pytest
from app.agents.graph import build_agent_graph
from app.cache.coordination import conversation_lock, enforce_rate_limit
from app.cache.redis import close_redis, get_redis_client
from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededError
from app.db.checkpointer import close_checkpointer
from app.db.models import ChatRun, Message
from app.llm.factory import MockLLMClient
from app.services.chat_service import ChatService
from app.services.session_service import SessionService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration


class SlowLLM(MockLLMClient):
    """取消测试模型在一个 token 后等待，用于确认任务实际终止。"""

    def __init__(self):
        """记录异步生成器是否执行了 finally。"""
        self.closed = False

    async def stream(self, messages):
        """产生真正增量后阻塞，关闭图应关闭这个生成器。"""
        try:
            yield "partial"
            await asyncio.Event().wait()
        finally:
            self.closed = True


def test_cancellation_persists_status_and_releases_lock(monkeypatch):
    """取消后运行和消息有终态，会话锁释放，模型生成任务不继续占资源。"""
    llm = SlowLLM()
    monkeypatch.setattr(
        "app.services.chat_service.get_agent_graph",
        lambda saver: build_agent_graph(checkpointer=saver, llm=llm),
    )
    monkeypatch.setattr("app.services.chat_service.get_llm_client", lambda: llm)

    async def scenario():
        """使用独立事务验证取消后的真实 PostgreSQL 与 Redis 状态。"""
        engine = create_async_engine(get_settings().postgres_dsn)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as database:
                sessions = SessionService(database)
                session = await sessions.create_session(title="cancellation-test", user_id=None)
                session_id = session.id
                run_id = uuid.uuid4()
                stream = ChatService(database).stream(
                    session_id=session_id, message="你好", use_web_search=False, request_id=run_id
                )
                async with asyncio.timeout(20):
                    async for event in stream:
                        if event["event"] == "token":
                            break
                    await stream.aclose()
                await database.rollback()
                run = await database.get(ChatRun, run_id)
                assert run.status == "cancelled"
                user = await database.scalar(
                    select(Message).where(Message.session_id == session_id)
                )
                assert user.message_metadata["status"] == "cancelled"
                assert not await get_redis_client().exists(f"lock:chat:{session_id}")
                assert llm.closed
                await sessions.delete_session(session_id)
        finally:
            await close_checkpointer()
            await close_redis()
            await engine.dispose()

    asyncio.run(scenario())


def test_redis_atomic_limit_and_owned_lock_release(monkeypatch):
    """限流键必须有 TTL，退出锁上下文后仅释放自己持有的租约。"""
    monkeypatch.setattr(get_settings(), "chat_rate_limit_per_minute", 2)

    async def scenario():
        """对唯一测试会话使用真实 Redis，结束后清理计数键。"""
        session_id = uuid.uuid4()
        redis = get_redis_client()
        try:
            await enforce_rate_limit(session_id)
            await enforce_rate_limit(session_id)
            with pytest.raises(RateLimitExceededError):
                await enforce_rate_limit(session_id)
            assert 0 < await redis.ttl(f"rate:chat:{session_id}") <= 60
            async with conversation_lock(session_id):
                assert await redis.exists(f"lock:chat:{session_id}")
            assert not await redis.exists(f"lock:chat:{session_id}")
        finally:
            await redis.delete(f"rate:chat:{session_id}")
            await close_redis()

    asyncio.run(scenario())
