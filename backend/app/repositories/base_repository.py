from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from beanie import Document
from beanie.odm.fields import PydanticObjectId

T = TypeVar("T", bound=Document)


class BaseRepository(Generic[T]):
    """Generic repository for Beanie document models. Provides common CRUD and query operations."""

    def __init__(self, model: Type[T]) -> None:
        self.model = model

    async def create(self, data: Dict[str, Any]) -> T:
        """Create a new document from a dict, insert it, and return it."""
        document = self.model(**data)
        await document.insert()
        return document

    async def get_by_id(self, id: PydanticObjectId) -> Optional[T]:
        """Return a single document by ID, or None if not found."""
        return await self.model.get(id)

    async def get_one(self, filters: Dict[str, Any]) -> Optional[T]:
        """Return a single document matching the filters, or None."""
        return await self.model.find_one(filters)

    async def get_many(
        self,
        filters: Dict[str, Any],
        limit: int = 100,
        skip: int = 0,
    ) -> List[T]:
        """Return a list of documents matching the filters, with pagination."""
        return await self.model.find(filters).skip(skip).limit(limit).to_list()

    async def update(
        self,
        id: PydanticObjectId,
        update_data: Dict[str, Any],
    ) -> Optional[T]:
        """Find document by id, update fields, save, and return the updated document."""
        document = await self.model.get(id)
        if document is None:
            return None
        for key, value in update_data.items():
            if hasattr(document, key):
                setattr(document, key, value)
        await document.save()
        return document

    async def delete(self, id: PydanticObjectId) -> bool:
        """Delete document by id. Return True if deleted, False if not found."""
        document = await self.model.get(id)
        if document is None:
            return False
        await document.delete()
        return True

    async def count(self, filters: Dict[str, Any]) -> int:
        """Return the number of documents matching the filters."""
        return await self.model.find(filters).count()
