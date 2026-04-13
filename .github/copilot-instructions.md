# AgentForge — Workspace Instructions

Full architecture and command reference: [CLAUDE.md](../CLAUDE.md)

## Architecture

AgentForge is a **FastAPI + ReAct-loop agent platform** (v2). All active code lives in three packages:

| Package    | Purpose                                                      |
| ---------- | ------------------------------------------------------------ |
| `gateway/` | FastAPI server, session management, 8 channel adapters       |
| `runtime/` | ReAct agent loop, 24 tools, SQLite memory, personality files |
| `llm/`     | Ollama / OpenAI provider abstraction                         |

**Do NOT edit v1 legacy files** (`app.py`, `agent.py`, `tools.py`, `llm_provider.py`, `main_cli.py`, `activity_store.py`) — kept for reference only. All changes go to the `gateway/`, `runtime/`, and `llm/` packages.

## Build & Run

```bash
# Install (creates .venv)
manage.bat install          # Windows
./manage.sh install         # Unix/Mac

# Start server (http://localhost:5000)
python main.py
python main.py --reload     # Dev mode with auto-reload
python main.py --cli        # Interactive CLI

# Lifecycle management
manage.bat start / stop / restart / status / log / logf / clean
```

No test suite — manual testing via `python main.py --cli` and `http://localhost:5000/docs` (Swagger).

## Key Conventions

### Adding a Tool

1. Add a plain `def my_tool(input: str) -> str` function in `runtime/tools.py`
2. Register it in `TOOL_REGISTRY` (bottom of file): `{"function": my_tool, "description": "..."}`
3. The LLM sees it on the next request — **no restart needed**
4. All file access must go through `_safe_path()` (enforces `AGENT_WORKSPACE` sandbox)

### Adding a Channel

1. Create `gateway/channels/<name>.py` implementing `ChannelAdapter` from `base.py`  
   — Required: `channel_name`, `parse_incoming()` → `NormalizedMessage`, `send_reply()` → `bool`
2. Register in `gateway/channels/__init__.py`
3. Webhook auto-routed at `/webhook/<name>` in `gateway/server.py`

### Personality Files (`runtime/*.md`)

Loaded on every request — **edit anytime, no restart needed**:

| File                   | Controls                                                           |
| ---------------------- | ------------------------------------------------------------------ |
| `runtime/SOUL.md`      | Agent tone and communication style                                 |
| `runtime/AGENTS.md`    | Hard rules and forbidden actions (injected into LLM system prompt) |
| `runtime/USER.md`      | User profile — agent can update via `file_manager` tool            |
| `runtime/TOOLS.md`     | Tool-selection hints for the LLM                                   |
| `runtime/HEARTBEAT.md` | Scheduled task definitions (scheduler not yet implemented)         |

## Pitfalls

- **`nodes/` package is unused** — it's a Phase 4 placeholder; don't integrate it into anything yet
- **File sandbox**: `_safe_path()` restricts all file ops to `AGENT_WORKSPACE` (default: `runtime/`). Paths escaping it raise `PermissionError`
- **Auto-created files** (gitignore these): `memory.db`, `app.log`, `.app.pid`, `nul`, `ocr_uploads/`, `runtime/ocr_index.json`, `runtime/agent_notes.json`, `runtime/agent_activity.json`
- **LLM fallback**: Set `LLM_PROVIDER=keyword` to run without any LLM — regex-based tool dispatch always works
- **`runtime/AGENTS.md`** is the agent's runtime rules file injected into LLM prompts — it is **not** the VS Code workspace instructions file
