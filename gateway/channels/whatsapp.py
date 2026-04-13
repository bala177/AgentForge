"""
gateway/channels/whatsapp.py — WhatsApp Business API channel adapter.

Handles incoming webhook events from the WhatsApp Cloud API (Meta)
and sends replies back via the WhatsApp Business API.

Setup:
  1. Set env vars: WHATSAPP_TOKEN, WHATSAPP_VERIFY_TOKEN, WHATSAPP_PHONE_ID
  2. Configure webhook URL in Meta Developer Console:
     https://your-domain.com/webhook/whatsapp
  3. Subscribe to "messages" webhook field

See: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks
"""

import os
import hmac
import hashlib
import httpx
from typing import Any

from .base import ChannelAdapter, NormalizedMessage, AgentReply
from log_config import get_logger

log = get_logger("channel.whatsapp")

# ── Config from environment ───────────────────────────────────────────
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "agent_verify_token")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"


class WhatsAppAdapter(ChannelAdapter):
    """Adapter for WhatsApp Business Cloud API."""

    channel_name = "whatsapp"

    async def parse_incoming(self, raw_data: Any) -> NormalizedMessage:
        """
        Parse a WhatsApp Cloud API webhook payload.

        Incoming structure (simplified):
        {
          "object": "whatsapp_business_account",
          "entry": [{
            "changes": [{
              "value": {
                "messages": [{
                  "from": "15551234567",
                  "type": "text",
                  "text": {"body": "Hello!"},
                  "timestamp": "1234567890"
                }],
                "contacts": [{"profile": {"name": "User"}}]
              }
            }]
          }]
        }
        """
        try:
            entry = raw_data.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})
            messages = value.get("messages", [])

            if not messages:
                raise ValueError("No messages in webhook payload")

            msg = messages[0]
            sender = msg.get("from", "unknown")
            msg_type = msg.get("type", "text")

            # Extract text based on message type
            if msg_type == "text":
                text = msg.get("text", {}).get("body", "")
            elif msg_type == "image":
                caption = msg.get("image", {}).get("caption", "")
                text = caption or "User sent an image"
            elif msg_type == "document":
                caption = msg.get("document", {}).get("caption", "")
                text = caption or "User sent a document"
            elif msg_type == "audio":
                text = "User sent an audio message"
            elif msg_type == "location":
                loc = msg.get("location", {})
                text = f"User shared location: {loc.get('latitude')}, {loc.get('longitude')}"
            else:
                text = f"Unsupported message type: {msg_type}"

            if not text:
                raise ValueError("Empty message text")

            # Extract sender name
            contacts = value.get("contacts", [])
            sender_name = contacts[0].get("profile", {}).get("name", "") if contacts else ""

            return NormalizedMessage(
                text=text,
                sender_id=sender,
                channel=self.channel_name,
                session_id=f"wa_{sender}",
                metadata={
                    "msg_type": msg_type,
                    "sender_name": sender_name,
                    "msg_id": msg.get("id", ""),
                },
            )

        except (KeyError, IndexError) as e:
            raise ValueError(f"Invalid WhatsApp webhook payload: {e}")

    async def send_reply(self, session_id: str, reply: AgentReply) -> bool:
        """
        Send a text reply back via WhatsApp Cloud API.

        POST https://graph.facebook.com/v18.0/{PHONE_ID}/messages
        """
        if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
            log.warning("WhatsApp not configured — skipping send")
            return False

        # Extract phone number from session_id ("wa_15551234567" → "15551234567")
        recipient = session_id.replace("wa_", "")

        formatted = self.format_for_platform(reply)

        url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": formatted},
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    log.info("WhatsApp reply sent to %s", recipient)
                    return True
                else:
                    log.error("WhatsApp API error %d: %s", resp.status_code, resp.text[:200])
                    return False
        except Exception as e:
            log.error("WhatsApp send failed: %s", e)
            return False

    async def verify_request(self, raw_data: Any) -> bool:
        """
        Verify WhatsApp webhook signature (X-Hub-Signature-256 header).
        For the verification challenge (GET), check hub.verify_token.
        """
        if not WHATSAPP_APP_SECRET:
            # If no secret configured, skip verification (dev mode)
            return True

        signature = raw_data.get("_signature", "")
        body = raw_data.get("_body", b"")

        if not signature:
            return True  # No signature = verification challenge or dev mode

        expected = "sha256=" + hmac.new(
            WHATSAPP_APP_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(signature, expected)

    def format_for_platform(self, reply: AgentReply) -> str:
        """Format reply for WhatsApp (plain text with optional tool info)."""
        text = reply.text

        # Add tool citations if any
        tool_steps = [s for s in reply.steps if s.get("tool")]
        if tool_steps:
            text += "\n\n---"
            for s in tool_steps:
                text += f"\n🔧 _{s['tool']}_"

        return text[:4096]  # WhatsApp max message length


def verify_webhook_challenge(params: dict) -> str | None:
    """
    Handle WhatsApp webhook verification (GET request).
    Returns the challenge string if token matches, else None.
    """
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        log.info("WhatsApp webhook verified")
        return challenge
    log.warning("WhatsApp webhook verification failed")
    return None
