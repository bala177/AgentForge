"""
gateway/channels/slack.py — Slack channel adapter.

Handles incoming webhook events from the Slack Events API (Bot)
and sends replies back via Slack Web API (chat.postMessage).

Setup:
  1. Create a Slack App at https://api.slack.com/apps
  2. Set env vars: SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET
  3. Enable Event Subscriptions with URL: https://your-domain.com/webhook/slack
  4. Subscribe to bot events: message.channels, message.im, app_mention
  5. Install the app to your workspace

See: https://api.slack.com/apis/events-api
"""

import os
import hmac
import hashlib
import time
import httpx
from typing import Any

from .base import ChannelAdapter, NormalizedMessage, AgentReply
from log_config import get_logger

log = get_logger("channel.slack")

# ── Config from environment ───────────────────────────────────────────
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
SLACK_API_URL = "https://slack.com/api"


class SlackAdapter(ChannelAdapter):
    """Adapter for Slack Events API."""

    channel_name = "slack"

    async def parse_incoming(self, raw_data: Any) -> NormalizedMessage:
        """
        Parse a Slack Events API payload.

        Event callback structure:
        {
          "type": "event_callback",
          "event": {
            "type": "message",
            "user": "U12345",
            "text": "hello bot",
            "channel": "C12345",
            "ts": "1234567890.123456"
          }
        }

        URL verification challenge:
        {
          "type": "url_verification",
          "challenge": "some_challenge_string"
        }
        """
        event_type = raw_data.get("type", "")

        # URL verification — handled at gateway level, but just in case
        if event_type == "url_verification":
            raise ValueError("__url_verification__:" + raw_data.get("challenge", ""))

        if event_type != "event_callback":
            raise ValueError(f"Unexpected Slack event type: {event_type}")

        event = raw_data.get("event", {})
        msg_type = event.get("type", "")

        # Ignore bot's own messages (avoid loops)
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            raise ValueError("__ignore__:bot_message")

        if msg_type not in ("message", "app_mention"):
            raise ValueError(f"Ignoring Slack event type: {msg_type}")

        text = event.get("text", "").strip()
        user_id = event.get("user", "unknown")
        channel_id = event.get("channel", "")

        if not text:
            raise ValueError("Empty Slack message")

        # Remove bot mention prefix if present (e.g., "<@U12345> hello" → "hello")
        import re
        text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

        return NormalizedMessage(
            text=text,
            sender_id=user_id,
            channel=self.channel_name,
            session_id=f"slack_{channel_id}_{user_id}",
            metadata={
                "channel_id": channel_id,
                "thread_ts": event.get("thread_ts", event.get("ts", "")),
                "ts": event.get("ts", ""),
                "team_id": raw_data.get("team_id", ""),
            },
        )

    async def send_reply(self, session_id: str, reply: AgentReply) -> bool:
        """
        Send a reply to a Slack channel via chat.postMessage.
        """
        if not SLACK_BOT_TOKEN:
            log.warning("Slack not configured — skipping send")
            return False

        # Extract channel_id from session_id ("slack_C12345_U67890" → "C12345")
        parts = session_id.split("_")
        channel_id = parts[1] if len(parts) >= 2 else ""
        if not channel_id:
            log.error("Cannot extract channel_id from session_id: %s", session_id)
            return False

        formatted = self.format_for_platform(reply)

        url = f"{SLACK_API_URL}/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "channel": channel_id,
            "text": reply.text,  # fallback text
            "blocks": formatted,
        }

        # If there's a thread_ts in the metadata, reply in thread
        thread_ts = reply.metadata.get("thread_ts", "")
        if thread_ts:
            payload["thread_ts"] = thread_ts

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers, timeout=30)
                data = resp.json()
                if data.get("ok"):
                    log.info("Slack reply sent to channel %s", channel_id)
                    return True
                else:
                    log.error("Slack API error: %s", data.get("error", "unknown"))
                    return False
        except Exception as e:
            log.error("Slack send failed: %s", e)
            return False

    async def verify_request(self, raw_data: Any) -> bool:
        """
        Verify Slack request signature (X-Slack-Signature header).
        See: https://api.slack.com/authentication/verifying-requests-from-slack
        """
        if not SLACK_SIGNING_SECRET:
            return True  # Dev mode — skip verification

        timestamp = raw_data.get("_timestamp", "")
        signature = raw_data.get("_signature", "")
        body = raw_data.get("_body", b"")

        if not timestamp or not signature:
            return True  # Missing headers = possibly dev mode

        # Reject requests older than 5 minutes
        try:
            if abs(time.time() - int(timestamp)) > 300:
                log.warning("Slack request too old (timestamp: %s)", timestamp)
                return False
        except ValueError:
            return False

        # Compute expected signature
        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8') if isinstance(body, bytes) else body}"
        expected = "v0=" + hmac.new(
            SLACK_SIGNING_SECRET.encode(),
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(signature, expected)

    def format_for_platform(self, reply: AgentReply) -> list[dict]:
        """
        Format reply as Slack Block Kit blocks.
        Returns a list of block dicts for rich formatting.
        """
        blocks = []

        # Main answer as a section block
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": reply.text[:3000],
            },
        })

        # Tool citations as context blocks
        tool_steps = [s for s in reply.steps if s.get("tool")]
        if tool_steps:
            blocks.append({"type": "divider"})
            tool_elements = []
            for s in tool_steps:
                tool_elements.append({
                    "type": "mrkdwn",
                    "text": f":wrench: *{s['tool']}* — {(s.get('result', '')[:100])}",
                })
            blocks.append({
                "type": "context",
                "elements": tool_elements[:10],  # Slack limits to 10 elements
            })

        # Stats footer
        mode_label = "LLM" if reply.mode == "llm" else "Keyword"
        stats_text = f":gear: {mode_label}"
        if reply.model:
            stats_text += f" | :robot_face: {reply.model}"
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": stats_text}],
        })

        return blocks
