# AgentForge v2.0

A multi-channel, LLM-powered AI agent platform with **FastAPI**, **WebSocket**, real-time chat, and 25 built-in tools.

---

## What Is an AI Agent?

An **AI Agent** is a program that can:

1. **Perceive** — Receive a task/question from the user
2. **Think / Plan** — Break the task into steps (reasoning)
3. **Act** — Use **tools** (functions) to accomplish each step
4. **Observe** — Read the result of each tool call
5. **Loop** — Repeat Think → Act → Observe until the task is done
6. **Respond** — Return the final answer to the user

This is called the **ReAct loop** (Reason + Act).

## Architecture Overview

```
                     ┌─────────────────────────────────────────────┐
  Browser ──────────►│           gateway/server.py                 │
  (WebSocket/REST)   │           FastAPI + Uvicorn                 │
                     │                                             │
  Slack  ───────────►│   /webhook/slack      → SlackAdapter        │
  WhatsApp ─────────►│   /webhook/whatsapp   → WhatsAppAdapter     │
  Telegram ─────────►│   /webhook/telegram   → TelegramAdapter     │
  Discord ──────────►│   /webhook/discord    → DiscordAdapter      │
  MS Teams ─────────►│   /webhook/teams      → TeamsAdapter        │
  Email ────────────►│   /webhook/email      → EmailAdapter        │
  CLI ──────────────►│   main.py --cli       → direct              │
                     └──────────────┬──────────────────────────────┘
                                    │
                          ┌─────────▼────────── ┐
                          │   runtime/agent.py  │
                          │   ReAct Loop        │
                          │   (LLM or Keyword)  │
                          └──┬──────────┬───────┘
                             │          │
                   ┌─────────▼──┐  ┌────▼────────────┐
                   │ llm/       │  │ runtime/tools.py │
                   │ provider.py│  │ 14 real tools    │
                   │ (Ollama /  │  └──────────────────┘
                   │  OpenAI)   │
                   └────────────┘
```

**8 incoming channels** — all routed through the same agent with unified session management.
If no LLM is available, the agent falls back to **keyword matching** (always works).

---

## Quick Start

### 1. Install & Run (Web Server)

```bash
# Clone / navigate to the project
cd agent_forge

# (Optional) Create virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the FastAPI server
python main.py
```

The server starts on **http://localhost:5000** with:

| Endpoint                                   | Description                    |
| ------------------------------------------ | ------------------------------ |
| `http://localhost:5000`                    | Web dashboard                  |
| `http://localhost:5000/docs`               | Interactive API docs (Swagger) |
| `ws://localhost:5000/ws/chat/{session_id}` | WebSocket real-time chat       |
| `ws://localhost:5000/ws/logs`              | Live log streaming             |

### 2. Using the Management Scripts

```bash
# Windows
manage.bat install      # Create venv & install deps
manage.bat start        # Start the server (background)
manage.bat stop         # Stop the server
manage.bat restart      # Restart
manage.bat status       # Check if running
manage.bat log          # Tail the log file
manage.bat clean        # Remove caches & temp files
manage.bat help         # Show all commands

# macOS / Linux
chmod +x manage.sh
./manage.sh install
./manage.sh start
```

### 3. CLI Mode (Interactive Terminal)

```bash
python main.py --cli
```

Options: run demo examples, interactive chat, or use Ollama LLM directly.

### 4. Custom Host/Port

```bash
python main.py --host 127.0.0.1 --port 8080
python main.py --reload    # Auto-reload for development
```

---

## LLM Configuration

The agent supports **Ollama** (local, free) and **OpenAI** (cloud) as its brain.

### Ollama (Recommended for Local Use)

```bash
# 1. Install from https://ollama.com
# 2. Pull a model:
ollama pull llama3.2

# 3. Start the agent — Ollama is auto-detected on localhost:11434
python main.py
```

### OpenAI / Compatible APIs

