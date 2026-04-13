"""
gateway/server.py — FastAPI web server for the AI Agent.

Provides:
  • REST API (all existing endpoints preserved)
  • WebSocket chat endpoint (/ws/chat/{session_id})
  • WebSocket log streaming (replaces SSE)
  • Channel webhook routing (/webhook/{channel})
  • Tool gallery, memory viewer, LLM config
  • Static file & template serving
"""

import os
import time
import json as _json
import asyncio
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List


# ── Pydantic request models (enables Swagger body documentation) ──────
class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


class ToolRequest(BaseModel):
    tool: str
    input: str = ""


class LLMConfigRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    ollama_url: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None


class NoteCreateRequest(BaseModel):
    text: str
    category: str = "general"
    tags: List[str] = []
    color: str = "default"
    source: str = "manual"


class NoteUpdateRequest(BaseModel):
    text: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    color: Optional[str] = None
    pinned: Optional[bool] = None


class PinRequest(BaseModel):
    pinned: bool = True


class FactRequest(BaseModel):
    key: str
    value: str
    source: str = "user"

from runtime.agent import AgentForge
from runtime.tools import TOOL_REGISTRY
from llm.provider import LLMProvider, LLMConfig
import runtime.activity_store as activity_store
from gateway.session import SessionManager, Session
from gateway.channels.webchat import WebChatAdapter
from gateway.channels.whatsapp import WhatsAppAdapter, verify_webhook_challenge
from gateway.channels.slack import SlackAdapter
from gateway.channels.telegram import TelegramAdapter
from gateway.channels.discord import DiscordAdapter
from gateway.channels.teams import TeamsAdapter
from gateway.channels.email_channel import EmailAdapter
from gateway.channels.base import AgentReply, NormalizedMessage
from log_config import get_logger, ring_handler

log = get_logger("gateway")

# ── App setup ─────────────────────────────────────────────────────────
app = FastAPI(title="AgentForge", version="2.0.0")

# Template & static dirs
_GATEWAY_DIR = Path(__file__).parent
_TEMPLATES_DIR = _GATEWAY_DIR / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Core components
agent = AgentForge(name="WebAgent")
session_manager = SessionManager(ttl=1800)  # 30 min
webchat_adapter = WebChatAdapter()
whatsapp_adapter = WhatsAppAdapter()
slack_adapter = SlackAdapter()
telegram_adapter = TelegramAdapter()
discord_adapter = DiscordAdapter()
teams_adapter = TeamsAdapter()
email_adapter = EmailAdapter()

# Channel adapter registry
_channel_adapters = {
    "webchat": webchat_adapter,
    "whatsapp": whatsapp_adapter,
    "slack": slack_adapter,
    "telegram": telegram_adapter,
    "discord": discord_adapter,
    "teams": teams_adapter,
    "email": email_adapter,
}

# Connected WebSocket clients for broadcasting
_ws_chat_clients: dict[str, WebSocket] = {}  # session_id → ws
_ws_log_clients: list[WebSocket] = []
_start_time = time.time()  # for /status uptime

log.info("FastAPI gateway created, agent initialised")


# ── Startup / shutdown ────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    session_manager.start_cleanup()
    # Start log broadcast loop
    asyncio.create_task(_broadcast_logs_loop())
    log.info("Gateway started — WebSocket + REST ready")


@app.on_event("shutdown")
async def on_shutdown():
    session_manager.stop_cleanup()
    log.info("Gateway shutting down")


# ── Tool metadata for the UI (icons, colors, example inputs) ─────────
TOOL_META = {
    "calculator": {
        "icon": "🧮", "color": "#6366f1",
        "example": "factorial(10) / sqrt(144)",
        "category": "Math",
    },
    "get_datetime": {
        "icon": "🕐", "color": "#0891b2",
        "example": "+5:30",
        "category": "Utility",
    },
    "weather_lookup": {
        "icon": "🌦️", "color": "#f59e0b",
        "example": "Tokyo",
        "category": "Web API",
    },
    "web_search": {
        "icon": "🔍", "color": "#10b981",
        "example": "Python programming tutorials",
        "category": "Web API",
    },
    "wikipedia_lookup": {
        "icon": "📚", "color": "#8b5cf6",
        "example": "Alan Turing",
        "category": "Web API",
    },
    "url_fetcher": {
        "icon": "🌐", "color": "#ec4899",
        "example": "https://httpbin.org/json",
        "category": "Web API",
    },
    "unit_converter": {
        "icon": "⚖️", "color": "#14b8a6",
        "example": "100 km to miles",
        "category": "Math",
    },
    "file_manager": {
        "icon": "📁", "color": "#f97316",
        "example": "list .",
        "category": "System",
    },
    "system_info": {
        "icon": "💻", "color": "#64748b",
        "example": "",
        "category": "System",
    },
    "text_analyzer": {
        "icon": "📝", "color": "#a855f7",
        "example": "The quick brown fox jumps over the lazy dog near the river bank",
        "category": "Text",
    },
    "hash_encode": {
        "icon": "🔐", "color": "#ef4444",
        "example": "sha256 hello world",
        "category": "Crypto",
    },
    "ip_lookup": {
        "icon": "🌍", "color": "#3b82f6",
        "example": "",
        "category": "Web API",
    },
    "note_taker": {
        "icon": "📌", "color": "#eab308",
        "example": "save Remember to review the agent code",
        "category": "Utility",
    },
    "document_ocr": {
        "icon": "📷", "color": "#0ea5e9",
        "example": "status",
        "category": "AI",
    },
    "json_yaml_tool": {
        "icon": "📋", "color": "#7c3aed",
        "example": 'format {"name":"test","value":42}',
        "category": "Data",
    },
    "csv_data_tool": {
        "icon": "📊", "color": "#059669",
        "example": "parse name,age\\nAlice,30\\nBob,25",
        "category": "Data",
    },
    "pdf_reader": {
        "icon": "📄", "color": "#dc2626",
        "example": "read document.pdf",
        "category": "Document",
    },
    "code_runner": {
        "icon": "▶️", "color": "#2563eb",
        "example": "print('Hello, World!')",
        "category": "Code",
    },
    "process_manager": {
        "icon": "⚙️", "color": "#475569",
        "example": "top",
        "category": "System",
    },
    "network_diag": {
        "icon": "🌐", "color": "#0284c7",
        "example": "ping google.com",
        "category": "Network",
    },
    "password_gen": {
        "icon": "🔑", "color": "#b91c1c",
        "example": "generate 20",
        "category": "Security",
    },
    "regex_tool": {
        "icon": "🔤", "color": "#9333ea",
        "example": "test \\d+ abc123xyz",
        "category": "Text",
    },
    "archive_tool": {
        "icon": "🗜️", "color": "#ca8a04",
        "example": "list archive.zip",
        "category": "File",
    },
    "currency_convert": {
        "icon": "💱", "color": "#16a34a",
        "example": "100 USD to EUR",
        "category": "Finance",
    },
    "schedule_tool": {
        "icon": "⏰", "color": "#d97706",
        "example": "list",
        "category": "Utility",
    },
}


