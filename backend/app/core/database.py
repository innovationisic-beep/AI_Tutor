from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.model_loader import get_document_models


async def connect_to_mongo(mongodb_url: str) -> None:
    """
    Create Motor client, connect to the database, and initialize Beanie
    with all discovered document models from app.models.
    """
    document_models = get_document_models()

    client = AsyncIOMotorClient(mongodb_url)
    database = client.get_default_database()

    await init_beanie(
        database=database,
        document_models=document_models,
    )
