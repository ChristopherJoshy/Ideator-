import asyncio
import html
import logging
from datetime import datetime, timedelta

import httpx

from backend.config import settings
from backend.db.mongodb import get_mongodb_db

logger = logging.getLogger(__name__)


def safe_truncate(text: str, max_chars: int = 3000) -> str:
    """Safe truncation to keep log message size within Telegram limits."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n<i>[Truncated due to length limit]</i>"


async def _get_active_users_metrics() -> str:
    """
    Computes active user metrics (unique users in last 15m and 24h) and top active users (most messages).
    Returns a formatted HTML string.
    """
    try:
        db = get_mongodb_db()
        now = datetime.utcnow()
        
        # 1. Current Concurrency (15m) and Daily Active Users (24h)
        active_15m = await db.chats.distinct("user_id", {"updated_at": {"$gte": now - timedelta(minutes=15)}})
        active_24h = await db.chats.distinct("user_id", {"updated_at": {"$gte": now - timedelta(hours=24)}})
        
        # 2. Total registered users (All time)
        total_users = await db.users.count_documents({})
        
        # 3. Best Active Users (top 5 by messages count)
        pipeline = [
            {"$unwind": "$messages"},
            {"$group": {"_id": "$user_id", "message_count": {"$sum": 1}}},
            {"$sort": {"message_count": -1}},
            {"$limit": 5}
        ]
        cursor = db.chats.aggregate(pipeline)
        top_users = []
        async for doc in cursor:
            user_id = doc["_id"]
            user_doc = await db.users.find_one({"_id": user_id})
            display_name = user_doc.get("display_name", "Unknown") if user_doc else "Unknown"
            top_users.append(f"• {display_name}: {doc['message_count']} msgs")
            
        top_users_str = "\n".join(top_users) if top_users else "None"
        
        return (
            f"\n\n<b>📊 Active User Metrics</b>\n"
            f"<b>Active Users (15m):</b> {len(active_15m)}\n"
            f"<b>Active Users (24h):</b> {len(active_24h)}\n"
            f"<b>Total Users (All time):</b> {total_users}\n"
            f"<b>Top Active Users:</b>\n{top_users_str}"
        )
    except Exception as exc:
        logger.warning("Failed to compute active users metrics for Telegram: %s", exc)
        return ""


async def log_to_telegram(text: str):
    """
    Asynchronously send a message log to the configured Telegram bot.
    Fails silently on connection issues so it never disrupts user requests.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    
    if not token or not chat_id or token == "mock_telegram_bot_token" or chat_id == "mock_telegram_chat_id" or not token.strip():
        logger.debug("Telegram logging is not configured or is using mock credentials.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error(f"Telegram API responded with status {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Failed to send log to Telegram: {e}")


async def log_chat_message(sender_name: str, message: str, is_user: bool = True, chat_id: str = ""):
    """
    Formats and logs a user or assistant message to Telegram.
    HTML-escapes dynamic text, enforces maximum limits, and appends user metrics.
    """
    emoji = "👤" if is_user else "🤖"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    escaped_sender = html.escape(sender_name)
    truncated_msg = safe_truncate(message, max_chars=3000)
    escaped_message = html.escape(truncated_msg)
    
    chat_info = f"<b>Chat ID:</b> <code>{html.escape(chat_id)}</code>\n" if chat_id else ""
    metrics = await _get_active_users_metrics()
    
    text = (
        f"<b>{emoji} Chat Log</b>\n"
        f"<b>Time:</b> {timestamp}\n"
        f"<b>Sender:</b> {escaped_sender}\n"
        f"{chat_info}"
        f"<b>Message:</b>\n<blockquote>{escaped_message}</blockquote>"
        f"{metrics}"
    )
    await log_to_telegram(text)


async def log_error(error_msg: str, user_name: str = "Unknown", path: str = ""):
    """
    Formats and logs an error to Telegram.
    HTML-escapes input params to ensure valid parse syntax.
    """
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    escaped_user = html.escape(user_name)
    escaped_path = html.escape(path)
    truncated_err = safe_truncate(error_msg, max_chars=3000)
    escaped_err = html.escape(truncated_err)
    
    text = (
        f"<b>⚠️ System Error Log</b>\n"
        f"<b>Time:</b> {timestamp}\n"
        f"<b>User:</b> {escaped_user}\n"
        f"<b>Endpoint/Path:</b> {escaped_path}\n\n"
        f"<b>Error:</b>\n"
        f"<blockquote>{escaped_err}</blockquote>"
    )
    await log_to_telegram(text)


async def periodic_metrics_reporter():
    """
    Background task to post the active users count to Telegram every 10 minutes (600 seconds).
    Runs continuously during the application lifecycle.
    """
    logger.info("Starting periodic Telegram metrics reporter (runs every 10 mins)...")
    await asyncio.sleep(10)  # Wait for MongoDB initialization on startup
    while True:
        try:
            db = get_mongodb_db()
            now = datetime.utcnow()
            active_15m = await db.chats.distinct("user_id", {"updated_at": {"$gte": now - timedelta(minutes=15)}})
            active_24h = await db.chats.distinct("user_id", {"updated_at": {"$gte": now - timedelta(hours=24)}})
            total_users = await db.users.count_documents({})
            
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")
            text = (
                f"<b>⏰ Periodic System Status</b>\n"
                f"<b>Time:</b> {timestamp}\n"
                f"<b>Current Active Users (15m):</b> {len(active_15m)}\n"
                f"<b>Daily Active Users (24h):</b> {len(active_24h)}\n"
                f"<b>Total Users (All time):</b> {total_users}"
            )
            await log_to_telegram(text)
        except Exception as exc:
            logger.warning("Periodic metrics reporter failed: %s", exc)
        
        await asyncio.sleep(600)
