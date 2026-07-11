import logging
from motor.motor_asyncio import AsyncIOMotorClient
from backend.config import settings

logger = logging.getLogger(__name__)

class MongoDBManager:
    client: AsyncIOMotorClient = None
    db = None

mongodb_manager = MongoDBManager()

def get_mongodb_client() -> AsyncIOMotorClient:
    if mongodb_manager.client is None:
        logger.info("Connecting to MongoDB...")
        mongodb_manager.client = AsyncIOMotorClient(settings.MONGO_URI)
    return mongodb_manager.client

def get_mongodb_db():
    if mongodb_manager.db is None:
        client = get_mongodb_client()
        mongodb_manager.db = client[settings.MONGO_DB_NAME]
    return mongodb_manager.db

async def close_mongodb_connection():
    if mongodb_manager.client is not None:
        logger.info("Closing MongoDB connection...")
        mongodb_manager.client.close()
        mongodb_manager.client = None
        mongodb_manager.db = None
