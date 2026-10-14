import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UserRepository:
    """Provide database queries related to users."""

    def __init__(self, database: AsyncSession) -> None:
        """Reuse the transaction owned by the current request."""
        self.database = database

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return a user by primary key, or None when it does not exist."""
        return await self.database.get(User, user_id)
