import logging
from typing import Optional
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TelegramService:
    """Service to dispatch formatted reports and alerts to Telegram."""

    TELEGRAM_API_BASE = "https://api.telegram.org/bot"

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.bot_token = bot_token if bot_token is not None else settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id if chat_id is not None else settings.TELEGRAM_CHAT_ID

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id and "your_" not in self.bot_token)

    def _split_message(self, text: str, max_length: int = 4000) -> list[str]:
        """Splits text into chunks under Telegram's 4096 character limit."""
        if len(text) <= max_length:
            return [text]

        chunks = []
        lines = text.split("\n")
        current_chunk = []
        current_len = 0

        for line in lines:
            if current_len + len(line) + 1 > max_length:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = len(line) + 1
            else:
                current_chunk.append(line)
                current_len += len(line) + 1

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

    def send_message_sync(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Synchronously send a message to the configured Telegram chat."""
        if not self.is_configured:
            logger.warning("TelegramService: Bot token or Chat ID not configured. Message skipped.")
            return False

        url = f"{self.TELEGRAM_API_BASE}{self.bot_token}/sendMessage"
        chunks = self._split_message(text)
        success = True

        with httpx.Client(timeout=15.0) as client:
            for chunk in chunks:
                try:
                    payload = {
                        "chat_id": self.chat_id,
                        "text": chunk,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    }
                    response = client.post(url, json=payload)
                    response.raise_for_status()
                except Exception as e:
                    logger.error(f"TelegramService: Failed to send message chunk: {e}")
                    # Try plain text fallback in case markdown parsing failed
                    try:
                        payload["parse_mode"] = None
                        client.post(url, json=payload)
                    except Exception:
                        success = False

        return success

    async def send_message_async(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Asynchronously send a message to the configured Telegram chat."""
        if not self.is_configured:
            logger.warning("TelegramService: Bot token or Chat ID not configured. Message skipped.")
            return False

        url = f"{self.TELEGRAM_API_BASE}{self.bot_token}/sendMessage"
        chunks = self._split_message(text)
        success = True

        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                payload = {
                    "chat_id": self.chat_id,
                    "text": chunk,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                }
                try:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                except Exception as e:
                    logger.error(f"TelegramService: Async send error: {e}")
                    try:
                        payload["parse_mode"] = None
                        await client.post(url, json=payload)
                    except Exception:
                        success = False

        return success
