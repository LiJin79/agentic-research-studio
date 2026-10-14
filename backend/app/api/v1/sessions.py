import uuid

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import SessionServiceDependency
from app.schemas.session import (
    MessageListResponse,
    SessionCreate,
    SessionListResponse,
    SessionResponse,
    SessionUpdate,
)

router = APIRouter()


@router.patch("/{session_id}", response_model=SessionResponse)
async def rename_session(
    session_id: uuid.UUID, payload: SessionUpdate, service: SessionServiceDependency
):
    """更新标题用于组织工作台会话，不改变消息和图状态。"""
    chat_session = await service.rename_session(session_id, payload.title)
    return SessionResponse.model_validate(chat_session)


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate,
    service: SessionServiceDependency,
) -> SessionResponse:
    """Create and return a persistent chat session."""
    chat_session = await service.create_session(title=payload.title, user_id=payload.user_id)
    return SessionResponse.model_validate(chat_session)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    service: SessionServiceDependency,
    user_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SessionListResponse:
    """Return sessions ordered by their latest activity time."""
    sessions, total = await service.list_sessions(
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return SessionListResponse(
        items=[SessionResponse.model_validate(item) for item in sessions],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: uuid.UUID,
    service: SessionServiceDependency,
) -> SessionResponse:
    """Return one session selected by UUID."""
    chat_session = await service.get_session(session_id)
    return SessionResponse.model_validate(chat_session)


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def list_session_messages(
    session_id: uuid.UUID,
    service: SessionServiceDependency,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MessageListResponse:
    """Return one session's messages in chronological order."""
    messages, total = await service.list_messages(
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return MessageListResponse(
        items=messages,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    service: SessionServiceDependency,
) -> Response:
    """Delete a session and return an empty HTTP 204 response."""
    await service.delete_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
