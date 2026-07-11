import time
import logging
from fastapi import APIRouter, HTTPException, status
from backend.db import get_mongodb_db, get_redis_client, get_qdrant_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["Health Checks"])

@router.get("", status_code=status.HTTP_200_OK)
async def overall_health():
    """
    Get overall system health including MongoDB, Redis, and Qdrant.
    """
    services = {
        "mongodb": "unknown",
        "redis": "unknown",
        "qdrant": "unknown"
    }
    
    # Check MongoDB
    try:
        db = get_mongodb_db()
        await db.command("ping")
        services["mongodb"] = "ok"
    except Exception as e:
        logger.error(f"MongoDB healthcheck failed: {e}")
        services["mongodb"] = f"error: {str(e)}"

    # Check Redis
    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        services["redis"] = "ok"
    except Exception as e:
        logger.error(f"Redis healthcheck failed: {e}")
        services["redis"] = f"error: {str(e)}"

    # Check Qdrant
    try:
        qdrant_client = get_qdrant_client()
        await qdrant_client.get_collections()
        services["qdrant"] = "ok"
    except Exception as e:
        logger.error(f"Qdrant healthcheck failed: {e}")
        services["qdrant"] = f"error: {str(e)}"

    overall_status = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    
    response = {
        "status": overall_status,
        "services": services
    }
    
    if overall_status == "degraded":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response
        )
        
    return response

@router.get("/mongo")
async def health_mongo():
    """Check MongoDB latency."""
    start_time = time.perf_counter()
    try:
        db = get_mongodb_db()
        await db.command("ping")
        latency = (time.perf_counter() - start_time) * 1000
        return {"status": "ok", "latency_ms": round(latency, 2)}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "message": str(e)}
        )

@router.get("/redis")
async def health_redis():
    """Check Redis latency."""
    start_time = time.perf_counter()
    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        latency = (time.perf_counter() - start_time) * 1000
        return {"status": "ok", "latency_ms": round(latency, 2)}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "message": str(e)}
        )

@router.get("/qdrant")
async def health_qdrant():
    """Check Qdrant health and retrieve collection status."""
    start_time = time.perf_counter()
    try:
        qdrant_client = get_qdrant_client()
        collections_response = await qdrant_client.get_collections()
        latency = (time.perf_counter() - start_time) * 1000
        collections = [col.name for col in collections_response.collections]
        return {
            "status": "ok",
            "latency_ms": round(latency, 2),
            "collections": collections
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "message": str(e)}
        )
