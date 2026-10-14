from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService
from app.services.session_service import SessionService

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_session_service(database: DatabaseSession) -> SessionService:
    """为一次请求创建会话业务服务。"""
    return SessionService(database)


SessionServiceDependency = Annotated[SessionService, Depends(get_session_service)]


def get_document_service(database: DatabaseSession) -> DocumentService:
    """为一次请求创建文档业务服务。"""
    return DocumentService(database)


DocumentServiceDependency = Annotated[DocumentService, Depends(get_document_service)]


def get_chat_service(database: DatabaseSession) -> ChatService:
    """为一次请求创建聊天编排服务。"""
    return ChatService(database)


ChatServiceDependency = Annotated[ChatService, Depends(get_chat_service)]
