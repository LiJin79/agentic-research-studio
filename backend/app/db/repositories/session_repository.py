from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatSession, Message


class SessionRepository:
    """Contain SQLAlchemy queries; transaction commits belong to the service layer."""

    def __init__(self, database: AsyncSession) -> None:
        """Reuse the transaction supplied by the service layer."""
        self.database = database

    async def create(self, *, title: str, user_id: uuid.UUID | None) -> ChatSession:
        """Add a new session and flush its generated identifier."""
        chat_session = ChatSession(title=title, user_id=user_id)
        self.database.add(chat_session)
        # flush assigns database-generated fields while keeping the transaction open.
        await self.database.flush()
        return chat_session

    async def get_by_id(self, session_id: uuid.UUID) -> ChatSession | None:
        """Return a session by primary key or None."""
        return await self.database.get(ChatSession, session_id)

    async def list(
        self,
        *,
        user_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ChatSession], int]:
        """Build optional owner filtering and pagination at the SQL layer."""
        filters = []
        if user_id is not None:
            filters.append(ChatSession.user_id == user_id)

        query = (
            select(ChatSession)
            .where(*filters)
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_query = select(func.count(ChatSession.id)).where(*filters)

        sessions = list((await self.database.scalars(query)).all())
        total = int((await self.database.scalar(count_query)) or 0)
        return sessions, total

    async def delete(self, session_id: uuid.UUID) -> bool:
        """Delete by identifier and report whether a row existed."""
        # The database foreign key cascades deletion to all messages in the session.
        result = await self.database.execute(
            delete(ChatSession).where(ChatSession.id == session_id)
        )
        return bool(result.rowcount)

    async def list_messages(
        self,
        *,
        session_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[Message], int]:
        """Return messages in chronological order with a total count."""
        query = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        count_query = select(func.count(Message.id)).where(Message.session_id == session_id)

        messages = list((await self.database.scalars(query)).all())
        total = int((await self.database.scalar(count_query)) or 0)
        return messages, total

    async def list_recent_messages(
        self,
        *,
        session_id: uuid.UUID,
        limit: int,
    ) -> list[Message]:
        """读取最近消息后恢复为时间正序，供模型构造对话历史。"""
        query = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        newest_first = list((await self.database.scalars(query)).all())
        return list(reversed(newest_first))

    async def add_message(
        self,
        *,
        session_id: uuid.UUID,
        role: str,
        content: str,
        message_metadata: dict | None = None,
    ) -> Message:
        """Append a message and update the parent session activity time."""
        message = Message(
            session_id=session_id,
            role=role,
            content=content,
            message_metadata=message_metadata or {},
        )
        self.database.add(message)
        # 触发会话 updated_at 更新，让会话列表按最近交互排序。
        await self.database.execute(
            update(ChatSession).where(ChatSession.id == session_id).values(updated_at=func.now())
        )
        await self.database.flush()
        return message
