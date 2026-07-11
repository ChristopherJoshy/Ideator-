import logging
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from backend.config import settings

logger = logging.getLogger(__name__)

class QdrantManager:
    client: AsyncQdrantClient = None

qdrant_manager = QdrantManager()

def get_qdrant_client() -> AsyncQdrantClient:
    if qdrant_manager.client is None:
        api_key = settings.QDRANT_API_KEY if settings.QDRANT_API_KEY else None
        
        # Robust handling for cloud cluster URLs vs local hosts
        if settings.QDRANT_HOST.startswith(("http://", "https://")):
            logger.info("Connecting to Qdrant Cloud...")
            qdrant_manager.client = AsyncQdrantClient(
                url=settings.QDRANT_HOST,
                api_key=api_key
            )
        else:
            logger.info("Connecting to local Qdrant...")
            qdrant_manager.client = AsyncQdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                api_key=api_key
            )
    return qdrant_manager.client

async def init_qdrant_collections():
    client = get_qdrant_client()
    collections = ["claimed_idea_vectors", "idea_dna_vectors"]
    
    for collection in collections:
        try:
            exists = await client.collection_exists(collection_name=collection)
            if not exists:
                logger.info(f"Creating Qdrant collection: {collection}...")
                await client.create_collection(
                    collection_name=collection,
                    vectors_config=models.VectorParams(
                        size=384,  # Dimension of sentence-transformers/all-MiniLM-L6-v2
                        distance=models.Distance.COSINE
                    )
                )
            else:
                logger.debug(f"Qdrant collection {collection} already exists.")
        except Exception as e:
            logger.error(f"Error checking/creating Qdrant collection {collection}: {e}")

async def close_qdrant_connection():
    if qdrant_manager.client is not None:
        logger.info("Closing Qdrant client connection...")
        try:
            await qdrant_manager.client.close()
        except AttributeError:
            pass
        qdrant_manager.client = None
