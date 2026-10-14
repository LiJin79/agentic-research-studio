import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    """Input accepted when a client creates a conversation."""

    user_id: uuid.UUID | None = None
    title: str = Field(default="New conversation", min_length=1, max_length=200)


class SessionResponse(BaseModel):
    """Public representation of one persisted chat session."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    title: str
    created_at: datetime
    updated_at: datetime


class SessionUpdate(BaseModel):
    """重命名会话只允许修改标题，不接受所有权或内部状态字段。"""

    title: str = Field(min_length=1, max_length=200)


class SessionListResponse(BaseModel):
    """Paginated chat-session response."""

    items: list[SessionResponse]
    total: int
    limit: int
    offset: int


class MessageResponse(BaseModel):
    """Public representation of one persisted conversation message."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    message_metadata: dict[str, Any]
    created_at: datetime


class MessageListResponse(BaseModel):
    """Paginated message-history response."""

    items: list[MessageResponse]
    total: int
    limit: int
    offset: int
