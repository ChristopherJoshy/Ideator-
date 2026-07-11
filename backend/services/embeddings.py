"""Real text embeddings used for semantic collision detection.

Uses the OpenAI embeddings API when a key is configured. Failures return None so
callers can degrade gracefully instead of fabricating similarity scores.
"""

import logging

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"


async def embed(text: str) -> list[float] | None:
    key = settings.OPENAI_API_KEY
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": EMBEDDING_MODEL, "input": text},
            )
            response.raise_for_status()
            return response.json()["data"][0]["embedding"]
    except Exception as exc:
        logger.warning("Embedding generation failed: %s", exc)
        return None
