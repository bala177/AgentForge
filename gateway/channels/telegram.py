"""
gateway/channels/telegram.py — Telegram Bot API channel adapter.

Handles incoming webhook updates from the Telegram Bot API
and sends replies back via sendMessage.

Setup:
  1. Create a bot via @BotFather on Telegram → get the token
  2. Set env var: TELEGRAM_BOT_TOKEN
  3. Set webhook URL via Telegram API:
     curl https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://your-domain.com/webhook/telegram
  4. Messages will now flow to /webhook/telegram

For local development (polling mode is NOT implemented — use ngrok):
  ngrok http 5000
  curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<ngrok-id>.ngrok.io/webhook/telegram"

See: https://core.telegram.org/bots/api
"""

import os
import hashlib
import hmac
import httpx
from typing import Any

from .base import ChannelAdapter, NormalizedMessage, AgentReply
from log_config import get_logger

log = get_logger("channel.telegram")

# ── Config from environment ───────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN", "")  # optional webhook secret
TELEGRAM_API_URL = "https://api.telegram.org"


class TelegramAdapter(ChannelAdapter):
    """Adapter for Telegram Bot API (webhook mode)."""

    channel_name = "telegram"

    async def parse_incoming(self, raw_data: Any) -> NormalizedMessage:
        """
        Parse a Telegram Update object.

        Incoming structure (simplified):
        {
          "update_id": 123456789,
          "message": {
            "message_id": 42,
            "from": {"id": 12345, "first_name": "John", "username": "johndoe"},
            "chat": {"id": 12345, "type": "private"},
            "text": "Hello bot!"
          }
        }

        Also supports:
          - channel_post
          - edited_message
          - callback_query (inline button presses)
        """
        # Try message, then edited_message, then channel_post
        message = (
            raw_data.get("message")
            or raw_data.get("edited_message")
            or raw_data.get("channel_post")
        )

        # Handle callback_query (inline keyboard button press)
        callback = raw_data.get("callback_query")
        if callback and not message:
            message = callback.get("message", {})
            text = callback.get("data", "")
            sender = callback.get("from", {})
        else:
            if not message:
                raise ValueError("No message in Telegram update")
            text = message.get("text", "")
            sender = message.get("from", {})

        # Handle photo messages with caption
        if not text and message.get("photo"):
            text = message.get("caption", "User sent a photo")

        # Handle document messages
        if not text and message.get("document"):
            text = message.get("caption", "User sent a document")

        # Handle voice / audio
        if not text and (message.get("voice") or message.get("audio")):
            text = "User sent an audio message"

        # Handle location
        if not text and message.get("location"):
            loc = message["location"]
            text = f"User shared location: {loc.get('latitude')}, {loc.get('longitude')}"

        # Handle sticker
        if not text and message.get("sticker"):
            emoji = message["sticker"].get("emoji", "")
            text = f"User sent a sticker {emoji}"

        if not text:
            raise ValueError("Empty or unsupported Telegram message")

        chat_id = message.get("chat", {}).get("id", "")
        user_id = str(sender.get("id", chat_id))
        username = sender.get("username", "")
        first_name = sender.get("first_name", "")

        return NormalizedMessage(
            text=text,
            sender_id=user_id,
            channel=self.channel_name,
            session_id=f"tg_{chat_id}",
            metadata={
                "chat_id": chat_id,
                "chat_type": message.get("chat", {}).get("type", "private"),
                "message_id": message.get("message_id", ""),
                "username": username,
                "first_name": first_name,
                "update_id": raw_data.get("update_id", ""),
            },
        )

    async def send_reply(self, session_id: str, reply: AgentReply) -> bool:
        """
        Send a reply via Telegram sendMessage API.

        POST https://api.telegram.org/bot<TOKEN>/sendMessage
        """
        if not TELEGRAM_BOT_TOKEN:
            log.warning("Telegram not configured — skipping send")
            return False

        # Extract chat_id from session_id ("tg_12345" → "12345")
        chat_id = session_id.replace("tg_", "")
        if not chat_id:
            log.error("Cannot extract chat_id from session_id: %s", session_id)
            return False

        formatted = self.format_for_platform(reply)

        url = f"{TELEGRAM_API_URL}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": formatted,
            "parse_mode": "Markdown",
        }

        # Reply to specific message if available
        msg_id = reply.metadata.get("message_id")
        if msg_id:
            payload["reply_to_message_id"] = msg_id

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=30)
                data = resp.json()
                if data.get("ok"):
                    log.info("Telegram reply sent to chat %s", chat_id)
                    return True
                else:
                    log.error("Telegram API error: %s", data.get("description", "unknown"))
                    # Retry without Markdown if parse error
                    if "parse" in data.get("description", "").lower():
                        payload["parse_mode"] = None
                        payload["text"] = reply.text
                        resp2 = await client.post(url, json=payload, timeout=30)
                        return resp2.json().get("ok", False)
                    return False
        except Exception as e:
            log.error("Telegram send failed: %s", e)
            return False

    async def verify_request(self, raw_data: Any) -> bool:
        """
        Verify Telegram webhook request via secret_token header.
        See: https://core.telegram.org/bots/api#setwebhook
        """
        if not TELEGRAM_SECRET_TOKEN:
            return True  # No secret configured — skip verification

        provided = raw_data.get("_secret_token", "")
        if not provided:
            return True  # Missing header = possibly dev mode

        return hmac.compare_digest(provided, TELEGRAM_SECRET_TOKEN)

    def format_for_platform(self, reply: AgentReply) -> str:
        """Format reply for Telegram (Markdown)."""
        text = reply.text

        # Add tool citations
        tool_steps = [s for s in reply.steps if s.get("tool")]
        if tool_steps:
            text += "\n\n---"
            for s in tool_steps:
                text += f"\n🔧 _{s['tool']}_"

        return text[:4096]  # Telegram max message length
