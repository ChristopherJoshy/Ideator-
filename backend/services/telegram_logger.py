import logging
import httpx
from datetime import datetime
from backend.config import settings

logger = logging.getLogger(__name__)

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

async def log_chat_message(sender_name: str, message: str, is_user: bool = True):
    """
    Formats and logs a user or assistant message to Telegram.
    """
    emoji = "👤" if is_user else "🤖"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    text = (
        f"<b>{emoji} Chat Log</b>\n"
        f"<b>Time:</b> {timestamp}\n"
        f"<b>Sender:</b> {sender_name}\n\n"
        f"<code>{message}</code>"
    )
    await log_to_telegram(text)

async def log_error(error_msg: str, user_name: str = "Unknown", path: str = ""):
    """
    Formats and logs an error to Telegram.
    """
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    text = (
        f"<b>⚠️ System Error Log</b>\n"
        f"<b>Time:</b> {timestamp}\n"
        f"<b>User:</b> {user_name}\n"
        f"<b>Endpoint/Path:</b> {path}\n\n"
        f"<b>Error:</b>\n"
        f"<code>{error_msg}</code>"
    )
    await log_to_telegram(text)