Set environment variables or configure via the web UI (⚙ LLM Settings):

```bash
set LLM_PROVIDER=openai
set LLM_MODEL=gpt-4o-mini
set OPENAI_API_KEY=sk-...
python main.py
```

Works with OpenAI-compatible servers (LM Studio, Together, Groq, etc.):

```bash
set OPENAI_BASE_URL=http://localhost:1234/v1
```

### Keyword Fallback

If no LLM is available, the agent works with **keyword matching** — no API keys needed.

### Environment Variables

| Variable          | Default                     | Description                         |
| ----------------- | --------------------------- | ----------------------------------- |
| `APP_HOST`        | `0.0.0.0`                   | Server bind address                 |
| `APP_PORT`        | `5000`                      | Server port                         |
| `LLM_PROVIDER`    | `ollama`                    | `ollama` / `openai` / `keyword`     |
| `LLM_MODEL`       | (auto-detected)             | Model name                          |
| `OLLAMA_URL`      | `http://localhost:11434`    | Ollama server URL                   |
| `OPENAI_API_KEY`  | (empty)                     | OpenAI API key                      |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL          |
| `LLM_TEMPERATURE` | `0.2`                       | Response randomness (0.0–1.0)       |
| `LLM_MAX_TOKENS`  | `1024`                      | Max response length                 |
| `SESSION_TTL`     | `1800`                      | Session timeout in seconds (30 min) |
| `MAX_UPLOAD_MB`   | `16`                        | Max file upload size                |
| `LOG_LEVEL`       | `DEBUG`                     | Logging level                       |

---

## 14 Built-in Tools — No API Keys Needed