# =====================================================================
#  HTML / Dashboard
# =====================================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main dashboard page with tool cards."""
    log.info("GET / — serving index page")
    tools_info = []
    for name, info in TOOL_REGISTRY.items():
        meta = TOOL_META.get(name, {"icon": "🔧", "color": "#64748b", "example": "", "category": "Other"})
        tools_info.append({
            "name": name,
            "description": info["description"],
            "icon": meta["icon"],
            "color": meta["color"],
            "example": meta["example"],
            "category": meta["category"],
        })
    log.debug("Loaded %d tools for index page", len(tools_info))
    return templates.TemplateResponse("index.html", {"request": request, "tools": tools_info})


# =====================================================================
#  REST API — Tools
# =====================================================================

@app.post("/api/tool")
async def run_tool(body: ToolRequest):
    """Run a single tool directly and return its output."""
    tool_name = body.tool
    tool_input = body.input
    log.info("POST /api/tool — tool=%s  input=%s", tool_name, tool_input[:120])

    if tool_name not in TOOL_REGISTRY:
        log.warning("Unknown tool requested: %s", tool_name)
        return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=400)

    try:
        t0 = time.perf_counter()
        result = TOOL_REGISTRY[tool_name]["function"](tool_input)
        elapsed = (time.perf_counter() - t0) * 1000
        log.info("Tool %s completed in %.1f ms  result_len=%d", tool_name, elapsed, len(result))
        activity_store.log_activity(
            act_type="tool", tool=tool_name,
            input_text=tool_input, output_text=result,
            success=True, duration_ms=elapsed,
        )
        return {"tool": tool_name, "input": tool_input, "result": result}
    except Exception as e:
        log.exception("Tool %s raised an exception", tool_name)
        activity_store.log_activity(
            act_type="tool", tool=tool_name,
            input_text=tool_input, output_text=str(e),
            success=False,
        )
        return JSONResponse({"error": str(e)}, status_code=500)


# =====================================================================
#  Slash Commands — pre-processed before reaching the agent
# =====================================================================

