"""
gateway/channels/webchat.py — WebChat channel adapter.

Handles the browser-based chat UI. Messages come in via WebSocket
or REST API and replies are sent back the same way.

This adapter is mostly a pass-through since the web UI communicates
directly with the gateway, but it normalizes the format so the
agent runtime doesn't know which channel originated the message.
"""

from .base import ChannelAdapter, NormalizedMessage, AgentReply
from log_config import get_logger

log = get_logger("channel.webchat")


class WebChatAdapter(ChannelAdapter):
    """Adapter for the browser-based WebChat UI."""

    channel_name = "webchat"

    async def parse_incoming(self, raw_data: dict) -> NormalizedMessage:
        """
        Parse a WebSocket or REST message from the browser.
        Expected format: {"message": "...", "session_id": "..."}
        """
        text = raw_data.get("message", "").strip()
        if not text:
            raise ValueError("Empty message")

        return NormalizedMessage(
            text=text,
            sender_id=raw_data.get("user_id", "webchat_user"),
            channel=self.channel_name,
            session_id=raw_data.get("session_id", ""),
            attachments=raw_data.get("attachments", []),
            metadata={"source": "browser"},
        )

    async def send_reply(self, session_id: str, reply: AgentReply) -> bool:
        """
        For WebChat, replies are returned directly via the WebSocket/HTTP
        response — this method is a no-op (the gateway handles delivery).
        """
        log.debug("WebChat reply for session %s: %s", session_id, reply.text[:100])
        return True

    def format_for_platform(self, reply: AgentReply) -> dict:
        """Return the full reply dict for the web UI (JSON)."""
        return reply.to_dict()