| #   | Tool                 | What It Does                                                                |
| --- | -------------------- | --------------------------------------------------------------------------- |
| 1   | **calculator**       | Full math: `sqrt`, `sin`, `cos`, `log`, `factorial`, `pi`, `e`, etc.        |
| 2   | **get_datetime**     | Current date/time with timezone support (UTC offsets)                       |
| 3   | **weather_lookup**   | **Real** weather for ANY city worldwide via [wttr.in](https://wttr.in)      |
| 4   | **web_search**       | Search the web via DuckDuckGo (top 8 results)                               |
| 5   | **wikipedia_lookup** | Get Wikipedia summaries for any topic                                       |
| 6   | **url_fetcher**      | Fetch & extract readable text from any URL (HTML, JSON)                     |
| 7   | **unit_converter**   | 80+ conversion pairs: length, weight, temp, volume, area, speed, data, time |
| 8   | **file_manager**     | Read, write, append, list directories, file info                            |
| 9   | **system_info**      | OS, CPU, Python version, hostname, IP                                       |
| 10  | **text_analyzer**    | Word/char/sentence count, reading time, top words, uniqueness ratio         |
| 11  | **hash_encode**      | MD5, SHA-256, SHA-1, Base64, URL encode/decode                              |
| 12  | **ip_lookup**        | Public IP + geolocation for any IP or domain                                |
| 13  | **note_taker**       | Persistent notes: save (with #tags), list, search, edit, pin, delete        |
| 14  | **document_ocr**     | Scan images → extract text → searchable index (local OCR via Tesseract)     |

---

## REST API Reference

All endpoints are available under `/api/`. Interactive docs at `/docs` (Swagger UI).

### Chat & Tools

| Method | Endpoint     | Description                        |
| ------ | ------------ | ---------------------------------- |
| POST   | `/api/chat`  | Send a message, get agent response |
| POST   | `/api/tool`  | Run a single tool directly         |
| GET    | `/api/tools` | List all tools with metadata       |

### LLM Configuration

| Method | Endpoint          | Description                   |
| ------ | ----------------- | ----------------------------- |
| GET    | `/api/llm/status` | Check LLM availability        |
| GET    | `/api/llm/models` | List available models         |
| GET    | `/api/llm/config` | Get current LLM configuration |
| POST   | `/api/llm/config` | Update LLM configuration      |

### Memory & Sessions

| Method | Endpoint                         | Description                  |
| ------ | -------------------------------- | ---------------------------- |
| GET    | `/api/memory`                    | View agent memory            |
| POST   | `/api/memory/clear`              | Clear agent memory           |
| GET    | `/api/memory/stats`              | Memory store statistics      |
| GET    | `/api/memory/conversations`      | List stored sessions         |
| GET    | `/api/memory/conversations/{id}` | Get conversation history     |
| DELETE | `/api/memory/conversations/{id}` | Delete conversation history  |
| GET    | `/api/memory/facts`              | List/search persistent facts |
| POST   | `/api/memory/facts`              | Save a fact                  |
| DELETE | `/api/memory/facts/{key}`        | Delete a fact                |
| GET    | `/api/sessions`                  | List active sessions         |
| GET    | `/api/sessions/{id}`             | Get session details          |
| DELETE | `/api/sessions/{id}`             | Delete a session             |

### Activity & Notes

| Method | Endpoint               | Description                                 |
| ------ | ---------------------- | ------------------------------------------- |
| GET    | `/api/activity`        | List activities (filters: type, tool, days) |
| GET    | `/api/activity/stats`  | Usage statistics                            |
| GET    | `/api/activity/export` | Export as JSON or CSV                       |
| GET    | `/api/notes`           | List notes                                  |
| POST   | `/api/notes`           | Create a note                               |
| PUT    | `/api/notes/{id}`      | Update a note                               |
| DELETE | `/api/notes/{id}`      | Delete a note                               |
| POST   | `/api/notes/{id}/pin`  | Toggle pin                                  |

### OCR & Channels

| Method | Endpoint            | Description                     |
| ------ | ------------------- | ------------------------------- |
| POST   | `/api/ocr/upload`   | Upload image for OCR scanning   |
| POST   | `/webhook/slack`    | Slack Events API webhook        |
| POST   | `/webhook/whatsapp` | WhatsApp Cloud API webhook      |
| GET    | `/webhook/whatsapp` | WhatsApp verification challenge |
| POST   | `/webhook/telegram` | Telegram Bot API webhook        |
| POST   | `/webhook/discord`  | Discord Interactions webhook    |
| POST   | `/webhook/teams`    | Microsoft Teams Bot Framework   |
| POST   | `/webhook/email`    | Email inbound parse webhook     |

### WebSocket Endpoints

| Endpoint                      | Description                  |
| ----------------------------- | ---------------------------- |
| `ws://host:port/ws/chat/{id}` | Real-time bidirectional chat |
| `ws://host:port/ws/logs`      | Live log streaming to UI     |

---

## Testing

### Quick Smoke Test (No LLM Required)

```bash
# 1. Start the server
python main.py

# 2. Test a tool directly via REST
curl -X POST http://localhost:5000/api/tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "calculator", "input": "factorial(10) / sqrt(144)"}'

# 3. Test the chat endpoint (keyword mode)
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the weather in Tokyo?"}'

# 4. Check LLM status
curl http://localhost:5000/api/llm/status

# 5. List tools
curl http://localhost:5000/api/tools

# 6. Open dashboard in browser
start http://localhost:5000
```

### PowerShell (Windows)

```powershell
# Test a tool
Invoke-RestMethod -Uri http://localhost:5000/api/tool `
  -Method POST -ContentType "application/json" `
  -Body '{"tool": "get_datetime", "input": ""}'

# Test chat
Invoke-RestMethod -Uri http://localhost:5000/api/chat `
  -Method POST -ContentType "application/json" `
  -Body '{"message": "Convert 100 F to C"}'
```

### Test with Ollama LLM

```bash
# Ensure Ollama is running with a model
ollama pull llama3.2
ollama serve   # if not already running

# Start the agent (auto-detects Ollama)
python main.py

# The chat endpoint will now use LLM reasoning
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Who is Alan Turing and what is he famous for?"}'
```

### CLI Testing

```bash
# Run demo examples (tests all tools automatically)
python main.py --cli
# Choose option 1 (demo), 2 (interactive), or 4 (with Ollama LLM)
```

### WebSocket Testing

Use a WebSocket client (browser console, wscat, or Postman):

```javascript
// Browser console
const ws = new WebSocket('ws://localhost:5000/ws/chat/test123');
ws.onmessage = (e) => console.log(JSON.parse(e.data));
ws.onopen = () => ws.send(JSON.stringify({ message: 'Hello!' }));
```

```bash
# Using wscat
npm install -g wscat
wscat -c ws://localhost:5000/ws/chat/test_session
> {"message": "What time is it?"}
```

### Channel Webhook Testing

#### Slack

```bash
# Simulate a Slack event
curl -X POST http://localhost:5000/webhook/slack \
  -H "Content-Type: application/json" \
  -d '{
    "type": "event_callback",
    "event": {
      "type": "message",
      "user": "U12345",
      "text": "weather in Paris",
      "channel": "C12345",
      "ts": "1234567890.123456"
    }
  }'
```

#### WhatsApp

```bash
# Simulate a WhatsApp message
curl -X POST http://localhost:5000/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{"changes": [{"value": {
      "messages": [{"from": "15551234567", "type": "text", "text": {"body": "Hello"}}],
      "contacts": [{"profile": {"name": "Test"}}]
    }}]}]
  }'
```

---

## Channel Setup

### Slack Bot

1. Create a Slack App at https://api.slack.com/apps
2. Set environment variables:
   ```bash
   set SLACK_BOT_TOKEN=xoxb-your-token
   set SLACK_SIGNING_SECRET=your-secret
   ```
3. Enable **Event Subscriptions** → Request URL: `https://your-domain.com/webhook/slack`
4. Subscribe to bot events: `message.channels`, `message.im`, `app_mention`
5. Install the app to your workspace

### WhatsApp Business

1. Set up a Meta Business App at https://developers.facebook.com
2. Set environment variables:
   ```bash
   set WHATSAPP_TOKEN=your-token
   set WHATSAPP_PHONE_ID=your-phone-id
   set WHATSAPP_VERIFY_TOKEN=agent_verify_token
   set WHATSAPP_APP_SECRET=your-app-secret   # optional, for signature verification
   ```
3. Configure webhook URL: `https://your-domain.com/webhook/whatsapp`
4. Subscribe to the `messages` webhook field

> **Note**: For local development, use [ngrok](https://ngrok.com) to expose your local server: `ngrok http 5000`

---

## Key Concepts

| Concept              | Location                             | Description                                   |
| -------------------- | ------------------------------------ | --------------------------------------------- |
| **ReAct Loop**       | `runtime/agent.py` → `run()`         | Think → Act → Observe → repeat cycle          |
| **LLM Provider**     | `llm/provider.py`                    | Ollama / OpenAI abstraction layer             |
| **Tools**            | `runtime/tools.py`                   | 25 real functions the agent can call          |
| **Tool Registry**    | `runtime/tools.py` → `TOOL_REGISTRY` | Agent knows available tools                   |
| **System Prompt**    | `runtime/agent.py` → `SYSTEM_PROMPT` | Tells the LLM about available tools           |
| **Memory (SQLite)**  | `runtime/memory.py`                  | Conversations, facts, tool cache (persistent) |
| **Sessions**         | `gateway/session.py`                 | Multi-user session isolation with TTL expiry  |
| **Channel Adapters** | `gateway/channels/`                  | Normalize messages from any platform          |
| **Activity Journal** | `runtime/activity_store.py`          | Auto-logged tool calls & chat interactions    |
| **Node Registry**    | `nodes/registry.py`                  | Remote device node tracking (Phase 4)         |
| **Gateway Server**   | `gateway/server.py`                  | FastAPI + WebSocket + webhook routing         |

## Project Structure

```
agent_forge/
├── main.py                  ← Entry point: FastAPI server or CLI mode
├── config.py                ← Centralised config (env-var overrides)
├── log_config.py            ← Logging: console, file, in-memory ring buffer
├── requirements.txt         ← Python dependencies
├── manage.bat / manage.sh   ← Management scripts (install/start/stop/status)
│
├── gateway/                 ← HTTP / WebSocket server layer
│   ├── server.py            ← FastAPI app: REST API, WebSocket, webhooks
│   ├── session.py           ← Multi-user session manager (TTL-based)
│   ├── templates/
│   │   └── index.html       ← Web dashboard UI
│   └── channels/            ← Messaging channel adapters
│       ├── base.py          ← Abstract ChannelAdapter + NormalizedMessage
│       ├── webchat.py       ← Browser WebSocket/REST adapter
│       ├── slack.py         ← Slack Events API adapter
│       └── whatsapp.py      ← WhatsApp Cloud API adapter
│
├── runtime/                 ← Agent core logic
│   ├── agent.py             ← ReAct loop (LLM-powered + keyword fallback)
│   ├── tools.py             ← 25 real-world tools (TOOL_REGISTRY)
│   ├── memory.py            ← SQLite-backed persistent memory
│   └── activity_store.py    ← Activity journal + notes store
│
├── llm/                     ← LLM abstraction
│   └── provider.py          ← Ollama & OpenAI provider (LLMConfig, LLMProvider)
│
├── nodes/                   ← Remote device nodes (Phase 4)
│   ├── protocol.py          ← WebSocket protocol (Gateway ↔ Node messages)
│   └── registry.py          ← Node tracking & capability registry
│
├── ocr_uploads/             ← Uploaded images for OCR (auto-created)
├── ocr_index.json           ← OCR document index (auto-created)
├── agent_notes.json         ← Persistent notes (auto-created)
├── agent_activity.json      ← Activity journal (auto-created)
├── memory.db                ← SQLite memory store (auto-created)
└── app.log                  ← Rotating log file (auto-created)
```

### Legacy v1 Files (Preserved)

The root-level `app.py` (Flask), `agent.py`, `tools.py`, `llm_provider.py`, `activity_store.py`, and `main_cli.py` are the original v1 implementation. They still work independently but are superseded by the v2 packaged architecture above. The v2 server (`python main.py`) is the recommended entry point.

---

## Example Queries

```
You > What's the weather in Berlin?
You > Calculate sin(pi/4) * sqrt(2)
You > Who is Marie Curie?
You > Search for best Python frameworks 2025
You > Convert 5 gallons to liters
You > What's my IP address?
You > Hash sha256 hello world
You > Analyze text: The quick brown fox jumps over the lazy dog
You > Read file requirements.txt
You > Save a note: meeting at 3pm tomorrow
You > What's the system info?
You > Scan this document image for text
You > Search my scanned documents for "invoice"
```

---

## Document OCR Tool

The **document_ocr** tool scans images (photos of documents, screenshots, etc.) and extracts structured text into a searchable index.

### Prerequisites

Install [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) engine:

```bash
# Windows (download installer):
# https://github.com/UB-Mannheim/tesseract/wiki

# macOS:
brew install tesseract

# Linux (Debian/Ubuntu):
sudo apt install tesseract-ocr
```

Check status in the app: select the OCR tool → type `status` → Run.

### How to Use — Three Ways

#### 1. Tool Test Mode (click OCR card in sidebar)

- **Browse Files** — click the 📁 button to pick a local image
- **Take Photo** — click the 📷 button (opens camera on mobile devices)
- **From URL** — click the 🔗 button to enter an image URL
- **Drag & Drop** — drag any image file onto the upload zone
- Click **Run ▶** to scan

#### 2. Chat Mode (📎 button in chat bar)

- Click the **📎** paperclip button next to the chat input
- Select an image file
- A preview strip appears above the chat bar
- Type a message (or use the default) and Send
- The agent runs OCR, then analyzes and answers based on the extracted text

#### 3. Text Commands (in tool test or chat)

```
scan <filepath>          — OCR a local image file
scan_url <url>           — Download and OCR an image from a URL
search <keyword>         — Full-text search across all scanned docs
list                     — List all scanned documents in the index
info <id-or-number>      — Show full extracted text of a document
delete <id-or-number>    — Remove a document from the index
clear                    — Clear the entire OCR index
status                   — Check Tesseract availability & index stats
```

### OCR Features

- **Image preprocessing**: auto grayscale, contrast enhancement, sharpening, binarization
- **Confidence scoring**: each scan reports OCR confidence percentage
- **Persistent index**: all scans saved to `ocr_index.json` for future searches
- **Context-aware search**: keyword search returns highlighted snippets with surrounding context
- **Format support**: PNG, JPG, BMP, TIFF, GIF, WebP

---

## What Could You Add Next?

- Add more LLM providers (Anthropic, Google Gemini, Groq)
- Add a vector-store memory for long-term recall
- Add multi-agent collaboration (agents talking to each other)
- Add a database query tool (SQLite, PostgreSQL)
- Add streaming responses for real-time output
- Add PDF document OCR (multi-page scanning)
- Add OCR language packs for non-English documents
- Build the Phase 4 remote device node layer (iOS/Android/desktop nodes)

---

## Architecture Map — Component Breakdown

| Concept                   | Implementation                               | Status   |
| ------------------------- | -------------------------------------------- | -------- |
| **Gateway (API Layer)**   | `gateway/server.py` (FastAPI + Uvicorn)      | ✅ Done  |
| ├─ REST endpoints         | `/api/chat`, `/api/tool`, `/api/tools`, etc. | ✅ Done  |
| ├─ WebSocket real-time    | `/ws/chat/{session_id}`                      | ✅ Done  |
| ├─ SSE fallback           | `/api/logs/stream`                           | ✅ Done  |
| └─ Webhook router         | `/webhook/{channel}`                         | ✅ Done  |
| **Channel Adapters**      | `gateway/channels/`                          | ✅ Done  |
| ├─ WebChat                | `webchat.py`                                 | ✅ Done  |
| ├─ WhatsApp               | `whatsapp.py`                                | ✅ Done  |
| ├─ Slack                  | `slack.py`                                   | ✅ Done  |
| ├─ Telegram               | `telegram.py`                                | ✅ Done  |
| ├─ Discord                | `discord.py`                                 | ✅ Done  |
| ├─ MS Teams               | `teams.py`                                   | ✅ Done  |
| ├─ Email                  | `email_channel.py`                           | ✅ Done  |
| └─ Base protocol          | `base.py` (NormalizedMessage / AgentReply)   | ✅ Done  |
| **Agent Runtime**         | `runtime/agent.py`                           | ✅ Done  |
| ├─ ReAct loop (LLM)       | `run_with_llm()` — 5-step max                | ✅ Done  |
| ├─ Keyword fallback       | `run_with_keywords()`                        | ✅ Done  |
| ├─ System prompt + tools  | Dynamic tool list in SYSTEM_PROMPT           | ✅ Done  |
| └─ JSON structured output | `_parse_llm_response()` with fallback        | ✅ Done  |
| **LLM Provider**          | `llm/provider.py`                            | ✅ Done  |
| ├─ Ollama (local)         | `_chat_ollama()`                             | ✅ Done  |
| ├─ OpenAI (cloud)         | `_chat_openai()`                             | ✅ Done  |
| ├─ Auto model detection   | `_auto_detect_model()`                       | ✅ Done  |
| └─ Runtime config switch  | `LLMConfig` dataclass + `/api/llm/config`    | ✅ Done  |
| **Session Management**    | `gateway/session.py`                         | ✅ Done  |
| ├─ TTL-based expiry       | 30 min default, background cleanup thread    | ✅ Done  |
| ├─ Per-user isolation     | Session per `session_id`                     | ✅ Done  |
| └─ Multi-channel tracking | `channel` field in Session                   | ✅ Done  |
| **Persistent Memory**     | `runtime/memory.py`                          | ✅ Done  |
| ├─ Conversation history   | SQLite `conversations` table                 | ✅ Done  |
| ├─ Long-term facts        | SQLite `facts` table                         | ✅ Done  |
| └─ Tool result cache      | SQLite `tool_cache` with TTL                 | ✅ Done  |
| **Tools Engine**          | `runtime/tools.py` (14 tools)                | ✅ Done  |
| **Activity Tracking**     | `runtime/activity_store.py`                  | ✅ Done  |
| **Node Protocol (Ph 4)**  | `nodes/protocol.py` + `nodes/registry.py`    | 🔲 Stubs |
| **Config Management**     | `config.py` (env vars + dataclasses)         | ✅ Done  |
| **Entry Points**          | `main.py` (server + CLI)                     | ✅ Done  |
| **Management Scripts**    | `manage.bat` + `manage.sh`                   | ✅ Done  |
| **Web Dashboard**         | `gateway/templates/index.html`               | ✅ Done  |

> **Note:** The only piece in stub form is the remote device nodes (Phase 4) —
> `protocol.py` and `registry.py` define message types and a node registry class
> but no `/ws/node` endpoint is wired into the gateway yet.

---

## Testing Guide — Layer by Layer

### Layer 1: Gateway — REST API

```bash
# 1a. Health check — dashboard loads
curl http://localhost:5000/

# 1b. List all 14 tools
curl http://localhost:5000/api/tools

# 1c. Chat via REST
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "what time is it"}'

# 1d. Direct tool call
curl -X POST http://localhost:5000/api/tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "calculator", "input": "factorial(10)"}'

# 1e. Unknown tool (should return 400)
curl -X POST http://localhost:5000/api/tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "nonexistent", "input": "test"}'

# 1f. Empty message (should return 400)
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": ""}'
```

### Layer 2: Gateway — WebSocket Chat

Open **http://localhost:5000** in a browser and:

1. Type `weather in London` → verify real weather data returns
2. Type `calculate sqrt(144)` → verify `Result: 12.0`
3. Check the "typing…" indicator appears while agent is processing
4. Open a second browser tab → verify separate `session_id` and isolated history
5. Refresh the page → verify you get a new session

### Layer 3: Gateway — Log Streaming

1. Open the dashboard → check that the **live log panel** shows real-time logs
2. Or test SSE fallback:

```bash
curl -N http://localhost:5000/api/logs/stream
```

Then send a chat in another terminal — you should see log entries stream in.

### Layer 4: LLM Provider

```bash
# 4a. Check LLM status
curl http://localhost:5000/api/llm/status

# 4b. List models
curl http://localhost:5000/api/llm/models

# 4c. Get current config
curl http://localhost:5000/api/llm/config

# 4d. Switch to keyword mode (no LLM needed)
curl -X POST http://localhost:5000/api/llm/config \
  -H "Content-Type: application/json" \
  -d '{"provider": "keyword"}'

# 4e. Test chat in keyword mode
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "weather in Paris"}'

# 4f. Switch back to Ollama
curl -X POST http://localhost:5000/api/llm/config \
  -H "Content-Type: application/json" \
  -d '{"provider": "ollama"}'
```

### Layer 5: Session Management

```bash
# 5a. List active sessions
curl http://localhost:5000/api/sessions

# 5b. Chat with a named session
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hello", "session_id": "test-session-1"}'

# 5c. Get session details
curl http://localhost:5000/api/sessions/test-session-1

# 5d. Delete session
curl -X DELETE http://localhost:5000/api/sessions/test-session-1
```

### Layer 6: Persistent Memory

```bash
# 6a. Memory stats
curl http://localhost:5000/api/memory/stats

# 6b. List conversations
curl http://localhost:5000/api/memory/conversations

# 6c. Get conversation history
curl http://localhost:5000/api/memory/conversations/test-session-1

# 6d. Save a fact
curl -X POST http://localhost:5000/api/memory/facts \
  -H "Content-Type: application/json" \
  -d '{"key": "user_city", "value": "London"}'

# 6e. List facts
curl http://localhost:5000/api/memory/facts

# 6f. Delete fact
curl -X DELETE http://localhost:5000/api/memory/facts/user_city

# 6g. Delete conversation
curl -X DELETE http://localhost:5000/api/memory/conversations/test-session-1
```

### Layer 7: Activity & Notes

```bash
# 7a. Activity log
curl http://localhost:5000/api/activity

# 7b. Activity stats
curl http://localhost:5000/api/activity/stats

# 7c. Export as CSV
curl http://localhost:5000/api/activity/export?format=csv

# 7d. Create a note
curl -X POST http://localhost:5000/api/notes \
  -H "Content-Type: application/json" \
  -d '{"text": "Test note from API", "category": "testing"}'

# 7e. List notes
curl http://localhost:5000/api/notes

# 7f. Pin a note (replace {note_id} with actual ID from 7e response)
curl -X POST http://localhost:5000/api/notes/{note_id}/pin \
  -H "Content-Type: application/json" \
  -d '{"pinned": true}'

# 7g. Delete a note
curl -X DELETE http://localhost:5000/api/notes/{note_id}
```

### Layer 8: Channel Webhooks

```bash
# 8a. Slack URL verification
curl -X POST http://localhost:5000/webhook/slack \
  -H "Content-Type: application/json" \
  -d '{"type": "url_verification", "challenge": "test123"}'
# Expect: {"challenge": "test123"}

# 8b. Discord PING
curl -X POST http://localhost:5000/webhook/discord \
  -H "Content-Type: application/json" \
  -d '{"type": 1}'
# Expect: {"type": 1}

# 8c. Unknown channel (should return 404)
curl -X POST http://localhost:5000/webhook/unknown \
  -H "Content-Type: application/json" \
  -d '{"text": "hi"}'

# 8d. WhatsApp verification
curl "http://localhost:5000/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=test&hub.challenge=abc123"
```

### Layer 9: All 14 Tools (via REST)

```bash
curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"calculator","input":"2**10"}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"get_datetime","input":"+5:30"}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"weather_lookup","input":"Tokyo"}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"web_search","input":"python tutorials"}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"wikipedia_lookup","input":"Alan Turing"}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"url_fetcher","input":"https://httpbin.org/json"}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"unit_converter","input":"100 km to miles"}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"file_manager","input":"list ."}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"system_info","input":""}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"text_analyzer","input":"The quick brown fox jumps over the lazy dog"}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"hash_encode","input":"sha256 hello"}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"ip_lookup","input":""}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"note_taker","input":"save Test note #testing"}'

curl -X POST http://localhost:5000/api/tool -H "Content-Type: application/json" \
  -d '{"tool":"document_ocr","input":"status"}'
```

### Layer 10: Swagger UI

Open **http://localhost:5000/docs** — every endpoint listed above is interactive.
Click **"Try it out"** on any endpoint to test directly from the browser.

---

## OpenClaw Comparison & Roadmap

For a full feature-by-feature comparison with [OpenClaw](https://github.com/openclaw/openclaw) (225k★ TypeScript personal AI assistant) and a phased execution plan, see:

📄 **[COMPARISON_OPENCLAW.md](COMPARISON_OPENCLAW.md)**

**Quick summary:** AgentForge covers ~25% of OpenClaw's 67 features across 9 categories. The 5-phase roadmap targets ~55% coverage in ~10 days, focusing on tool expansion (14→24), response streaming, code execution, model failover, and security — while keeping the Python-first, zero-dependency philosophy.