def _handle_slash_command(text: str, session_id: str) -> dict | None:
    """
    Handle /commands before they reach the agent.
    Returns a response dict if command was handled, None otherwise.
    """
    text = text.strip()
    if not text.startswith("/"):
        return None

    parts = text.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/new", "/clear", "/reset"):
        session = session_manager.get_session(session_id)
        if session:
            session.clear_history()
            agent.memory_store.clear_conversation(session_id)
        return {
            "answer": "Session cleared. Starting fresh.",
            "steps": [], "mode": "command", "command": cmd,
        }

    if cmd == "/help":
        help_text = (
            "**Available Commands:**\n"
            "| Command | Description |\n"
            "|---|---|\n"
            "| `/new` or `/clear` | Clear session, start fresh |\n"
            "| `/help` | Show this help |\n"
            "| `/tools` | List all available tools |\n"
            "| `/model [name]` | Show or switch active LLM model |\n"
            "| `/status` | Show agent status (model, session, tools, uptime) |\n"
            "| `/memory` | Show stored facts for this session |\n"
            "| `/compact` | Summarize long conversation into compact context |\n"
        )
        return {
            "answer": help_text,
            "steps": [], "mode": "command", "command": "/help",
        }

    if cmd == "/tools":
        lines = ["**Available Tools ({count}):**\n".format(count=len(TOOL_REGISTRY))]
        for name, info in TOOL_REGISTRY.items():
            meta = TOOL_META.get(name, {"icon": "🔧", "category": "Other"})
            lines.append(f"- {meta.get('icon', '🔧')} **{name}** [{meta.get('category', 'Other')}] — {info['description'][:80]}")
        return {
            "answer": "\n".join(lines),
            "steps": [], "mode": "command", "command": "/tools",
        }

    if cmd == "/model":
        if arg:
            old_model = agent.llm_config.model
            agent.llm_config.model = arg
            agent.llm = LLMProvider(agent.llm_config)
            return {
                "answer": f"Model switched: **{old_model}** → **{arg}**",
                "steps": [], "mode": "command", "command": "/model",
            }
        else:
            return {
                "answer": (
                    f"**Current model:** {agent.llm_config.model}\n"
                    f"**Provider:** {agent.llm_config.provider}\n"
                    f"**Temperature:** {agent.llm_config.temperature}\n"
                    f"**Max tokens:** {agent.llm_config.max_tokens}\n\n"
                    f"Use `/model <name>` to switch (e.g. `/model mistral:latest`)"
                ),
                "steps": [], "mode": "command", "command": "/model",
            }

    if cmd == "/status":
        import platform as _plat
        session = session_manager.get_session(session_id)
        msg_count = len(session.history) if session else 0
        uptime = time.time() - _start_time
        h, rem = divmod(int(uptime), 3600)
        m, s = divmod(rem, 60)
        return {
            "answer": (
                f"**Agent Status**\n"
                f"- **Model:** {agent.llm_config.model} ({agent.llm_config.provider})\n"
                f"- **Max steps:** {agent.max_steps}\n"
                f"- **Tools:** {len(TOOL_REGISTRY)}\n"
                f"- **Session:** {session_id} ({msg_count} messages)\n"
                f"- **Active sessions:** {session_manager.count}\n"
                f"- **Uptime:** {h}h {m}m {s}s\n"
                f"- **Platform:** {_plat.system()} {_plat.release()}\n"
                f"- **Python:** {_plat.python_version()}"
            ),
            "steps": [], "mode": "command", "command": "/status",
        }

    if cmd == "/memory":
        facts = agent.memory_store.all_facts_as_context(limit=50)
        if facts:
            return {
                "answer": f"**Stored Facts:**\n\n{facts}",
                "steps": [], "mode": "command", "command": "/memory",
            }
        else:
            return {
                "answer": "No facts stored yet. The agent learns facts as you chat.",
                "steps": [], "mode": "command", "command": "/memory",
            }

    if cmd == "/compact":
        if not agent.use_llm:
            return {
                "answer": "⚠️ Compaction requires an LLM. Currently in keyword mode.",
                "steps": [], "mode": "command", "command": "/compact",
            }
        msg_count = agent.memory_store.count_messages(session_id)
        if msg_count < 5:
            return {
                "answer": "Session is already compact (fewer than 5 messages).",
                "steps": [], "mode": "command", "command": "/compact",
            }
        summary = agent.consolidate_session(session_id)
        return {
            "answer": (
                f"✅ **Session compacted** ({msg_count} messages → 5 kept)\n\n"
                f"**Summary written to MEMORY.md:**\n\n{summary}"
            ),
            "steps": [], "mode": "command", "command": "/compact",
        }

    # Unknown slash command
    return {
        "answer": f"Unknown command: `{cmd}`. Type `/help` for available commands.",
        "steps": [], "mode": "command", "command": cmd,
    }


# =====================================================================
#  REST API — Chat (HTTP fallback, also used by non-WS clients)
# =====================================================================

@app.post("/api/chat")
async def chat(body: ChatRequest):
    """Run the full agent loop on a user message (REST endpoint)."""
    user_input = body.message.strip()
    session_id = body.session_id
    log.info("POST /api/chat — message=%s", user_input[:200])

    if not user_input:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    # Get or create session
    session = session_manager.get_or_create(
        session_id=session_id, channel="webchat"
    )

    # Slash command interception
    slash_result = _handle_slash_command(user_input, session.session_id)
    if slash_result is not None:
        slash_result["session_id"] = session.session_id
        log.info("Slash command handled: %s", slash_result.get("command", "?"))
        return slash_result

    session.add_message("user", user_input)

    try:
        t0 = time.perf_counter()
        result = agent.run(user_input, session_id=session.session_id)
        elapsed = (time.perf_counter() - t0) * 1000
        log.info("Chat completed in %.1f ms  mode=%s  steps=%d",
                 elapsed, result.get("mode"), len(result.get("steps", [])))

        # Store in session
        session.add_message("assistant", result.get("answer", ""))

        # Log activity
        tools_used = ", ".join(
            s.get("tool", "") for s in result.get("steps", [])
            if s.get("tool") and s["tool"] != "none"
        )
        activity_store.log_activity(
            act_type="chat", tool=tools_used,
            input_text=user_input, output_text=result.get("answer", ""),
            success=True, duration_ms=elapsed,
            mode=result.get("mode", ""), model=result.get("model", ""),
            steps=len(result.get("steps", [])),
            session_id=session.session_id,
        )

        # Add session info to response
        result["session_id"] = session.session_id
        return result
    except Exception as e:
        log.exception("Chat handler raised an exception")
        activity_store.log_activity(
            act_type="chat", input_text=user_input,
            output_text=str(e), success=False,
        )
        return JSONResponse({"error": str(e)}, status_code=500)


# =====================================================================
#  WebSocket — Real-time Chat
# =====================================================================

