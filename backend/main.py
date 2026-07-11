import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.db.mongodb import get_mongodb_client, close_mongodb_connection
from backend.db.redis_client import get_redis_client, close_redis_connection
from backend.db.qdrant_client import get_qdrant_client, init_qdrant_collections, close_qdrant_connection
from backend.routers import health_router
from backend.routers.auth import router as auth_router
from backend.routers.chat import router as chat_router

# Configure logging
logging.basicConfig(
    # Keep request diagnostics useful without allowing third-party clients to
    # emit connection URLs or credentials in development logs.
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
for noisy_logger in ("httpx", "httpcore", "pymongo", "redis"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks
    logger.info("Initializing services on startup...")
    
    # 1. Connect MongoDB
    try:
        get_mongodb_client()
        logger.info("MongoDB client connected.")
    except Exception as e:
        logger.error(f"Failed to connect MongoDB: {e}")
        
    # 2. Connect Redis
    try:
        get_redis_client()
        logger.info("Redis client connected.")
    except Exception as e:
        logger.error(f"Failed to connect Redis: {e}")
        
    # 3. Connect Qdrant and init collections
    try:
        get_qdrant_client()
        logger.info("Qdrant client connected.")
        await init_qdrant_collections()
        logger.info("Qdrant collections checked/initialized.")
    except Exception as e:
        logger.error(f"Failed to connect Qdrant: {e}")

    # 4. Start periodic Telegram metrics reporter task
    import asyncio
    from backend.services.telegram_logger import periodic_metrics_reporter
    metrics_task = asyncio.create_task(periodic_metrics_reporter())

    yield
    
    # Shutdown tasks
    logger.info("Shutting down services...")
    metrics_task.cancel()
    try:
        await metrics_task
    except asyncio.CancelledError:
        pass
    await close_mongodb_connection()
    await close_redis_connection()
    await close_qdrant_connection()
    logger.info("Shutdown sequence complete.")

app = FastAPI(
    title="Ideator API",
    description="Backend API for the Ideator collision-avoidance idea platform.",
    version="0.1.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
import os

static_path = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_path, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Include routers
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")

@app.get("/")
async def root():
    return {
        "message": "Welcome to the Ideator API. Health check endpoints are available at /api/health",
        "env": settings.APP_ENV
    }
