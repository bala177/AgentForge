"""
gateway/channels/email_channel.py — Email channel adapter (SMTP / IMAP).

Receives messages via a webhook endpoint (email-to-webhook service)
and sends replies back via SMTP.

Integration approaches:
  A) **Email-to-Webhook** (recommended):  Use a service like SendGrid Inbound
     Parse, Mailgun Routes, or Postmark to forward incoming emails as
     POST webhooks to: https://your-domain.com/webhook/email

  B) **IMAP Polling** (advanced):  Poll an IMAP mailbox periodically.
     Not implemented here — can be added as a background task.

  C) **Direct SMTP test**:  Use curl/Postman to POST email-like payloads
     to /webhook/email for local testing without any email service.

Setup (SendGrid Inbound Parse):
  1. Set env vars: EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, EMAIL_FROM,
                   EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD
  2. Configure SendGrid Inbound Parse → set URL: https://your-domain.com/webhook/email
  3. Point your MX records to SendGrid

Setup (Mailgun):
  1. Set env vars as above + MAILGUN_API_KEY
  2. Create a Mailgun route: match_recipient("agent@your-domain.com")
     → forward("https://your-domain.com/webhook/email")

See: https://docs.sendgrid.com/for-developers/parsing-email/setting-up-the-inbound-parse-webhook
     https://documentation.mailgun.com/en/latest/api-routes.html
"""

import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

from .base import ChannelAdapter, NormalizedMessage, AgentReply
from log_config import get_logger

log = get_logger("channel.email")

# ── Config from environment ───────────────────────────────────────────
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_SMTP_USER = os.getenv("EMAIL_SMTP_USER", "")
EMAIL_SMTP_PASSWORD = os.getenv("EMAIL_SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "AI Agent")


class EmailAdapter(ChannelAdapter):
    """Adapter for Email via webhook (SendGrid/Mailgun/Postmark inbound parse)."""

    channel_name = "email"

    async def parse_incoming(self, raw_data: Any) -> NormalizedMessage:
        """
        Parse an inbound email webhook payload.

        SendGrid Inbound Parse format:
        {
          "from": "user@example.com",
          "to": "agent@your-domain.com",
          "subject": "Weather question",
          "text": "What's the weather in Tokyo?",
          "html": "<p>What's the weather in Tokyo?</p>",
          "sender_ip": "1.2.3.4"
        }

        Mailgun format:
        {
          "sender": "user@example.com",
          "recipient": "agent@your-domain.com",
          "subject": "Weather question",
          "body-plain": "What's the weather in Tokyo?",
          "stripped-text": "What's the weather in Tokyo?"
        }

        Generic / test format:
        {
          "from": "user@example.com",
          "subject": "Hello",
          "body": "What time is it?"
        }
        """
        # Normalize — handle multiple webhook providers
        sender = (
            raw_data.get("from")
            or raw_data.get("sender")
            or raw_data.get("email")
            or "unknown@unknown.com"
        )

        # Extract just the email address if it contains a name
        import re
        email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', sender)
        sender_email = email_match.group(0) if email_match else sender

        subject = raw_data.get("subject", "(no subject)")

        # Try multiple body fields
        body = (
            raw_data.get("stripped-text")      # Mailgun (cleaned)
            or raw_data.get("body-plain")      # Mailgun (full)
            or raw_data.get("text")            # SendGrid
            or raw_data.get("body")            # Generic
            or raw_data.get("plain")           # Postmark
            or ""
        )

        # Fall back to HTML if no plain text
        if not body:
            html = raw_data.get("html") or raw_data.get("HtmlBody") or ""
            if html:
                from bs4 import BeautifulSoup
                body = BeautifulSoup(html, "html.parser").get_text(separator=" ").strip()

        if not body:
            body = subject  # Use subject as the query if body is empty

        if not body or body == "(no subject)":
            raise ValueError("Empty email message")

        # Combine subject + body for context
        text = body if subject in body or subject == "(no subject)" else f"{subject}: {body}"

        to_addr = (
            raw_data.get("to")
            or raw_data.get("recipient")
            or ""
        )

        return NormalizedMessage(
            text=text,
            sender_id=sender_email,
            channel=self.channel_name,
            session_id=f"email_{sender_email}",
            metadata={
                "from": sender,
                "to": to_addr,
                "subject": subject,
                "sender_ip": raw_data.get("sender_ip", ""),
                "message_id": raw_data.get("Message-Id", raw_data.get("message-id", "")),
            },
        )

    async def send_reply(self, session_id: str, reply: AgentReply) -> bool:
        """
        Send a reply email via SMTP.
        """
        if not EMAIL_SMTP_USER or not EMAIL_SMTP_PASSWORD:
            log.warning("Email SMTP not configured — skipping send")
            return False

        # Extract recipient from session_id ("email_user@example.com" → "user@example.com")
        recipient = session_id.replace("email_", "", 1)
        if not recipient or "@" not in recipient:
            log.error("Invalid email recipient from session_id: %s", session_id)
            return False

        subject = f"Re: {reply.metadata.get('subject', 'AI Agent Reply')}"
        formatted = self.format_for_platform(reply)

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = f"{EMAIL_FROM_NAME} <{EMAIL_FROM or EMAIL_SMTP_USER}>"
            msg["To"] = recipient
            msg["Subject"] = subject

            # Plain text
            msg.attach(MIMEText(formatted, "plain"))

            # HTML version
            html_body = self._to_html(reply)
            msg.attach(MIMEText(html_body, "html"))

            # Send
            context = ssl.create_default_context()
            with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as server:
                server.starttls(context=context)
                server.login(EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD)
                server.send_message(msg)

            log.info("Email reply sent to %s", recipient)
            return True

        except Exception as e:
            log.error("Email send failed: %s", e)
            return False

    def format_for_platform(self, reply: AgentReply) -> str:
        """Format reply as plain text for email."""
        text = reply.text

        tool_steps = [s for s in reply.steps if s.get("tool")]
        if tool_steps:
            text += "\n\n---\nTools used:"
            for s in tool_steps:
                text += f"\n  • {s['tool']}"

        text += "\n\n--\nAI Agent Platform"
        return text

    def _to_html(self, reply: AgentReply) -> str:
        """Format reply as HTML for email."""
        import html
        body_html = html.escape(reply.text).replace("\n", "<br>")
        parts = [f"<p>{body_html}</p>"]

        tool_steps = [s for s in reply.steps if s.get("tool")]
        if tool_steps:
            parts.append("<hr><p><b>Tools used:</b></p><ul>")
            for s in tool_steps:
                parts.append(f"<li>🔧 <em>{html.escape(s['tool'])}</em></li>")
            parts.append("</ul>")

        parts.append("<p style='color:#888;font-size:12px'>— AI Agent Platform</p>")
        return "".join(parts)