@app.websocket("/ws/chat/{session_id}")
async def ws_chat(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time bidirectional chat.

    Client sends:  {"message": "...", "user_id": "..."}
    Server sends:  {"answer": "...", "steps": [...], "mode": "...", ...}
    """
    await websocket.accept()
    session = session_manager.get_or_create(
        session_id=session_id, channel="webchat"
    )
    _ws_chat_clients[session_id] = websocket
    log.info("WebSocket chat connected: session=%s", session_id)

    try:
        while True:
            data = await websocket.receive_json()
            user_input = data.get("message", "").strip()

            if not user_input:
                await websocket.send_json({"error": "Empty message"})
                continue

            session.add_message("user", user_input)

            # Slash command interception
            slash_result = _handle_slash_command(user_input, session.session_id)
            if slash_result is not None:
                slash_result["session_id"] = session.session_id
                slash_result["type"] = "reply"
                log.info("WS slash command handled: %s", slash_result.get("command", "?"))
                await websocket.send_json(slash_result)
                continue

            # Stream agent events via asyncio.Queue bridge (sync generator → async WS)
            t0 = time.perf_counter()
            loop = asyncio.get_running_loop()
            stream_queue: asyncio.Queue = asyncio.Queue()

            def _stream_thread():
                try:
                    for event in agent.run_streaming(user_input, session.session_id):
                        asyncio.run_coroutine_threadsafe(
                            stream_queue.put(event), loop
                        )
                except Exception as exc:
                    asyncio.run_coroutine_threadsafe(
                        stream_queue.put({"type": "error", "error": str(exc)}), loop
                    )
                finally:
                    asyncio.run_coroutine_threadsafe(
                        stream_queue.put(None), loop  # sentinel
                    )

            threading.Thread(target=_stream_thread, daemon=True).start()

            full_result: dict = {}
            while True:
                event = await stream_queue.get()
                if event is None:
                    break
                event["session_id"] = session.session_id
                if event.get("type") == "done":
                    full_result = event
                try:
                    await websocket.send_json(event)
                except Exception:
                    break

            elapsed = (time.perf_counter() - t0) * 1000
            full_answer = full_result.get("answer", "")
            session.add_message("assistant", full_answer)

            # Log activity
            tools_used = ", ".join(
                s.get("tool", "") for s in full_result.get("steps", [])
                if s.get("tool") and s["tool"] != "none"
            )
            activity_store.log_activity(
                act_type="chat", tool=tools_used,
                input_text=user_input, output_text=full_answer,
                success=True, duration_ms=elapsed,
                mode=full_result.get("mode", ""), model=full_result.get("model", ""),
                steps=len(full_result.get("steps", [])),
                session_id=session.session_id,
            )

    except WebSocketDisconnect:
        log.info("WebSocket chat disconnected: session=%s", session_id)
    except Exception as e:
        log.exception("WebSocket chat error: session=%s", session_id)
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
    finally:
        _ws_chat_clients.pop(session_id, None)


# =====================================================================
#  WebSocket — Live Log Streaming (replaces SSE)
# =====================================================================

@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    """WebSocket endpoint for live log streaming to the UI."""
    await websocket.accept()
    _ws_log_clients.append(websocket)
    log.info("WebSocket log client connected (total: %d)", len(_ws_log_clients))

    try:
        # Send recent logs on connect
        recent = ring_handler.get_since(-1)
        for entry in recent[-100:]:
            await websocket.send_json(entry)

        # Keep alive — wait for disconnect
        while True:
            await websocket.receive_text()  # ping/pong keepalive
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if websocket in _ws_log_clients:
            _ws_log_clients.remove(websocket)
        log.info("WebSocket log client disconnected (remaining: %d)", len(_ws_log_clients))


async def _broadcast_logs_loop():
    """Background task: broadcast new log entries to all connected WS clients."""
    last_seq = -1
    while True:
        await asyncio.sleep(0.4)
        entries = ring_handler.get_since(last_seq)
        if not entries:
            continue
        last_seq = entries[-1]["seq"]
        # Broadcast to all log clients
        disconnected = []
        for ws in _ws_log_clients:
            try:
                for entry in entries:
                    await ws.send_json(entry)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            if ws in _ws_log_clients:
                _ws_log_clients.remove(ws)


# ── SSE fallback (for compatibility) ─────────────────────────────────

@app.get("/api/logs/stream")
async def log_stream_sse():
    """Server-Sent Events endpoint (kept for backward compatibility)."""
    log.info("SSE /api/logs/stream — client connected")

    async def generate():
        last_seq = -1
        while True:
            entries = ring_handler.get_since(last_seq)
            for entry in entries:
                last_seq = entry["seq"]
                data = _json.dumps(entry)
                yield f"data: {data}\n\n"
            await asyncio.sleep(0.4)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/logs/recent")
async def log_recent(n: int = 100):
    """Return the last N log entries as JSON."""
    entries = ring_handler.get_since(-1)
    return entries[-n:]


# =====================================================================
#  REST API — Memory
# =====================================================================

@app.get("/api/memory")
async def memory():
    """Return the agent's memory."""
    return {"memory": agent.memory, "count": len(agent.memory)}


@app.post("/api/memory/clear")
async def clear_memory():
    """Clear the agent's memory."""
    agent.memory.clear()
    return {"status": "ok", "message": "Memory cleared"}


# =====================================================================
#  REST API — Tools listing
# =====================================================================

@app.get("/api/tools")
async def list_tools():
    """Return tool metadata as JSON."""
    tools = {}
    for name, info in TOOL_REGISTRY.items():
        meta = TOOL_META.get(name, {})
        tools[name] = {
            "description": info["description"],
            "icon": meta.get("icon", "🔧"),
            "example": meta.get("example", ""),
            "category": meta.get("category", "Other"),
        }
    return tools


# =====================================================================
#  REST API — Channel Configuration
# =====================================================================

CHANNEL_SETUP = {
    "telegram": {
        "display": "Telegram", "emoji": "✈️",
        "webhook_path": "/webhook/telegram",
        "docs_url": "https://core.telegram.org/bots/api",
        "vars": [
            {"key": "TELEGRAM_BOT_TOKEN", "label": "Bot Token", "hint": "From @BotFather on Telegram", "secret": True, "required": True},
            {"key": "TELEGRAM_SECRET_TOKEN", "label": "Webhook Secret", "hint": "Optional — any random string for security", "secret": True, "required": False},
        ],
        "setup_steps": [
            "Open Telegram → search @BotFather → send /newbot",
            "Follow prompts and copy the Bot Token",
            "Expose this server publicly (e.g. ngrok http 5000)",
            "Register webhook: curl 'https://api.telegram.org/bot{TOKEN}/setWebhook?url=https://YOUR-DOMAIN/webhook/telegram'",
            "Send a message to your bot — it routes through this agent!",
        ],
    },
    "whatsapp": {
        "display": "WhatsApp", "emoji": "📱",
        "webhook_path": "/webhook/whatsapp",
        "docs_url": "https://developers.facebook.com/docs/whatsapp/cloud-api",
        "vars": [
            {"key": "WHATSAPP_TOKEN", "label": "Access Token", "hint": "Meta Cloud API permanent token", "secret": True, "required": True},
            {"key": "WHATSAPP_VERIFY_TOKEN", "label": "Verify Token", "hint": "Any string you choose (for webhook verification)", "secret": False, "required": True},
            {"key": "WHATSAPP_PHONE_ID", "label": "Phone Number ID", "hint": "Meta Developer Console → WhatsApp → API Setup", "secret": False, "required": True},
            {"key": "WHATSAPP_APP_SECRET", "label": "App Secret", "hint": "Meta App → Settings → Basic (optional, for signature verification)", "secret": True, "required": False},
        ],
        "setup_steps": [
            "Go to developers.facebook.com → Create App → Business",
            "Add WhatsApp product → copy Phone Number ID and Access Token",
            "Set Webhook URL in Meta Console: https://YOUR-DOMAIN/webhook/whatsapp",
            "Set Verify Token to match your WHATSAPP_VERIFY_TOKEN value",
            "Subscribe to the 'messages' webhook field",
        ],
    },
    "slack": {
        "display": "Slack", "emoji": "💬",
        "webhook_path": "/webhook/slack",
        "docs_url": "https://api.slack.com/apis/events-api",
        "vars": [
            {"key": "SLACK_BOT_TOKEN", "label": "Bot Token", "hint": "xoxb-... from OAuth & Permissions page", "secret": True, "required": True},
            {"key": "SLACK_SIGNING_SECRET", "label": "Signing Secret", "hint": "From Basic Information page", "secret": True, "required": True},
        ],
        "setup_steps": [
            "api.slack.com/apps → Create New App → From Scratch",
            "OAuth & Permissions → add chat:write, channels:read → Install to workspace",
            "Copy Bot Token (xoxb-...)",
            "Basic Information → copy Signing Secret",
            "Event Subscriptions → enable → URL: https://YOUR-DOMAIN/webhook/slack",
            "Subscribe to: message.channels, message.im, app_mention",
        ],
    },
    "discord": {
        "display": "Discord", "emoji": "🎮",
        "webhook_path": "/webhook/discord",
        "docs_url": "https://discord.com/developers/docs/interactions/receiving-and-responding",
        "vars": [
            {"key": "DISCORD_PUBLIC_KEY", "label": "Public Key", "hint": "Developer Portal → App → General Information", "secret": True, "required": True},
            {"key": "DISCORD_BOT_TOKEN", "label": "Bot Token", "hint": "Developer Portal → Bot page → Reset Token", "secret": True, "required": True},
            {"key": "DISCORD_APP_ID", "label": "Application ID", "hint": "General Information page", "secret": False, "required": True},
        ],
        "setup_steps": [
            "discord.com/developers/applications → New Application",
            "Bot tab → Reset Token → copy Bot Token",
            "General Information → copy Application ID and Public Key",
            "Interactions Endpoint URL: https://YOUR-DOMAIN/webhook/discord",
            "Register /ask slash command via Discord API",
            "OAuth2 → invite bot with applications.commands + bot scopes",
        ],
    },
    "teams": {
        "display": "MS Teams", "emoji": "🏢",
        "webhook_path": "/webhook/teams",
        "docs_url": "https://learn.microsoft.com/en-us/microsoftteams/platform/bots/bot-basics",
        "vars": [
            {"key": "TEAMS_APP_ID", "label": "App ID", "hint": "Azure Bot Service → Configuration", "secret": False, "required": True},
            {"key": "TEAMS_APP_PASSWORD", "label": "App Password", "hint": "Azure App Registration → Certificates & Secrets", "secret": True, "required": True},
            {"key": "TEAMS_TENANT_ID", "label": "Tenant ID", "hint": "Your Azure AD tenant ID (optional)", "secret": False, "required": False},
        ],
        "setup_steps": [
            "portal.azure.com → Create → Azure Bot",
            "Set Messaging Endpoint: https://YOUR-DOMAIN/webhook/teams",
            "App Registration → Certificates & Secrets → create client secret",
            "Copy App ID and App Password (client secret)",
            "Install the bot to your Teams workspace via Developer Portal",
        ],
    },
    "email": {
        "display": "Email", "emoji": "📧",
        "webhook_path": "/webhook/email",
        "docs_url": "https://docs.sendgrid.com/for-developers/parsing-email/setting-up-the-inbound-parse-webhook",
        "vars": [
            {"key": "EMAIL_SMTP_HOST", "label": "SMTP Host", "hint": "e.g. smtp.gmail.com", "secret": False, "required": True},
            {"key": "EMAIL_SMTP_PORT", "label": "SMTP Port", "hint": "587 (TLS) or 465 (SSL)", "secret": False, "required": False},
            {"key": "EMAIL_SMTP_USER", "label": "SMTP User", "hint": "Your email address", "secret": False, "required": True},
            {"key": "EMAIL_SMTP_PASSWORD", "label": "SMTP Password", "hint": "App password — NOT your account password", "secret": True, "required": True},
            {"key": "EMAIL_FROM", "label": "From Address", "hint": "Reply-from email (optional, defaults to SMTP_USER)", "secret": False, "required": False},
        ],
        "setup_steps": [
            "Use SendGrid / Mailgun / Postmark for inbound email → webhook forwarding",
            "Set inbound parse URL: https://YOUR-DOMAIN/webhook/email",
            "For Gmail SMTP replies: myaccount.google.com → Security → App passwords",
            "Test locally: POST /webhook/email with {\"from\":\"you@test.com\",\"body\":\"hello\"}",
        ],
    },
}


def _reload_channel_env(channel: str):
    """After config update, re-apply os.environ values to module-level vars."""
    module_map = {
        "telegram": "gateway.channels.telegram",
        "whatsapp": "gateway.channels.whatsapp",
        "slack": "gateway.channels.slack",
        "discord": "gateway.channels.discord",
        "teams": "gateway.channels.teams",
        "email": "gateway.channels.email_channel",
    }
    import sys
    mod_name = module_map.get(channel)
    if mod_name:
        mod = sys.modules.get(mod_name)
        if mod:
            for attr in dir(mod):
                if attr.isupper() and "_" in attr:
                    env_val = os.environ.get(attr)
                    if env_val is not None:
                        setattr(mod, attr, env_val)


@app.get("/api/channels")
async def get_channels_config():
    """Return configuration status and setup info for all channel adapters."""
    host = os.environ.get("APP_HOST", "localhost")
    port = os.environ.get("APP_PORT", "5000")
    base = f"http://{host}:{port}"
    result = {}
    for name, cfg in CHANNEL_SETUP.items():
        vars_info = []
        all_required_set = True
        for v in cfg["vars"]:
            val = os.environ.get(v["key"], "")
            configured = bool(val)
            if v.get("required", True) and not configured:
                all_required_set = False
            vars_info.append({
                "key": v["key"],
                "label": v["label"],
                "hint": v["hint"],
                "secret": v["secret"],
                "required": v.get("required", True),
                "configured": configured,
                "value": ("*" * min(len(val), 8) if val and v["secret"] else val),
            })
        result[name] = {
            "display": cfg["display"],
            "emoji": cfg["emoji"],
            "configured": all_required_set,
            "webhook_url": base + cfg["webhook_path"],
            "webhook_path": cfg["webhook_path"],
            "docs_url": cfg["docs_url"],
            "vars": vars_info,
            "setup_steps": cfg["setup_steps"],
        }
    return result


@app.post("/api/channels/{channel}")
async def set_channel_config(channel: str, request: Request):
    """Set environment variables for a channel adapter at runtime."""
    if channel not in CHANNEL_SETUP:
        return JSONResponse(
            {"error": f"Unknown channel: {channel}. Valid: {list(CHANNEL_SETUP.keys())}"},
            status_code=404,
        )
    data = await request.json()
    updated = []
    for key, value in data.items():
        if isinstance(value, str) and value.strip():
            os.environ[key] = value.strip()
            updated.append(key)
            log.info("Channel %s: configured %s", channel, key)
    _reload_channel_env(channel)
    log.info("Channel %s config updated: %s", channel, updated)
    return {"status": "ok", "channel": channel, "updated": updated}


# =====================================================================
#  REST API — LLM Configuration
# =====================================================================

@app.get("/api/llm/status")
async def llm_status():
    """Check LLM provider status and availability."""
    available, message = agent.llm.is_available()
    return {
        "available": available,
        "message": message,
        "config": agent.llm_config.to_dict(),
    }


@app.get("/api/llm/models")
async def llm_models():
    """List available models from the current provider."""
    models = agent.llm.list_models()
    return {"models": models, "current": agent.llm_config.model}


@app.get("/api/llm/config")
async def get_llm_config():
    """Get current LLM configuration."""
    return agent.llm_config.to_dict()


@app.post("/api/llm/config")
async def set_llm_config(body: LLMConfigRequest):
    """Update LLM configuration."""
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    log.info("POST /api/llm/config — updating: %s", data)
    agent.llm_config.update(data)
    agent.llm = LLMProvider(agent.llm_config)
    return {"status": "ok", "config": agent.llm_config.to_dict()}


# =====================================================================
#  REST API — Activity & Notes
# =====================================================================

@app.get("/api/activity")
async def api_activity(
    type: str = "",
    tool: str = "",
    days: int = 0,
    page: int = 1,
    limit: int = 50,
):
    """List activities with filters."""
    return activity_store.get_activities(
        act_type=type, tool=tool, days=days, page=page, limit=limit,
    )


@app.get("/api/activity/stats")
async def api_activity_stats(days: int = 30):
    """Usage statistics."""
    return activity_store.get_activity_stats(days)


@app.get("/api/activity/export")
async def api_activity_export(fmt: str = "json"):
    """Export activities as JSON or CSV. Use fmt=json or fmt=csv."""
    data = activity_store.export_activities(fmt)
    mime = "text/csv" if fmt == "csv" else "application/json"
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f"attachment; filename=activity.{fmt}"},
    )


