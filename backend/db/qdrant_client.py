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

# Per-collection vector dimensions.
#   - claimed_idea_vectors: semantic novelty check, uses OpenAI text-embedding-3-small (1536)
#   - idea_dna_vectors: lightweight memory fallback, uses deterministic _stable_vector (384)
COLLECTION_DIMENSIONS = {
    "claimed_idea_vectors": 1536,
    "idea_dna_vectors": 384,
}


async def init_qdrant_collections():
    client = get_qdrant_client()
    collections = list(COLLECTION_DIMENSIONS.keys())

    for collection in collections:
        expected_size = COLLECTION_DIMENSIONS[collection]
        try:
            exists = await client.collection_exists(collection_name=collection)
            if exists:
                try:
                    info = await client.get_collection(collection_name=collection)
                    # Qdrant v1.x returns vectors config size under config.params.vectors.size
                    current_size = 0
                    if hasattr(info.config.params, "vectors") and hasattr(info.config.params.vectors, "size"):
                        current_size = info.config.params.vectors.size
                    elif hasattr(info.config.params, "vectors") and isinstance(info.config.params.vectors, dict):
                        current_size = info.config.params.vectors.get("size", 0)

                    if current_size != expected_size:
                        logger.warning(
                            f"Dimension mismatch on collection {collection}: expected {expected_size}, "
                            f"got {current_size}. Re-creating collection..."
                        )
                        await client.delete_collection(collection_name=collection)
                        exists = False
                except Exception as check_err:
                    logger.warning(f"Failed to check details for collection {collection}: {check_err}")

            if not exists:
                logger.info(f"Creating Qdrant collection: {collection} (dim={expected_size})...")
                await client.create_collection(
                    collection_name=collection,
                    vectors_config=models.VectorParams(
                        size=expected_size,
                        distance=models.Distance.COSINE
                    )
                )
            else:
                logger.debug(f"Qdrant collection {collection} already exists.")
            
            # Create payload index for chat_id (required by Qdrant filter delete/querying)
            try:
                await client.create_payload_index(
                    collection_name=collection,
                    field_name="chat_id",
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
                logger.debug(f"Created chat_id payload index for collection: {collection}")
            except Exception as e:
                logger.warning(f"Could not create chat_id payload index on {collection}: {e}")
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
