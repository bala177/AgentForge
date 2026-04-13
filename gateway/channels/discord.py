"""
gateway/channels/discord.py — Discord Bot channel adapter.

Handles incoming webhook events from the Discord Interactions API
and sends replies back via the Discord REST API.

Two integration modes:
  A) **Interactions Endpoint (recommended)**: Register your URL in the Discord
     Developer Portal → Interactions Endpoint URL: https://your-domain.com/webhook/discord
     Discord sends slash commands and message components as POST requests.

  B) **Bot Gateway (advanced)**: Use a WebSocket connection (discord.py library).
     This adapter handles mode A only. For mode B, use discord.py externally
     and call /api/chat to proxy messages to the agent.

Setup:
  1. Create an Application at https://discord.com/developers/applications
  2. Create a Bot under your application → copy the Bot Token
  3. Set env vars: DISCORD_BOT_TOKEN, DISCORD_PUBLIC_KEY, DISCORD_APP_ID
  4. Set Interactions Endpoint URL: https://your-domain.com/webhook/discord
  5. Register a slash command (e.g. /ask) via the Discord API:
     POST https://discord.com/api/v10/applications/{APP_ID}/commands
     {"name": "ask", "description": "Ask the AI agent", "options": [
       {"name": "question", "description": "Your question", "type": 3, "required": true}
     ]}
  6. Invite the bot to your server with the Applications.commands + Bot scopes

See: https://discord.com/developers/docs/interactions/receiving-and-responding
"""

import os
import time
import httpx
from typing import Any

try:
    from nacl.signing import VerifyKey  # pip install PyNaCl (optional)
    from nacl.exceptions import BadSignatureError
    _HAS_NACL = True
except ImportError:
    _HAS_NACL = False

from .base import ChannelAdapter, NormalizedMessage, AgentReply
from log_config import get_logger

log = get_logger("channel.discord")

# ── Config from environment ───────────────────────────────────────────
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY", "")
DISCORD_APP_ID = os.getenv("DISCORD_APP_ID", "")
DISCORD_API_URL = "https://discord.com/api/v10"

# Interaction types
INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2
INTERACTION_MESSAGE_COMPONENT = 3

# Response types
RESPONSE_PONG = 1
RESPONSE_CHANNEL_MESSAGE = 4
RESPONSE_DEFERRED = 5


