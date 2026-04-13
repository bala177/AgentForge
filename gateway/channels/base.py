"""
gateway/channels/base.py — Abstract base class for channel adapters.

All messaging channels (WebChat, WhatsApp, Slack, etc.) implement this
interface so the gateway can route messages uniformly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NormalizedMessage:
    """Platform-agnostic inbound message format."""
    text: str
    sender_id: str
    channel: str                          # "webchat" | "whatsapp" | "slack"
    session_id: str = ""
    attachments: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "sender_id": self.sender_id,
            "channel": self.channel,
            "session_id": self.session_id,
            "attachments": self.attachments,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AgentReply:
    """Platform-agnostic outbound reply format."""
    text: str
    steps: list[dict] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    mode: str = ""
    model: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "answer": self.text,
            "steps": self.steps,
            "plan": self.plan,
            "mode": self.mode,
            "model": self.model,
            "metadata": self.metadata,
        }


class ChannelAdapter(ABC):
    """
    Abstract base for all messaging channel adapters.

    Each adapter knows how to:
      1. Parse incoming webhook/message into NormalizedMessage
      2. Format and send an AgentReply back to the platform
      3. Verify incoming requests (signatures, tokens)
    """

    channel_name: str = "base"

    @abstractmethod
    async def parse_incoming(self, raw_data: Any) -> NormalizedMessage:
        """
        Parse a raw inbound request/message into a NormalizedMessage.
        Raises ValueError if the payload is invalid.
        """
        ...

    @abstractmethod
    async def send_reply(self, session_id: str, reply: AgentReply) -> bool:
        """
        Send an AgentReply back to the user via the platform's API.
        Returns True on success.
        """
        ...

    async def verify_request(self, raw_data: Any) -> bool:
        """
        Verify the authenticity of an incoming request (signature, token).
        Default: always True (override for Slack/WhatsApp signature checks).
        """
        return True

    def format_for_platform(self, reply: AgentReply) -> str:
        """
        Convert an AgentReply into platform-specific formatting.
        Default: plain text.  Override for Slack blocks, WhatsApp templates, etc.
        """
        return reply.text
