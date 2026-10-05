from typing import List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.identification.users import User
from app.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User document operations."""

    def __init__(self) -> None:
        super().__init__(User)

    async def get_by_email(
        self,
        email: str,
        organization_id: Optional[PydanticObjectId] = None,
    ) -> Optional[User]:
        """Return the user with the given email. Optionally scoped by organization_id."""
        filters: dict = {"email": email.strip().lower()}
        if organization_id is not None:
            filters["organization_id"] = organization_id
        return await self.get_one(filters)

    async def get_users_by_role(
        self,
        role: str,
        organization_id: Optional[PydanticObjectId] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[User]:
        """Return users with the specified role. Optionally scoped by organization_id."""
        filters: dict = {"role": role}
        if organization_id is not None:
            filters["organization_id"] = organization_id
        return await self.get_many(filters, limit=limit, skip=skip)


def get_user_repository() -> UserRepository:
    """FastAPI dependency: return a UserRepository instance."""
    return UserRepository()