@app.delete("/api/activity/{activity_id}")
async def api_activity_delete(activity_id: str):
    """Delete a single activity entry by ID."""
    if activity_store.delete_activity(activity_id):
        return {"status": "ok", "deleted": activity_id}
    return JSONResponse({"error": "Activity not found"}, status_code=404)


@app.delete("/api/activity")
async def api_activity_clear():
    """Delete ALL activity entries (clear the journal)."""
    count = activity_store.clear_activities()
    log.info("Activity journal cleared — %d entries removed", count)
    return {"status": "ok", "deleted": count}


@app.get("/api/notes")
async def api_notes_list(category: str = "", search: str = "", sort: str = "newest"):
    """List notes with optional category filter, search, sort."""
    notes = activity_store.list_notes(category=category, search=search, sort=sort)
    categories = activity_store.get_note_categories()
    return {"notes": notes, "categories": categories, "total": len(notes)}


@app.post("/api/notes")
async def api_notes_create(body: NoteCreateRequest):
    """Create a new note."""
    if not body.text.strip():
        return JSONResponse({"error": "Note text is required"}, status_code=400)
    note = activity_store.save_note(
        text=body.text.strip(),
        category=body.category,
        tags=body.tags,
        color=body.color,
        source=body.source,
    )
    return {"status": "ok", "note": note}


