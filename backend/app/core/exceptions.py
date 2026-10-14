class ApplicationError(Exception):
    """Base exception for expected application-level failures."""


class ResourceNotFoundError(ApplicationError):
    """Raised when a requested business resource does not exist."""


class SessionNotFoundError(ResourceNotFoundError):
    """Raised when a requested chat session does not exist."""

    def __init__(self, session_id: object) -> None:
        """Build a session-specific not-found message."""
        super().__init__(f"Session {session_id} was not found")


class UserNotFoundError(ResourceNotFoundError):
    """Raised when a requested user does not exist."""

    def __init__(self, user_id: object) -> None:
        """Build a user-specific not-found message."""
        super().__init__(f"User {user_id} was not found")


class DocumentNotFoundError(ResourceNotFoundError):
    """Raised when a requested document does not exist."""

    def __init__(self, document_id: object) -> None:
        """Build a document-specific not-found message."""
        super().__init__(f"Document {document_id} was not found")


class RateLimitExceededError(ApplicationError):
    """Raised when one session sends too many chat requests in a minute."""


class UpstreamServiceError(ApplicationError):
    """Raised when an LLM or search provider cannot complete a request."""


class ModelSelectionError(ApplicationError):
    """请求选择了未知或尚未配置的模型，不应创建消息或调用供应商。"""
