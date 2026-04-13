"""
gateway/channels/teams.py — Microsoft Teams channel adapter.

Handles incoming messages from the Microsoft Bot Framework
and sends replies back via the Bot Framework REST API.

Setup:
  1. Register a bot at https://dev.botframework.com/bots/new
     or via Azure Bot Service: https://portal.azure.com → Create → Azure Bot
  2. Set env vars: TEAMS_APP_ID, TEAMS_APP_PASSWORD
  3. Set messaging endpoint: https://your-domain.com/webhook/teams
  4. Install the bot in your Teams workspace via the App Studio or Developer Portal

See: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/bot-basics
     https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-send-and-receive-messages
"""

import os
import httpx
from typing import Any

from .base import ChannelAdapter, NormalizedMessage, AgentReply
from log_config import get_logger

log = get_logger("channel.teams")

# ── Config from environment ───────────────────────────────────────────
TEAMS_APP_ID = os.getenv("TEAMS_APP_ID", "")
TEAMS_APP_PASSWORD = os.getenv("TEAMS_APP_PASSWORD", "")
TEAMS_TENANT_ID = os.getenv("TEAMS_TENANT_ID", "")
BOT_FRAMEWORK_API = "https://smba.trafficmanager.net"
OAUTH_URL = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"


class TeamsAdapter(ChannelAdapter):
    """Adapter for Microsoft Teams via Bot Framework."""

    channel_name = "teams"
    _access_token: str = ""
    _token_expiry: float = 0

    async def _get_access_token(self) -> str:
        """Get or refresh the Bot Framework access token."""
        import time
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token

        if not TEAMS_APP_ID or not TEAMS_APP_PASSWORD:
            return ""

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    OAUTH_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": TEAMS_APP_ID,
                        "client_secret": TEAMS_APP_PASSWORD,
                        "scope": "https://api.botframework.com/.default",
                    },
                    timeout=30,
                )
                data = resp.json()
                self._access_token = data.get("access_token", "")
                self._token_expiry = time.time() + data.get("expires_in", 3600) - 60
                return self._access_token
        except Exception as e:
            log.error("Teams token error: %s", e)
            return ""

    async def parse_incoming(self, raw_data: Any) -> NormalizedMessage:
        """
        Parse a Bot Framework Activity.

        Incoming structure:
        {
          "type": "message",
          "id": "activity-id",
          "text": "Hello bot!",
          "from": {"id": "user-id", "name": "John Doe"},
          "conversation": {"id": "conv-id", "tenantId": "tenant-id"},
          "channelId": "msteams",
          "serviceUrl": "https://smba.trafficmanager.net/...",
          "recipient": {"id": "bot-id", "name": "AgentBot"}
        }
        """
        activity_type = raw_data.get("type", "")

        if activity_type == "conversationUpdate":
            # Bot added to conversation — ignore
            raise ValueError("__ignore__:conversationUpdate")

        if activity_type != "message":
            raise ValueError(f"Unsupported Teams activity type: {activity_type}")

        text = raw_data.get("text", "").strip()
        if not text:
            # Check for attachments / adaptive cards
            attachments = raw_data.get("attachments", [])
            if attachments:
                text = "User sent an attachment"
            else:
                raise ValueError("Empty Teams message")

        # Remove bot mention (Teams includes "<at>BotName</at>" in group chats)
        import re
        text = re.sub(r"<at>.*?</at>\s*", "", text).strip()

        from_user = raw_data.get("from", {})
        conversation = raw_data.get("conversation", {})

        return NormalizedMessage(
            text=text,
            sender_id=from_user.get("id", "unknown"),
            channel=self.channel_name,
            session_id=f"teams_{conversation.get('id', '')}",
            metadata={
                "conversation_id": conversation.get("id", ""),
                "tenant_id": conversation.get("tenantId", ""),
                "service_url": raw_data.get("serviceUrl", ""),
                "activity_id": raw_data.get("id", ""),
                "from_name": from_user.get("name", ""),
                "recipient": raw_data.get("recipient", {}),
            },
        )

    async def send_reply(self, session_id: str, reply: AgentReply) -> bool:
        """
        Send a reply via the Bot Framework REST API.

        POST {serviceUrl}/v3/conversations/{conversationId}/activities
        """
        if not TEAMS_APP_ID or not TEAMS_APP_PASSWORD:
            log.warning("Teams not configured — skipping send")
            return False

        service_url = reply.metadata.get("service_url", BOT_FRAMEWORK_API)
        conversation_id = reply.metadata.get("conversation_id", "")
        activity_id = reply.metadata.get("activity_id", "")

        if not conversation_id:
            log.error("Missing conversation_id for Teams reply")
            return False

        token = await self._get_access_token()
        if not token:
            log.error("Cannot get Teams access token")
            return False

        formatted = self.format_for_platform(reply)

        url = f"{service_url}/v3/conversations/{conversation_id}/activities"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "type": "message",
            "text": formatted,
            "textFormat": "markdown",
        }
        if activity_id:
            payload["replyToId"] = activity_id

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code in (200, 201):
                    log.info("Teams reply sent to conversation %s", conversation_id)
                    return True
                else:
                    log.error("Teams API error %d: %s", resp.status_code, resp.text[:200])
                    return False
        except Exception as e:
            log.error("Teams send failed: %s", e)
            return False

    def format_for_platform(self, reply: AgentReply) -> str:
        """Format reply for Microsoft Teams (Markdown)."""
        text = reply.text

        tool_steps = [s for s in reply.steps if s.get("tool")]
        if tool_steps:
            text += "\n\n---\n"
            for s in tool_steps:
                text += f"\n🔧 *{s['tool']}*"

        return text[:28000]  # Teams message limit ~28KB
