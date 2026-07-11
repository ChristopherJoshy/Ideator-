"""Real, best-effort tools used by the chat pipeline.

These perform genuine work against configured backends. When a backend is missing
or unavailable they return an honest status instead of fabricated data.
"""

import json
import logging
import math

import httpx

from backend.config import settings
from backend.db.redis_client import get_redis_client
from backend.services.embeddings import embed

logger = logging.getLogger(__name__)

COLLISION_KEY = "ideator:collision_ideas"
MAX_STORED = 300


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def collision_check(text: str) -> str:
    """Semantic novelty check: compare the idea against previously stored ideas."""
    threshold = settings.COLLISION_SIMILARITY_THRESHOLD
    vector = await embed(text)
    if vector is None:
        return "Collision check skipped — embedding service unavailable."

    try:
        redis = get_redis_client()
        raw = await redis.lrange(COLLISION_KEY, 0, -1)
        best_score = 0.0
        best_text = None
        for item in raw:
            obj = json.loads(item)
            score = _cosine(vector, obj.get("vec", []))
            if score > best_score:
                best_score = score
                best_text = obj.get("text")

        # Persist this idea so future checks can detect self-similarity.
        await redis.lpush(COLLISION_KEY, json.dumps({"text": text, "vec": vector}))
        await redis.ltrim(COLLISION_KEY, 0, MAX_STORED - 1)
        await redis.expire(COLLISION_KEY, 60 * 60 * 24 * 30)
    except Exception as exc:
        logger.warning("Collision check storage failed: %s", exc)
        return "Collision check skipped — memory store unavailable."

    if best_text and best_score >= threshold:
        snippet = best_text if len(best_text) <= 80 else best_text[:77] + "…"
        return (
            f"Heads up — this overlaps with a previously stored idea "
            f"(similarity {best_score:.2f}): \"{snippet}\". Consider what makes yours different."
        )
    return (
        f"No similar claimed idea found (top similarity {best_score:.2f}, "
        f"threshold {threshold:.2f}). This looks novel."
    )


async def web_research(query: str) -> str | None:
    """Search the web via Tavily when a key is configured; otherwise return None.

    Returns a JSON-serialisable string with structured source data so the
    frontend can render individual result cards (title + url + snippet).
    """
    key = settings.TAVILY_API_KEY
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": query,
                    "max_results": 5,
                    "search_depth": "basic",
                    "include_answer": False,
                },
            )
            response.raise_for_status()
            results = response.json().get("results", [])
    except Exception as exc:
        logger.warning("Web research failed: %s", exc)
        return "Web research unavailable right now."

    if not results:
        return "No relevant sources found."

    # Build a structured payload the frontend can render as cards
    sources = []
    for item in results[:5]:
        title = item.get("title", "")
        url = item.get("url", "")
        snippet = item.get("content", "")[:200] if item.get("content") else ""
        if title or url:
            sources.append({"title": title, "url": url, "snippet": snippet})

    return json.dumps({"type": "web_research", "sources": sources})
