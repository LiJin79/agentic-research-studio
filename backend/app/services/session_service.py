import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.coordination import conversation_lock
from app.core.exceptions import SessionNotFoundError, UserNotFoundError
from app.db.checkpointer import create_checkpointer_context
from app.db.models import ChatSession, Message
from app.db.repositories.session_repository import SessionRepository
from app.db.repositories.user_repository import UserRepository


class SessionService:
    """Apply session rules and own transaction boundaries."""

    def __init__(self, database: AsyncSession) -> None:
        """Reuse the current request transaction and initialize repositories."""
        self.database = database
        self.sessions = SessionRepository(database)
        self.users = UserRepository(database)

    async def create_session(
        self,
        *,
        title: str,
        user_id: uuid.UUID | None,
    ) -> ChatSession:
        """Validate the optional owner, create a session, and commit it."""
        if user_id is not None and await self.users.get_by_id(user_id) is None:
            raise UserNotFoundError(user_id)

        chat_session = await self.sessions.create(title=title, user_id=user_id)
        await self.database.commit()
        await self.database.refresh(chat_session)
        return chat_session

    async def get_session(self, session_id: uuid.UUID) -> ChatSession:
        """Return a session or raise the shared not-found business error."""
        chat_session = await self.sessions.get_by_id(session_id)
        if chat_session is None:
            raise SessionNotFoundError(session_id)
        return chat_session

    async def rename_session(self, session_id: uuid.UUID, title: str) -> ChatSession:
        """更新标题后显式读取数据库生成的时间，避免序列化触发隐式异步查询。"""
        chat_session = await self.get_session(session_id)
        chat_session.title = title.strip() or "新会话"
        await self.database.commit()
        # onupdate=func.now() 会使 updated_at 过期；refresh 在 await 中安全加载。
        await self.database.refresh(chat_session)
        return chat_session

    async def list_sessions(
        self,
        *,
        user_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ChatSession], int]:
        """Return one page of sessions and the matching total count."""
        return await self.sessions.list(user_id=user_id, limit=limit, offset=offset)

    async def delete_session(self, session_id: uuid.UUID) -> None:
        """Delete a session and commit the cascading message deletion."""
        async with conversation_lock(session_id):
            await self.get_session(session_id)
            async with create_checkpointer_context() as checkpointer:
                await checkpointer.adelete_thread(str(session_id))
            deleted = await self.sessions.delete(session_id)
            if not deleted:
                raise SessionNotFoundError(session_id)
            await self.database.commit()

    async def list_messages(
        self,
        *,
        session_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[Message], int]:
        """Validate the session before returning its paginated history."""
        await self.get_session(session_id)
        return await self.sessions.list_messages(
            session_id=session_id,
            limit=limit,
            offset=offset,
        )

    async def append_message(
        self,
        *,
        session_id: uuid.UUID,
        role: str,
        content: str,
        message_metadata: dict | None = None,
    ) -> Message:
        """Internal entry point used later by ChatService, not a public HTTP endpoint."""
        await self.get_session(session_id)
        message = await self.sessions.add_message(
            session_id=session_id,
            role=role,
            content=content,
            message_metadata=message_metadata,
        )
        await self.database.commit()
        await self.database.refresh(message)
        return message
