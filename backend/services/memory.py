"""Small, failure-tolerant memory helpers for the MVP chat flow."""

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime

from qdrant_client.http import models

from backend.db.redis_client import get_redis_client
from backend.db.qdrant_client import get_qdrant_client

logger = logging.getLogger(__name__)

REDIS_FACTS_PREFIX = "ideator:chat:{chat_id}:facts"


def _stable_vector(text: str, dimensions: int = 384) -> list[float]:
    """Produce a deterministic, normalized fallback vector without model startup cost.

    The chat remains usable on small deployments; this can be replaced with a
    semantic embedding provider later without changing the stored payloads.
    """
    digest = hashlib.sha512(text.encode("utf-8")).digest()
    values = [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(dimensions)]
    magnitude = sum(value * value for value in values) ** 0.5 or 1.0
    return [value / magnitude for value in values]


async def remember_message(*, message_id: str, chat_id: str, user_id: str, sender: str, content: str) -> None:
    """Write short-term Redis and durable Qdrant memory without blocking chat."""
    entry = {
        "id": message_id,
        "chat_id": chat_id,
        "user_id": user_id,
        "sender": sender,
        "content": content,
        "created_at": datetime.utcnow().isoformat(),
    }

    try:
        redis = get_redis_client()
        key = f"ideator:chat:{chat_id}:recent"
        await redis.lpush(key, json.dumps(entry))
        await redis.ltrim(key, 0, 19)
        await redis.expire(key, 60 * 60 * 24 * 30)
    except Exception as exc:
        logger.warning("Redis memory unavailable: %s", exc)

    try:
        qdrant = get_qdrant_client()
        await qdrant.upsert(
            collection_name="idea_dna_vectors",
            points=[models.PointStruct(id=message_id, vector=_stable_vector(content), payload=entry)],
            wait=False,
        )
    except Exception as exc:
        logger.warning("Qdrant memory unavailable: %s", exc)


def remember_in_background(**kwargs) -> None:
    """Memory failures must never hold up a response stream."""
    asyncio.create_task(remember_message(**kwargs))


async def forget_chat(chat_id: str) -> None:
    """Remove all stored memory associated with a deleted chat session."""
    try:
        redis = get_redis_client()
        await redis.delete(REDIS_FACTS_PREFIX.format(chat_id=chat_id))
    except Exception as exc:
        logger.warning("Redis memory cleanup failed: %s", exc)
    try:
        qdrant = get_qdrant_client()
        await qdrant.delete(
            collection_name="idea_dna_vectors",
            points_selector=models.Filter(
                must=[models.FieldCondition(key="chat_id", match=models.MatchValue(value=chat_id))]
            ),
        )
    except Exception as exc:
        logger.warning("Qdrant memory cleanup failed: %s", exc)


async def remember_session_facts(chat_id: str, user_id: str, facts: list[str]) -> None:
    """Persist durable, session-level takeaways so the agent remembers them later."""
    if not facts:
        return
    clean = [str(fact).strip() for fact in facts if str(fact).strip()]
    if not clean:
        return
    try:
        redis = get_redis_client()
        key = REDIS_FACTS_PREFIX.format(chat_id=chat_id)
        await redis.rpush(key, *[json.dumps({"fact": fact, "user_id": user_id}) for fact in clean])
        await redis.expire(key, 60 * 60 * 24 * 30)
    except Exception as exc:
        logger.warning("Redis session-fact storage failed: %s", exc)
    try:
        qdrant = get_qdrant_client()
        points = [
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=_stable_vector(fact),
                payload={"chat_id": chat_id, "user_id": user_id, "fact": fact},
            )
            for fact in clean
        ]
        await qdrant.upsert(collection_name="idea_dna_vectors", points=points, wait=False)
    except Exception as exc:
        logger.warning("Qdrant session-fact storage failed: %s", exc)


async def get_session_facts(chat_id: str) -> list[str]:
    """Return the accumulated durable takeaways for a session (oldest first)."""
    facts = []
    try:
        redis = get_redis_client()
        key = REDIS_FACTS_PREFIX.format(chat_id=chat_id)
        raw = await redis.lrange(key, 0, -1)
        facts = [json.loads(item).get("fact", "") for item in raw if item]
    except Exception as exc:
        logger.warning("Redis session-fact retrieval failed: %s", exc)

    if not facts:
        try:
            qdrant = get_qdrant_client()
            results = await qdrant.scroll(
                collection_name="idea_dna_vectors",
                scroll_filter=models.Filter(
                    must=[models.FieldCondition(key="chat_id", match=models.MatchValue(value=chat_id))]
                ),
                limit=100,
                with_payload=True,
                with_vectors=False,
            )
            points = results[0]
            facts = [p.payload.get("fact") for p in points if p.payload and p.payload.get("fact")]
            if facts:
                logger.info("Retrieved %d session facts from Qdrant fallback for chat_id %s", len(facts), chat_id)
        except Exception as exc:
            logger.warning("Qdrant session-fact fallback retrieval failed: %s", exc)

    return facts
