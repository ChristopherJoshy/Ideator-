import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Get project root (2 levels up from backend/config/settings.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    APP_ENV: str = "development"
    DEBUG: bool = True
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # MongoDB Configuration
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "ideator_dev"

    # Redis Configuration
    REDIS_URL: str = "redis://localhost:6379/0"

    # Qdrant Configuration
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str = ""

    # Vector Search / Embeddings
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    COLLISION_SIMILARITY_THRESHOLD: float = 0.85

    # Telegram Bot Configuration
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # API Keys
    GROQ_API_KEYS: str = ""
    CEREBRAS_API_KEYS: str = ""
    MISTRAL_API_KEYS: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    TAVILY_API_KEY: str = ""
    YOUTUBE_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