@app.put("/api/notes/{note_id}")
async def api_notes_update(note_id: str, body: NoteUpdateRequest):
    """Update a note."""
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    note = activity_store.update_note(note_id, **fields)
    if note is None:
        return JSONResponse({"error": "Note not found"}, status_code=404)
    return {"status": "ok", "note": note}


@app.delete("/api/notes/{note_id}")
async def api_notes_delete(note_id: str):
    """Delete a note."""
    if activity_store.delete_note(note_id):
        return {"status": "ok"}
    return JSONResponse({"error": "Note not found"}, status_code=404)


@app.post("/api/notes/{note_id}/pin")
async def api_notes_pin(note_id: str, body: PinRequest):
    """Toggle pin on a note."""
    note = activity_store.pin_note(note_id, body.pinned)
    if note is None:
        return JSONResponse({"error": "Note not found"}, status_code=404)
    return {"status": "ok", "note": note}


# =====================================================================
#  REST API — OCR File Upload
# =====================================================================

_OCR_UPLOADS_DIR = Path(__file__).parent.parent / "ocr_uploads"


@app.post("/api/ocr/upload")
async def ocr_upload(file: UploadFile = File(...)):
    """Handle image upload for OCR scanning."""
    log.info("POST /api/ocr/upload — filename=%s", file.filename)
    try:
        if not file.filename:
            return JSONResponse({"error": "No file selected"}, status_code=400)

        allowed_ext = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp"}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_ext:
            return JSONResponse(
                {"error": f"Unsupported format '{ext}'. Use: {', '.join(sorted(allowed_ext))}"},
                status_code=400,
            )

        _OCR_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        import time as _time
        safe_name = f"{int(_time.time())}_{file.filename.replace(' ', '_')}"
        save_path = _OCR_UPLOADS_DIR / safe_name
        content = await file.read()
        save_path.write_bytes(content)
        file_size = len(content)
        log.info("Uploaded file saved to %s (%d bytes)", save_path, file_size)

        # Run OCR via the tool
        t0 = time.perf_counter()
        result = TOOL_REGISTRY["document_ocr"]["function"](f"scan {save_path}")
        elapsed = (time.perf_counter() - t0) * 1000
        log.info("OCR upload completed in %.1f ms", elapsed)
        activity_store.log_activity(
            act_type="tool", tool="document_ocr",
            input_text=f"scan {save_path}", output_text=result,
            success=True, duration_ms=elapsed,
        )
        return {"tool": "document_ocr", "input": file.filename, "result": result}
    except Exception as e:
        log.exception("OCR upload processing failed")
        return JSONResponse({"error": str(e)}, status_code=500)


