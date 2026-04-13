"""gateway.channels — Pluggable channel adapters (webchat, Slack, WhatsApp, etc.)."""
from .webchat import WebChatAdapter
from .whatsapp import WhatsAppAdapter
from .slack import SlackAdapter
from .telegram import TelegramAdapter
from .discord import DiscordAdapter
from .teams import TeamsAdapter
from .email_channel import EmailAdapter
