# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup & Install
```bash
# Windows
manage.bat install

# Unix/Mac
./manage.sh install
```

### Run the Server
```bash
python main.py                        # Start web server (default: 0.0.0.0:5000)
python main.py --port 8080            # Custom port
python main.py --reload               # Dev mode with auto-reload
```

### Run in CLI Mode
```bash
python main.py --cli                  # Interactive CLI (menu with 4 modes)
./manage.sh cli                       # Same, via manage script
```

### Manage Lifecycle (manage.sh / manage.bat)
```bash
./manage.sh start / stop / restart / status
./manage.sh log [N]    # Show last N log lines (default 50)
./manage.sh logf       # Tail -f the log live
./manage.sh clean      # Remove logs, pid file, __pycache__
./manage.sh purge      # clean + remove .venv
```

### Manual Testing (no test suite exists)
```bash
# Run demo queries that exercise all tools
python main.py --cli   # Choose option 1

# Swagger UI + all REST endpoints
curl http://localhost:5000/api/tools
open http://localhost:5000/docs
```

## Architecture

AgentForge is a multi-channel AI agent platform implementing the **ReAct loop** (Reason → Act → Observe). It supports 8 messaging channels unified under a single FastAPI gateway.

```
Browser / Slack / WhatsApp / Telegram / Discord / Teams / Email / CLI
                        │
              gateway/server.py        (FastAPI + uvicorn, REST + WebSocket)
                        │
              gateway/session.py       (in-memory sessions, TTL cleanup)
                        │
              runtime/agent.py         (ReAct loop: LLM or keyword fallback)
               /              \
  llm/provider.py          runtime/tools.py     (24 tools)
  (Ollama / OpenAI)
                        │
              runtime/memory.py        (SQLite: conversations, facts, tool cache)
```

### Key Concepts

**ReAct Loop (`runtime/agent.py`)** — `AgentForge.run(query)` dispatches to either:
- `run_with_llm()` — Up to `AGENT_MAX_STEPS` (default 20) iterations; LLM responds with structured JSON `{"action": "tool_call", "tool": "...", "input": "..."}` or `{"action": "answer", "text": "..."}`
- `run_with_keywords()` — Regex-based fallback that always works without an LLM

**Runtime Personality Files (`runtime/*.md`)** — Loaded on every request by `AgentForge._system_prompt()` and injected into the LLM system prompt. Edit these files at any time — changes take effect on the next message, no restart needed:

| File | Purpose |
|---|---|
| `runtime/SOUL.md` | Agent personality, tone, communication style |
| `runtime/AGENTS.md` | Hard rules the agent must never break, behavioral guidelines, forbidden actions |
| `runtime/USER.md` | User profile/preferences; the agent can update this via `file_manager` |
| `runtime/TOOLS.md` | Tool selection hints injected after the tool list |
| `runtime/HEARTBEAT.md` | Scheduled background task definitions (format defined, scheduler not yet implemented) |

**Channel Adapters (`gateway/channels/`)** — Each channel implements the `ChannelAdapter` protocol from `base.py`:
- `parse_incoming(raw_data)` → `NormalizedMessage`
- `send_reply(session_id, reply)` sends an `AgentReply`

Channels are registered in `gateway/channels/__init__.py` and routed via `/webhook/{channel}` in `server.py`.

**Tool Registry (`runtime/tools.py`)** — All 24 tools are plain Python functions registered in `TOOL_REGISTRY` (dict of name → `{function, description, params}`). The LLM sees these in its system prompt. Tools are sandboxed: `_safe_path()` confines file ops to `WORKSPACE_ROOT` (defaults to the `runtime/` directory).

**LLM Provider (`llm/provider.py`)** — `LLMProvider.chat(messages, json_mode)` abstracts Ollama (HTTP to `localhost:11434`) and OpenAI. Falls back to keyword mode on any error.

**Memory (`runtime/memory.py`)** — SQLite-backed 3-tier store: per-session conversation history, long-term key/value facts, and TTL-based tool result cache. `get_datetime` results are cached for 60s; all other tools for 300s.

**Session Management (`gateway/session.py`)** — In-memory `SessionManager` with background TTL cleanup. Sessions track channel, user_id, and message history.

**Configuration (`config.py`)** — Dataclass-based singletons (`AppConfig`, `LLMSettings`) populated from environment variables. No `.env` file needed; all settings have defaults.

**Logging (`log_config.py`)** — Three handlers: rotating file (`app.log`, 5 MB × 3), coloured console, and a 500-entry ring buffer exposed via `/ws/logs` WebSocket for the dashboard.

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` / `openai` / `keyword` |
| `LLM_MODEL` | auto-detect | Model name |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `OPENAI_API_KEY` | (empty) | Required for OpenAI |
| `AGENT_MAX_STEPS` | `20` | Max ReAct iterations per request |
| `AGENT_WORKSPACE` | `runtime/` dir | Sandbox root for file tool operations |
| `APP_PORT` | `5000` | Server port |
| `APP_HOST` | `0.0.0.0` | Server bind address |
| `SESSION_TTL` | `1800` | Session timeout (seconds) |
| `MAX_UPLOAD_MB` | `16` | File upload size limit |
| `LOG_LEVEL` | `DEBUG` | Logging verbosity |

### Adding a New Tool
1. Add a function to `runtime/tools.py`
2. Register it in `TOOL_REGISTRY` with `function`, `description`, and `params` keys
3. The agent automatically includes it in the LLM's system prompt on the next request

### Adding a New Channel
1. Create `gateway/channels/<name>.py` implementing `ChannelAdapter`
2. Register it in `gateway/channels/__init__.py`
3. Add a webhook route in `gateway/server.py` at `/webhook/<name>`

### Legacy v1 Files
`app.py`, `agent.py`, `tools.py`, `llm_provider.py`, `activity_store.py`, `main_cli.py` — the original Flask-based v1 implementation kept for reference. All active development uses the `gateway/`, `runtime/`, and `llm/` packages.

### Auto-created Files (gitignore candidates)
`memory.db`, `runtime/ocr_index.json`, `runtime/agent_notes.json`, `runtime/agent_activity.json`, `app.log`, `ocr_uploads/`, `.app.pid`, `nul`