class DiscordAdapter(ChannelAdapter):
    """Adapter for Discord Interactions API."""

    channel_name = "discord"

    async def parse_incoming(self, raw_data: Any) -> NormalizedMessage:
        """
        Parse a Discord Interaction payload.

        Slash command structure:
        {
          "type": 2,
          "data": {
            "name": "ask",
            "options": [{"name": "question", "value": "What's the weather?"}]
          },
          "member": {"user": {"id": "123", "username": "johndoe"}},
          "channel_id": "456",
          "guild_id": "789",
          "id": "interaction_id",
          "token": "interaction_token"
        }

        Regular message (via bot gateway proxy):
        {
          "content": "Hello bot",
          "author": {"id": "123", "username": "johndoe"},
          "channel_id": "456",
          "guild_id": "789"
        }
        """
        interaction_type = raw_data.get("type")

        # Ping verification — handled at gateway level
        if interaction_type == INTERACTION_PING:
            raise ValueError("__discord_ping__")

        # Slash command
        if interaction_type == INTERACTION_APPLICATION_COMMAND:
            data = raw_data.get("data", {})
            options = data.get("options", [])

            # Extract the question from slash command options
            text = ""
            for opt in options:
                if opt.get("name") in ("question", "message", "query", "input", "text"):
                    text = opt.get("value", "")
                    break
            if not text and options:
                text = options[0].get("value", "")
            if not text:
                text = data.get("name", "help")

            # Get user info
            member = raw_data.get("member", {})
            user = member.get("user", raw_data.get("user", {}))
            user_id = user.get("id", "unknown")
            username = user.get("username", "")
            channel_id = raw_data.get("channel_id", "")
            guild_id = raw_data.get("guild_id", "")

            return NormalizedMessage(
                text=text,
                sender_id=user_id,
                channel=self.channel_name,
                session_id=f"discord_{guild_id}_{channel_id}_{user_id}",
                metadata={
                    "channel_id": channel_id,
                    "guild_id": guild_id,
                    "username": username,
                    "interaction_id": raw_data.get("id", ""),
                    "interaction_token": raw_data.get("token", ""),
                    "command_name": data.get("name", ""),
                },
            )

        # Regular message (proxied from bot gateway)
        if raw_data.get("content"):
            author = raw_data.get("author", {})
            return NormalizedMessage(
                text=raw_data["content"],
                sender_id=author.get("id", "unknown"),
                channel=self.channel_name,
                session_id=f"discord_{raw_data.get('guild_id', '')}_{raw_data.get('channel_id', '')}_{author.get('id', '')}",
                metadata={
                    "channel_id": raw_data.get("channel_id", ""),
                    "guild_id": raw_data.get("guild_id", ""),
                    "username": author.get("username", ""),
                    "message_id": raw_data.get("id", ""),
                },
            )

        raise ValueError(f"Unsupported Discord interaction type: {interaction_type}")

    async def send_reply(self, session_id: str, reply: AgentReply) -> bool:
        """
        Send a reply back to Discord.

        For interactions: uses the interaction callback endpoint.
        For regular messages: uses the channel messages endpoint.
        """
        interaction_token = reply.metadata.get("interaction_token")
        interaction_id = reply.metadata.get("interaction_id")

        formatted = self.format_for_platform(reply)

        # Method 1: Interaction response (slash commands)
        if interaction_token and interaction_id:
            url = f"{DISCORD_API_URL}/interactions/{interaction_id}/{interaction_token}/callback"
            payload = {
                "type": RESPONSE_CHANNEL_MESSAGE,
                "data": {"content": formatted},
            }
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, json=payload, timeout=30)
                    if resp.status_code in (200, 204):
                        log.info("Discord interaction reply sent")
                        return True
                    else:
                        log.error("Discord interaction error %d: %s", resp.status_code, resp.text[:200])
                        return False
            except Exception as e:
                log.error("Discord interaction send failed: %s", e)
                return False

        # Method 2: Regular channel message
        channel_id = reply.metadata.get("channel_id")
        if channel_id and DISCORD_BOT_TOKEN:
            url = f"{DISCORD_API_URL}/channels/{channel_id}/messages"
            headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
            payload = {"content": formatted}
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, json=payload, headers=headers, timeout=30)
                    if resp.status_code in (200, 201):
                        log.info("Discord message sent to channel %s", channel_id)
                        return True
                    else:
                        log.error("Discord API error %d: %s", resp.status_code, resp.text[:200])
                        return False
            except Exception as e:
                log.error("Discord send failed: %s", e)
                return False

        log.warning("Discord not configured — skipping send")
        return False

    async def verify_request(self, raw_data: Any) -> bool:
        """
        Verify Discord request signature (Ed25519).
        See: https://discord.com/developers/docs/interactions/receiving-and-responding#security-and-authorization
        """
        if not DISCORD_PUBLIC_KEY:
            return True  # Dev mode

        if not _HAS_NACL:
            log.warning("PyNaCl not installed — skipping Discord signature verification")
            return True

        signature = raw_data.get("_signature", "")
        timestamp = raw_data.get("_timestamp", "")
        body = raw_data.get("_body", b"")

        if not signature or not timestamp:
            return True  # Missing headers

        try:
            verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
            message = timestamp.encode() + (body if isinstance(body, bytes) else body.encode())
            verify_key.verify(message, bytes.fromhex(signature))
            return True
        except BadSignatureError:
            log.warning("Discord signature verification failed")
            return False
        except Exception as e:
            log.warning("Discord verification error: %s", e)
            return True  # Fail open in dev

    def format_for_platform(self, reply: AgentReply) -> str:
        """Format reply for Discord (Markdown)."""
        text = reply.text

        # Add tool citations
        tool_steps = [s for s in reply.steps if s.get("tool")]
        if tool_steps:
            text += "\n\n> **Tools used:**"
            for s in tool_steps:
                text += f"\n> 🔧 *{s['tool']}*"

        return text[:2000]  # Discord max message length