# =====================================================================
#  REST API — Sessions
# =====================================================================

@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions."""
    return {"sessions": session_manager.list_sessions(), "count": session_manager.count}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session details."""
    session = session_manager.get_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return session.to_dict()


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session."""
    if session_manager.delete_session(session_id):
        return {"status": "ok"}
    return JSONResponse({"error": "Session not found"}, status_code=404)


# =====================================================================
#  REST API — Memory
# =====================================================================

@app.get("/api/memory/stats")
async def memory_stats():
    """Get memory store statistics (conversations, facts, cache)."""
    return agent.memory_store.stats()


@app.get("/api/memory/conversations")
async def list_conversations():
    """List session IDs that have stored conversations."""
    ids = agent.memory_store.get_session_ids(limit=100)
    return {"sessions": ids, "count": len(ids)}


@app.get("/api/memory/conversations/{session_id}")
async def get_conversation(session_id: str, limit: int = 50):
    """Get conversation history for a session."""
    msgs = agent.memory_store.get_conversation(session_id, limit=limit)
    return {
        "session_id": session_id,
        "messages": [
            {"role": m.role, "content": m.content, "timestamp": m.timestamp}
            for m in msgs
        ],
        "count": len(msgs),
    }


@app.delete("/api/memory/conversations/{session_id}")
async def delete_conversation(session_id: str):
    """Delete conversation history for a session."""
    count = agent.memory_store.delete_conversation(session_id)
    return {"status": "ok", "deleted": count}


@app.get("/api/memory/facts")
async def list_facts(q: str = ""):
    """List or search persistent facts."""
    facts = agent.memory_store.search_facts(q, limit=50)
    return {
        "facts": [
            {"key": f.key, "value": f.value, "source": f.source}
            for f in facts
        ],
        "count": len(facts),
    }


@app.post("/api/memory/facts")
async def save_fact(body: FactRequest):
    """Save a persistent fact."""
    if not body.key.strip() or not body.value.strip():
        return JSONResponse({"error": "key and value required"}, status_code=400)
    agent.memory_store.save_fact(body.key.strip(), body.value.strip(), source=body.source)
    return {"status": "ok", "key": body.key}


@app.delete("/api/memory/facts/{key}")
async def delete_fact(key: str):
    """Delete a persistent fact."""
    if agent.memory_store.delete_fact(key):
        return {"status": "ok"}
    return JSONResponse({"error": "Fact not found"}, status_code=404)


# =====================================================================
#  Channel Webhook Router
# =====================================================================

@app.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    """WhatsApp webhook verification (GET challenge-response)."""
    challenge = verify_webhook_challenge(dict(request.query_params))
    if challenge:
        return Response(content=challenge, media_type="text/plain")
    return JSONResponse({"error": "Verification failed"}, status_code=403)


@app.post("/webhook/{channel}")
async def channel_webhook(channel: str, request: Request):
    """
    Incoming webhook for external channels (WhatsApp, Slack, etc.).
    Routes through the appropriate ChannelAdapter.
    """
    adapter = _channel_adapters.get(channel)
    if not adapter:
        return JSONResponse(
            {"error": f"Unknown channel: {channel}. Supported: {list(_channel_adapters.keys())}"},
            status_code=404,
        )

    body = await request.json()
    log.info("POST /webhook/%s — payload keys: %s", channel, list(body.keys()))

    # ── Slack URL verification challenge ──
    if channel == "slack" and body.get("type") == "url_verification":
        return JSONResponse({"challenge": body.get("challenge", "")})

    # ── Discord PING verification ──
    if channel == "discord" and body.get("type") == 1:
        return JSONResponse({"type": 1})  # PONG

    # ── Verify request authenticity ──
    verify_data = dict(body)
    verify_data["_signature"] = (
        request.headers.get("X-Hub-Signature-256", "")
        or request.headers.get("X-Slack-Signature", "")
        or request.headers.get("X-Signature-Ed25519", "")
    )
    verify_data["_timestamp"] = (
        request.headers.get("X-Slack-Request-Timestamp", "")
        or request.headers.get("X-Signature-Timestamp", "")
    )
    verify_data["_secret_token"] = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    verify_data["_body"] = await request.body()

    if not await adapter.verify_request(verify_data):
        log.warning("Webhook %s — signature verification failed", channel)
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # ── Parse incoming message ──
    try:
        message: NormalizedMessage = await adapter.parse_incoming(body)
    except ValueError as e:
        err_str = str(e)
        # Slack bot self-message, Teams conversationUpdate, or special signals
        if "__ignore__" in err_str:
            return JSONResponse({"ok": True})  # 200 to prevent retries
        if "__url_verification__" in err_str:
            challenge = err_str.split(":", 1)[1]
            return JSONResponse({"challenge": challenge})
        if "__discord_ping__" in err_str:
            return JSONResponse({"type": 1})
        log.warning("Webhook %s parse error: %s", channel, e)
        return JSONResponse({"error": str(e)}, status_code=400)

    # ── Get or create a session ──
    session = session_manager.get_or_create(
        session_id=message.session_id, channel=channel, user_id=message.sender_id,
    )
    session.add_message("user", message.text)

    # ── Run the agent ──
    try:
        t0 = time.perf_counter()
        result = await asyncio.to_thread(
            agent.run, message.text, session.session_id
        )
        elapsed = (time.perf_counter() - t0) * 1000

        reply = AgentReply(
            text=result.get("answer", ""),
            steps=result.get("steps", []),
            plan=result.get("plan", []),
            mode=result.get("mode", ""),
            model=result.get("model", ""),
            metadata=message.metadata,
        )

        session.add_message("assistant", reply.text)

        # Log activity
        tools_used = ", ".join(
            s.get("tool", "") for s in result.get("steps", [])
            if s.get("tool") and s["tool"] != "none"
        )
        activity_store.log_activity(
            act_type="chat", tool=tools_used,
            input_text=message.text, output_text=reply.text,
            success=True, duration_ms=elapsed,
            mode=result.get("mode", ""), model=result.get("model", ""),
            steps=len(result.get("steps", [])),
            session_id=session.session_id,
        )

        # Send reply back via channel
        await adapter.send_reply(session.session_id, reply)

        log.info("Webhook %s completed in %.1f ms", channel, elapsed)
        return JSONResponse({"ok": True})

    except Exception as e:
        log.exception("Webhook %s processing error: %s", channel, e)
        return JSONResponse({"error": str(e)}, status_code=500)
