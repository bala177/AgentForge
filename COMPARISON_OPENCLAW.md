# AgentForge vs OpenClaw — Full Comparison & Execution Plan

> **Date:** February 2026  
> **OpenClaw version reference:** v2026.2.23 (225k GitHub stars, 824 contributors, TypeScript/Node.js)  
> **AgentForge version:** v2.0 (Python/FastAPI, single-developer)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Comparison](#2-architecture-comparison)
3. [Feature-by-Feature Comparison (9 Categories, 62 Features)](#3-feature-by-feature-comparison)
4. [Gap Analysis — What AgentForge Is Missing](#4-gap-analysis)
5. [What AgentForge Does Better / Differently](#5-what-AgentForge-does-better)
6. [Execution Plan — Phased Roadmap](#6-execution-plan)
7. [Phase Details & Implementation Specs](#7-phase-details)
8. [Effort Estimates](#8-effort-estimates)
9. [Success Criteria](#9-success-criteria)

---

## 1. Executive Summary

### What is OpenClaw?

OpenClaw (formerly Clawdbot/Moltbot) is a **personal AI assistant** built in TypeScript/Node.js with:

- A **Gateway WebSocket Control Plane** (single WS server on port 18789)
- **15+ messaging channels** (WhatsApp via Baileys, Telegram via grammY, Slack via Bolt, Discord via discord.js, Signal, iMessage, MS Teams, Matrix, Google Chat, Zalo, WebChat)
- **Pi Agent Runtime** with RPC-mode tool streaming and block streaming
- **Multi-agent routing** — route channels/accounts to isolated agents with per-agent sessions
- **Agent-to-Agent communication** via `sessions_*` tools
- **Skills platform** (bundled, managed, and workspace skills via ClawHub registry)
- **Companion apps** — macOS menu bar, iOS node, Android node
- **Voice Wake + Talk Mode** — always-on speech with ElevenLabs
- **Live Canvas** — agent-driven visual workspace (A2UI)
- **Browser control** — dedicated Chrome/Chromium via CDP
- **Cron + webhooks + Gmail Pub/Sub** automation
- **Docker sandboxing** for non-main sessions
- **Tailscale integration** for secure remote access
- **Model failover** — OAuth rotation, API key fallback, provider switching

### What is AgentForge?

AgentForge is a **Python/FastAPI AI agent platform** with:

- REST API + WebSocket gateway on port 5000
- 14 built-in tools (all self-contained, no API keys)
- ReAct loop (LLM-powered with keyword fallback)
- SQLite-backed persistent memory (conversations, facts, tool cache)
- Multi-user session management with TTL
- 7 channel adapters (WebChat, WhatsApp, Telegram, Slack, Discord, MS Teams, Email)
- Web dashboard (single-page HTML)
- Activity journal + notes store
- Channel configuration UI
- Swagger API docs

### Coverage Score

> **Updated after Tier 2 completion (T2-1 compaction, T2-2 HEARTBEAT, T2-3 schedule_tool, T2-4 streaming)**

| Category             | AgentForge (post-T2) | OpenClaw | Gap      |
| -------------------- | -------------------- | -------- | -------- |
| Gateway & API Layer  | 70%                  | 100%     | 30%      |
| Agent Core / Runtime | 60%                  | 100%     | 40%      |
| Tool System          | 45%                  | 100%     | 55%      |
| Channel Support      | 45%                  | 100%     | 55%      |
| Multi-Agent          | 0%                   | 100%     | 100%     |
| Streaming & UX       | 65%                  | 100%     | 35%      |
| Safety & Security    | 15%                  | 100%     | 85%      |
| Observability & Ops  | 20%                  | 100%     | 80%      |
| Platform / Apps      | 5%                   | 100%     | 95%      |
| **OVERALL**          | **~40%**             | **100%** | **~60%** |

---

## 2. Architecture Comparison

### OpenClaw Architecture

```
Channels (15+)    ───►  Gateway WS Control Plane (port 18789)
                              │
                              ├─ Pi Agent Runtime (RPC mode)
                              │    ├─ Tool streaming
                              │    ├─ Block streaming
                              │    └─ Sandboxed execution (Docker)
                              │
                              ├─ Session Model
                              │    ├─ main session (full access)
                              │    ├─ group sessions (sandboxed)
                              │    └─ multi-agent routing
                              │
                              ├─ Skills Platform (ClawHub)
                              │    ├─ Bundled skills (built-in)
                              │    ├─ Managed skills (auto-installed)
                              │    └─ Workspace skills (user-defined)
                              │
                              ├─ Nodes (macOS/iOS/Android)
                              │    ├─ system.run / system.notify
                              │    ├─ camera / screen recording
                              │    └─ location / canvas
                              │
                              ├─ Automation
                              │    ├─ Cron jobs / wakeups
                              │    ├─ Webhooks (external triggers)
                              │    └─ Gmail Pub/Sub
                              │
                              └─ Apps: macOS menubar, iOS, Android, WebChat, Control UI
```

### AgentForge Architecture (current — post Tier 2)

```
Channels (7)    ───►  FastAPI + Uvicorn (port 5000)
                              │
                              ├─ Agent Runtime
                              │    ├─ ReAct loop (20 steps, AGENT_MAX_STEPS env)  ✅ T1-1
                              │    ├─ SOUL/USER/AGENTS/TOOLS/HEARTBEAT.md         ✅ T1-2
                              │    ├─ Keyword fallback (always works)             ✅ existing
                              │    ├─ Context compaction + MEMORY.md              ✅ T2-1
                              │    └─ Streaming (tool events + token stream)      ✅ T2-4
                              │
                              ├─ Session Manager (in-memory, TTL)
                              │
                              ├─ 25 Built-in Tools (TOOL_REGISTRY)               ✅ T2-3 adds #25
                              │
                              ├─ SQLite Memory (conversations, facts, cache)
                              │
                              ├─ HEARTBEAT Scheduler (daemon, threading.Timer)   ✅ T2-2
                              │    ├─ HEARTBEAT.md tasks (persistent)
                              │    └─ agent_schedule.json (user-managed)
                              │
                              └─ Web Dashboard (streaming-capable UI)            ✅ T2-4
```

### Key Architectural Differences

| Aspect             | AgentForge                        | OpenClaw                                                    |
| ------------------ | --------------------------------- | ----------------------------------------------------------- |
| **Language**       | Python 3.10                       | TypeScript / Node ≥22                                       |
| **Server**         | FastAPI + Uvicorn (HTTP + WS)     | Gateway WS Control Plane                                    |
| **Agent runtime**  | Inline ReAct loop in same process | Pi Agent in RPC mode (separate process)                     |
| **Tool execution** | Synchronous, in-process           | Streamed via RPC, sandboxable                               |
| **Session scope**  | Flat (one session pool)           | Hierarchical (main vs group, multi-agent routing)           |
| **Channel SDK**    | REST webhook adapters (thin)      | Native SDK integrations (Baileys, grammY, Bolt, discord.js) |
| **Configuration**  | Env vars + runtime API            | JSON config file + env vars + CLI + UI                      |
| **Packaging**      | `pip install -r requirements.txt` | `npm install -g openclaw@latest` + daemon                   |
| **Platform**       | Server-only                       | Server + macOS/iOS/Android apps                             |

---

## 3. Feature-by-Feature Comparison

### Category 1: Gateway & API Layer

| #   | Feature                         | OpenClaw                         | AgentForge                    | Status     |
| --- | ------------------------------- | -------------------------------- | ----------------------------- | ---------- |
| 1   | HTTP REST API                   | ✅ CLI + Web API                 | ✅ FastAPI `/api/*`           | ✅ Done    |
| 2   | WebSocket real-time chat        | ✅ Gateway WS                    | ✅ `/ws/chat/{id}`            | ✅ Done    |
| 3   | Swagger / API docs              | ✅ (via tools)                   | ✅ `/docs` (auto-generated)   | ✅ Done    |
| 4   | SSE / log streaming             | ✅ Block streaming               | ✅ `/api/logs/stream`         | ✅ Done    |
| 5   | Webhook router                  | ✅ Per-channel webhooks          | ✅ `/webhook/{channel}`       | ✅ Done    |
| 6   | Control UI (Dashboard)          | ✅ Full web dashboard            | ✅ Web dashboard (index.html) | ✅ Done    |
| 7   | Gateway daemon (background)     | ✅ launchd/systemd user service  | ⚠️ manage.bat/sh only         | 🔶 Partial |
| 8   | Gateway health checks           | ✅ `openclaw doctor`             | ❌ No `/health` endpoint      | ❌ Missing |
| 9   | Gateway lock (single instance)  | ✅ PID-based lock                | ❌ No lock mechanism          | ❌ Missing |
| 10  | Tailscale / remote access       | ✅ Serve/Funnel auto-config      | ❌ Not implemented            | ❌ Missing |
| 11  | Authentication (password/token) | ✅ Password + Tailscale identity | ❌ No auth layer              | ❌ Missing |

### Category 2: Agent Core / Runtime

| #   | Feature                             | OpenClaw                             | AgentForge                                                                 | Status                 |
| --- | ----------------------------------- | ------------------------------------ | -------------------------------------------------------------------------- | ---------------------- |
| 12  | Agent loop (ReAct)                  | ✅ Pi agent w/ RPC streaming         | ✅ 5-step max ReAct loop                                                   | ✅ Done                |
| 13  | Keyword fallback                    | ❌ (relies on LLM)                   | ✅ `run_with_keywords()`                                                   | ✅ Unique              |
| 14  | System prompt + tool injection      | ✅ AGENTS.md + SOUL.md + TOOLS.md    | ✅ Dynamic SYSTEM_PROMPT                                                   | ✅ Done                |
| 15  | Multi-turn conversation             | ✅ Full session context              | ✅ Last 10 messages injected                                               | ✅ Done                |
| 16  | Tool result streaming               | ✅ Tool streaming via RPC            | ✅ Tool events stream via WS                                               | ✅ Done (T2-4)         |
| 17  | Block / chunk streaming             | ✅ Progressive response delivery     | ✅ Token + tool event streaming                                            | ✅ Done (T2-4)         |
| 18  | Planning / task decomposition       | ✅ Agent can plan multi-step         | ⚠️ LLM does ad-hoc planning                                                | 🔶 Partial             |
| 19  | Reflection / self-correction        | ✅ Agent re-evaluates                | ⚠️ Empty-answer nudge only                                                 | 🔶 Partial             |
| 20  | Session context compaction          | ✅ `/compact` command                | ✅ Auto + `/compact` (LLM summary)                                         | ✅ Done (T2-1)         |
| 21  | Thinking levels                     | ✅ off/minimal/low/medium/high/xhigh | ❌ Not implemented                                                         | ❌ Missing             |
| 22  | Chat commands (`/status`, `/reset`) | ✅ Full command set                  | ✅ 7 commands + /compact works                                             | ✅ Done (T1-3/T2-1)    |
| 23  | Autonomous mode (agent-initiated)   | ✅ Cron wakeups, webhooks            | ⚠️ HEARTBEAT + schedule_tool run background tasks; cannot push to channels | ⚠️ Partial (T2-2/T2-3) |

### Category 3: Tool System

| #   | Feature                             | OpenClaw                                                                                                 | AgentForge                               | Status     |
| --- | ----------------------------------- | -------------------------------------------------------------------------------------------------------- | ---------------------------------------- | ---------- |
| 24  | Built-in tools count                | ✅ bash, process, read, write, edit, browser, canvas, nodes, cron, sessions\_\*, discord, slack, gateway | ✅ 25 tools (calculator → schedule_tool) | 🔶 Partial |
| 25  | Browser control (CDP)               | ✅ Dedicated Chrome w/ snapshots                                                                         | ❌ No browser automation                 | ❌ Missing |
| 26  | File system tools (read/write/edit) | ✅ Separate read/write/edit tools                                                                        | ✅ `file_manager` (combined)             | ✅ Done    |
| 27  | Bash / code execution               | ✅ `bash` tool with sandbox                                                                              | ❌ No code execution                     | ❌ Missing |
| 28  | Process management                  | ✅ `process` tool                                                                                        | ❌ Not implemented                       | ❌ Missing |
| 29  | Skills platform (extensible tools)  | ✅ ClawHub registry, install/manage                                                                      | ❌ Hard-coded TOOL_REGISTRY              | ❌ Missing |
| 30  | Tool cache (avoid re-calls)         | ✅ (session-level)                                                                                       | ✅ SQLite tool_cache with TTL            | ✅ Done    |
| 31  | Parallel tool calls                 | ✅ Concurrent execution                                                                                  | ❌ Sequential only                       | ❌ Missing |
| 32  | Tool input validation / schema      | ✅ TypeBox schemas                                                                                       | ❌ String-in/string-out only             | ❌ Missing |
| 33  | Custom user tools                   | ✅ Workspace skills (SKILL.md)                                                                           | ❌ Must edit tools.py source             | ❌ Missing |

### Category 4: Channel Support

| #   | Feature                             | OpenClaw                                 | AgentForge                      | Status                |
| --- | ----------------------------------- | ---------------------------------------- | ------------------------------- | --------------------- |
| 34  | WebChat                             | ✅ WebChat UI + WS                       | ✅ Dashboard + WS               | ✅ Done               |
| 35  | WhatsApp                            | ✅ Baileys (direct device link)          | ✅ Cloud API adapter (webhook)  | ⚠️ Different approach |
| 36  | Telegram                            | ✅ grammY (native bot SDK)               | ✅ Webhook adapter              | 🔶 Partial            |
| 37  | Slack                               | ✅ Bolt (Socket Mode)                    | ✅ Webhook adapter              | 🔶 Partial            |
| 38  | Discord                             | ✅ discord.js (gateway bot)              | ✅ Webhook adapter              | 🔶 Partial            |
| 39  | Microsoft Teams                     | ✅ Extension                             | ✅ Webhook adapter              | 🔶 Partial            |
| 40  | Email                               | ❌ Gmail Pub/Sub (automation only)       | ✅ Inbound parse webhook        | ✅ Done               |
| 41  | Signal                              | ✅ signal-cli                            | ❌ No Signal adapter            | ❌ Missing            |
| 42  | iMessage / BlueBubbles              | ✅ Both legacy + BlueBubbles             | ❌ Not implemented              | ❌ Missing            |
| 43  | Google Chat                         | ✅ Chat API                              | ❌ Not implemented              | ❌ Missing            |
| 44  | Matrix                              | ✅ Extension                             | ❌ Not implemented              | ❌ Missing            |
| 45  | Group message support               | ✅ Mention gating, reply tags, routing   | ❌ No group handling            | ❌ Missing            |
| 46  | DM pairing / access control         | ✅ Pairing codes, allowlists per channel | ❌ No access control            | ❌ Missing            |
| 47  | Channel config UI                   | ✅ Control UI                            | ✅ Channels drawer in dashboard | ✅ Done               |
| 48  | Media handling (images/audio/video) | ✅ Full media pipeline + transcription   | ⚠️ OCR images only              | 🔶 Partial            |

### Category 5: Multi-Agent

| #   | Feature                      | OpenClaw                                                | AgentForge               | Status     |
| --- | ---------------------------- | ------------------------------------------------------- | ------------------------ | ---------- |
| 49  | Multi-agent routing          | ✅ Route channels → isolated agents                     | ❌ Single agent instance | ❌ Missing |
| 50  | Agent-to-Agent communication | ✅ `sessions_send`, `sessions_list`, `sessions_history` | ❌ No multi-agent        | ❌ Missing |
| 51  | Per-agent workspace / prompt | ✅ AGENTS.md per agent                                  | ❌ Single SYSTEM_PROMPT  | ❌ Missing |
| 52  | Sub-agent spawning           | ✅ `sessions_spawn`                                     | ❌ Not implemented       | ❌ Missing |

### Category 6: Streaming & UX

| #   | Feature                        | OpenClaw                        | AgentForge                       | Status     |
| --- | ------------------------------ | ------------------------------- | -------------------------------- | ---------- |
| 53  | Response streaming to channels | ✅ Chunked delivery             | ❌ Full response only            | ❌ Missing |
| 54  | Typing indicators              | ✅ Per-channel typing state     | ⚠️ WebSocket "typing" event only | 🔶 Partial |
| 55  | Presence (online/offline)      | ✅ Full presence system         | ❌ No presence tracking          | ❌ Missing |
| 56  | Usage tracking (tokens/cost)   | ✅ `/usage` per-response footer | ❌ No token counting             | ❌ Missing |

### Category 7: Safety & Security

| #   | Feature                        | OpenClaw                           | AgentForge                    | Status     |
| --- | ------------------------------ | ---------------------------------- | ----------------------------- | ---------- |
| 57  | Docker sandboxing              | ✅ Per-session Docker for non-main | ❌ All runs in host process   | ❌ Missing |
| 58  | Tool allow/deny lists          | ✅ Configurable per session mode   | ❌ All tools always available | ❌ Missing |
| 59  | Request signature verification | ✅ Per-channel (Slack, WhatsApp)   | ⚠️ Stubs in adapters          | 🔶 Partial |
| 60  | Prompt injection resistance    | ✅ DM pairing, sandbox isolation   | ❌ No protections             | ❌ Missing |

### Category 8: Observability & Ops

| #   | Feature            | OpenClaw               | AgentForge                      | Status    |
| --- | ------------------ | ---------------------- | ------------------------------- | --------- |
| 61  | Structured logging | ✅ Full logging        | ✅ Python logging + ring buffer | ✅ Done   |
| 62  | Activity journal   | ❌ (relies on logging) | ✅ Activity store + API         | ✅ Unique |

### Category 9: Platform / Companion Apps

| #   | Feature                | OpenClaw                          | AgentForge         | Status |
| --- | ---------------------- | --------------------------------- | ------------------ | ------ |
| 63  | macOS menu bar app     | ✅ Full companion app             | ❌ Server only     | ❌ N/A |
| 64  | iOS node               | ✅ Canvas, Voice Wake, camera     | ❌ Server only     | ❌ N/A |
| 65  | Android node           | ✅ Canvas, Talk Mode, camera, SMS | ❌ Server only     | ❌ N/A |
| 66  | Voice Wake / Talk Mode | ✅ ElevenLabs integration         | ❌ Not implemented | ❌ N/A |
| 67  | Live Canvas (A2UI)     | ✅ Agent-driven visual workspace  | ❌ Not implemented | ❌ N/A |

---

## 4. Gap Analysis

### Critical Gaps (must have for comparable agent)

| Priority | Gap                       | Impact                                                | Status                                                 |
| -------- | ------------------------- | ----------------------------------------------------- | ------------------------------------------------------ |
| ~~P0~~   | ~~No response streaming~~ | ~~User sees nothing for 5-30s~~                       | ✅ **RESOLVED (T2-4)** — tool events + token streaming |
| **P1**   | 24 tools (growing)        | Good — now leads all competitors. Typed schemas next. | ⚠️ Schemas still string-based (T3-1)                   |
| **P2**   | No code execution sandbox | Agent has `code_runner` but no Docker isolation       | 🔶 Partial — needs sandboxing (T3)                     |
| ~~P3~~   | ~~No slash commands~~     | ~~Basic session hygiene~~                             | ✅ **RESOLVED (T1-3)** — 7 commands, `/compact` works  |
| **P4**   | No tool input schemas     | All tools take a raw string, LLM must guess format    | ❌ Missing — T3-1                                      |
| **P5**   | No model failover         | If Ollama is down, LLM features stop                  | ❌ Missing — Phase 5                                   |
| **P6**   | No health endpoint        | No `/health` or `doctor` command for diagnostics      | ❌ Missing — Phase 5                                   |
| **P7**   | No access control         | Anyone can use any endpoint, no auth                  | ❌ Missing — Phase 5                                   |

### Important Gaps (nice to have for parity)

| Priority | Gap                         | Notes                                                                        |
| -------- | --------------------------- | ---------------------------------------------------------------------------- |
| ~~P8~~   | ~~No context compaction~~   | **✅ RESOLVED (T2-1)** — auto-compact every 20 msgs + MEMORY.md              |
| ~~P9~~   | ~~No cron/scheduled tasks~~ | **✅ RESOLVED (T2-2/T2-3)** — HEARTBEAT.md + schedule_tool #25               |
| **P10**  | No Skills/Plugin system     | Adding tools requires editing Python source code                             |
| **P11**  | Webhook channels are thin   | Use REST webhooks, not native SDKs (less reliable, no persistent connection) |
| **P12**  | No group message handling   | Cannot handle Slack channels, Telegram groups, Discord servers               |
| **P13**  | No parallel tool execution  | Agent runs one tool at a time (slower for multi-tool tasks)                  |
| **P14**  | No Docker sandboxing        | Code execution without sandbox is a security risk                            |

### Out of Scope (won't pursue — different product category)

| Gap                              | Reason                                                      |
| -------------------------------- | ----------------------------------------------------------- |
| macOS/iOS/Android companion apps | Native app development — different stack entirely           |
| Voice Wake / Talk Mode           | Requires ElevenLabs integration + audio pipeline            |
| Live Canvas (A2UI)               | Rich visual workspace — complex UI framework                |
| Tailscale integration            | Network infrastructure — add later when needed              |
| Signal / iMessage / Matrix       | Niche channels — current 7 channels cover primary use cases |
| Agent-to-Agent routing           | Requires multi-agent foundation first                       |

---

## 5. What AgentForge Does Better

| Feature                    | AgentForge Advantage                                     | OpenClaw                                  |
| -------------------------- | -------------------------------------------------------- | ----------------------------------------- |
| **Keyword fallback**       | Always works — no LLM needed                             | Requires LLM always                       |
| **Zero API keys needed**   | All 25 tools work out of box (DuckDuckGo, wttr.in, etc.) | Requires OpenAI/Anthropic API key         |
| **Activity journal**       | Built-in activity tracking with stats, export, delete    | No equivalent                             |
| **Document OCR**           | Built-in image OCR with Tesseract, searchable index      | Relies on external skills                 |
| **SQLite tool cache**      | Automatic caching with TTL to avoid redundant API calls  | No tool-level caching                     |
| **Single-file deployment** | `pip install + python main.py` — under 10 files          | Requires Node.js 22, pnpm, daemon install |
| **Python ecosystem**       | Python ML/DS libraries available directly                | TypeScript — harder to use ML tools       |
| **Swagger auto-docs**      | Full interactive API documentation auto-generated        | CLI-based interaction                     |
| **Management scripts**     | manage.bat/sh for install/start/stop/status/clean        | CLI commands only                         |
| **Email channel**          | Native inbound email webhook adapter                     | Gmail Pub/Sub only (automation, not chat) |

---

## 6. Execution Plan — Phased Roadmap

### Overview: 5 Phases to Close the Gap

```
Phase 1: Tool Expansion (P1)           ──── Foundation ────    ~3 days
Phase 2: Streaming & UX (P0, P3)       ──── Core UX ──────    ~2 days
Phase 3: Code Execution (P2, P14)      ──── Power Tools ───    ~2 days
Phase 4: Agent Intelligence (P4-P5)    ──── Smarter Agent ─    ~2 days
Phase 5: Security & Ops (P6-P7)        ──── Production ────    ~1 day
                                                          Total: ~10 days
```

### Phase Dependency Graph

```
Phase 1 (Tools)
    │
    ├──► Phase 2 (Streaming & UX)  ──► Phase 4 (Intelligence)
    │
    └──► Phase 3 (Code Execution)  ──► Phase 5 (Security & Ops)
```

---

## 7. Phase Details

### Phase 1: Tool Expansion (10 New Tools → 24 Total)

**Goal:** Close the biggest functional gap. Go from 14 to 24 tools.

| #   | New Tool           | Category                   | Dependencies                  | Effort |
| --- | ------------------ | -------------------------- | ----------------------------- | ------ |
| 15  | `json_yaml_tool`   | Data processing            | `pyyaml`                      | 2h     |
| 16  | `csv_data_tool`    | Data processing            | stdlib `csv`                  | 2h     |
| 17  | `pdf_reader`       | Document processing        | `pymupdf`                     | 2h     |
| 18  | `code_runner`      | Code execution (sandboxed) | stdlib `subprocess`           | 3h     |
| 19  | `process_manager`  | System admin               | `psutil`                      | 2h     |
| 20  | `network_diag`     | Network tools              | stdlib `socket`, `subprocess` | 2h     |
| 21  | `password_gen`     | Security                   | stdlib `secrets`              | 1h     |
| 22  | `regex_tool`       | Text processing            | stdlib `re`                   | 1h     |
| 23  | `archive_tool`     | File operations            | stdlib `zipfile`, `tarfile`   | 1h     |
| 24  | `currency_convert` | Finance                    | `requests` (free API)         | 1h     |

**Deliverables:**

- [ ] 10 new tool functions in `runtime/tools.py`
- [ ] Update `TOOL_REGISTRY` (10 new entries)
- [ ] Update `TOOL_META` (10 new entries with icons, examples, categories)
- [ ] Add keyword patterns in `runtime/agent.py` `run_with_keywords()`
- [ ] Update `requirements.txt` (add `pymupdf`, `psutil`, `pyyaml`)
- [ ] Update README tools table (14 → 24)
- [ ] Test all 10 tools via `POST /api/tool`

---

### Phase 2: Streaming & UX Improvements

**Goal:** Stream LLM responses token-by-token. Add chat commands.

#### 2A: Response Streaming (P0)

| Component           | Change                                                                            |
| ------------------- | --------------------------------------------------------------------------------- |
| `llm/provider.py`   | Add `chat_stream()` method yielding tokens from Ollama/OpenAI streaming API       |
| `runtime/agent.py`  | Add `run_with_llm_stream()` that yields `{"type": "token", "text": "..."}` events |
| `gateway/server.py` | WebSocket broadcasts streaming tokens as they arrive                              |
| `gateway/server.py` | Add `POST /api/chat/stream` SSE endpoint for REST clients                         |
| `index.html`        | Update chat UI to append tokens progressively                                     |

**Implementation sketch:**

```python
# llm/provider.py — new method
def chat_stream(self, messages, json_mode=False):
    """Yield tokens one-by-one from the LLM."""
    if self.config.provider == "ollama":
        resp = requests.post(f"{url}/api/chat", json=payload, stream=True)
        for line in resp.iter_lines():
            chunk = json.loads(line)
            yield chunk.get("message", {}).get("content", "")
    elif self.config.provider == "openai":
        payload["stream"] = True
        resp = requests.post(url, headers=headers, json=payload, stream=True)
        for line in resp.iter_lines():
            if line.startswith(b"data: "):
                data = json.loads(line[6:])
                delta = data["choices"][0].get("delta", {})
                yield delta.get("content", "")
```

#### 2B: Chat Commands (P3)

| Command            | Action                                           |
| ------------------ | ------------------------------------------------ |
| `/status`          | Show current model, session length, tool count   |
| `/reset` or `/new` | Clear session context                            |
| `/compact`         | Summarize long conversation into shorter context |
| `/model <name>`    | Switch LLM model at runtime                      |
| `/tools`           | List available tools                             |
| `/help`            | Show available commands                          |

**Implementation:** Pre-process user input in `gateway/server.py` chat handler. If message starts with `/`, route to command handler instead of agent.

---

### Phase 3: Code Execution & Sandbox

**Goal:** Add a safe code execution tool (the most-used tool in OpenClaw is `bash`).

#### 3A: Code Runner Tool (P2)

Already designed as `code_runner` in Phase 1. Key safety features:

- Subprocess with 10-second timeout
- Blocked imports: `os`, `sys`, `subprocess`, `shutil`, `pathlib`, `importlib`
- Blocked builtins: `exec`, `eval`, `compile`, `__import__`, `open`
- Resource limits: max 50 lines output, 10MB memory cap
- Runs in separate Python subprocess (not eval/exec in host)

#### 3B: Docker Sandbox Mode (P14) — Optional

| Component            | Change                                              |
| -------------------- | --------------------------------------------------- |
| `config.py`          | Add `SANDBOX_MODE` setting (none/subprocess/docker) |
| `runtime/sandbox.py` | New file: Docker execution wrapper                  |
| `Dockerfile.sandbox` | Minimal Python image for code execution             |

**Note:** Docker sandbox is an advanced feature. The subprocess approach in 3A is sufficient for most use cases. Docker adds complexity with minimal benefit for a single-user assistant.

---

### Phase 4: Agent Intelligence

**Goal:** Make the ReAct loop smarter with structured tool schemas and model failover.

#### 4A: Structured Tool Parameters (P4)

Replace string-in/string-out with typed parameters:

```python
# Current (fragile):
TOOL_REGISTRY = {
    "weather_lookup": {
        "function": weather_lookup,
        "description": "Get weather for a city",
    }
}

# New (structured):
TOOL_REGISTRY = {
    "weather_lookup": {
        "function": weather_lookup,
        "description": "Get weather for a city",
        "parameters": {
            "city": {"type": "string", "required": True, "description": "City name"},
            "units": {"type": "string", "enum": ["celsius", "fahrenheit"], "default": "celsius"},
        },
        "returns": "Weather data as formatted text",
    }
}
```

- System prompt generates parameter docs from schema
- Default input parsing: `tool_input` → try JSON dict → fallback to string
- Backward compatible: old tools still accept raw string

#### 4B: Model Failover (P5)

```python
# llm/provider.py — new failover logic
@dataclass
class LLMConfig:
    provider: str = "ollama"
    model: str = ""
    fallback_providers: list = field(default_factory=lambda: ["keyword"])

    # New: ordered model preferences
    model_preferences: list = field(default_factory=list)
    # e.g. ["llama3:latest", "llama3.1:latest", "mistral:latest"]
```

- Try primary model → on failure → try next in `model_preferences` → fallback to `keyword`
- Auto-detect available models on startup
- Log failover events to activity journal

#### 4C: Context Compaction (P8)

```python
# runtime/agent.py — new method
def compact_session(self, session_id: str) -> str:
    """Summarize conversation history into a shorter context."""
    history = self.memory_store.get_conversation(session_id, limit=100)
    if len(history) < 20:
        return "Session is already compact."

    summary_prompt = "Summarize this conversation into key points..."
    summary = self.llm.chat([
        {"role": "system", "content": summary_prompt},
        {"role": "user", "content": format_history(history)},
    ])

    self.memory_store.clear_conversation(session_id)
    self.memory_store.add_message(session_id, "system", f"[Context summary]: {summary}")
    return summary
```

---

### Phase 5: Security & Operations

**Goal:** Add health checks, basic auth, and operational improvements.

#### 5A: Health Endpoint (P6)

```python
@app.get("/health")
async def health():
    """Health check endpoint for monitoring."""
    checks = {
        "server": "ok",
        "llm": await check_llm_health(),
        "memory": check_memory_health(),
        "tools": len(TOOL_REGISTRY),
        "sessions": session_manager.count(),
        "uptime": time.time() - START_TIME,
    }
    status = "healthy" if all(v != "error" for v in checks.values() if isinstance(v, str)) else "degraded"
    return {"status": status, **checks}
```

#### 5B: Basic Auth (P7)

```python
# config.py
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")  # Empty = no auth

# gateway/server.py — middleware
@app.middleware("http")
async def auth_middleware(request, call_next):
    if not API_AUTH_TOKEN:
        return await call_next(request)
    if request.url.path in ("/health", "/docs", "/openapi.json", "/"):
        return await call_next(request)
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != API_AUTH_TOKEN:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)
```

#### 5C: Token Usage Tracking (P56)

```python
# Track tokens per request
@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""

# Return with every chat response:
{"answer": "...", "usage": {"prompt_tokens": 145, "completion_tokens": 89, "total_tokens": 234}}
```

---

## 8. Effort Estimates

| Phase       | Features                             | Effort       | Files Modified                                  | New Files             |
| ----------- | ------------------------------------ | ------------ | ----------------------------------------------- | --------------------- |
| **Phase 1** | 10 new tools                         | 3 days       | tools.py, agent.py, requirements.txt, README.md | None                  |
| **Phase 2** | Streaming + chat commands            | 2 days       | provider.py, agent.py, server.py, index.html    | None                  |
| **Phase 3** | Code runner (sandbox)                | 2 days       | tools.py                                        | sandbox.py (optional) |
| **Phase 4** | Tool schemas + failover + compaction | 2 days       | tools.py, provider.py, agent.py                 | None                  |
| **Phase 5** | Health + auth + usage tracking       | 1 day        | server.py, config.py, provider.py               | None                  |
| **Total**   |                                      | **~10 days** |                                                 |                       |

### Post-Phase Coverage Estimate

| Category       | Before   | After Phase 1 | After Phase 2 | After Phase 3 | After Phase 4 | After Phase 5 |
| -------------- | -------- | ------------- | ------------- | ------------- | ------------- | ------------- |
| Gateway & API  | 70%      | 70%           | 75%           | 75%           | 75%           | 85%           |
| Agent Core     | 30%      | 30%           | 55%           | 55%           | 70%           | 70%           |
| Tool System    | 25%      | 55%           | 55%           | 65%           | 75%           | 75%           |
| Channels       | 45%      | 45%           | 45%           | 45%           | 45%           | 45%           |
| Multi-Agent    | 0%       | 0%            | 0%            | 0%            | 0%            | 0%            |
| Streaming & UX | 15%      | 15%           | 65%           | 65%           | 65%           | 75%           |
| Safety         | 10%      | 10%           | 10%           | 30%           | 30%           | 55%           |
| Observability  | 20%      | 20%           | 20%           | 20%           | 20%           | 40%           |
| **OVERALL**    | **~25%** | **~30%**      | **~40%**      | **~45%**      | **~50%**      | **~55%**      |

> **Reality check:** Reaching 100% parity with OpenClaw is unrealistic and unnecessary. OpenClaw has 824 contributors, 3 months of public development, and native app teams. Reaching **55%** functional coverage makes AgentForge a **credible, self-contained AI agent** — the missing 45% is mostly multi-agent, native apps, and advanced streaming that a single-user Python agent doesn't need.

---

## 9. Success Criteria

### Phase 1 Complete When: ✅ ALL DONE

- [x] All 10 new tools pass `POST /api/tool` tests
- [x] LLM correctly routes queries to new tools (e.g., "convert this JSON to YAML" → `json_yaml_tool`)
- [x] `GET /api/tools` returns 24 tools (now 25 with schedule_tool from T2-3)
- [x] Dashboard tool cards show all tools
- [x] README updated

### Phase 2 Complete When: ✅ MOSTLY DONE (see T2-4)

- [x] WebSocket chat shows tokens appearing character-by-character (T2-4)
- [ ] SSE endpoint `/api/chat/stream` delivers streamed responses (REST remains sync; WS done)
- [x] `/status` returns model name and session info (T1-3)
- [x] `/reset` clears session and confirms (T1-3)
- [x] `/compact` summarizes and compacts long conversation (T2-1)

### Phase 3 Complete When:

- [ ] `code_runner` executes safe Python code and returns output
- [ ] Blocked imports raise clear error messages
- [ ] 10-second timeout kills runaway code
- [ ] Code execution works via both REST and WebSocket

### Phase 4 Complete When:

- [ ] System prompt includes parameter descriptions for structured tools
- [ ] LLM sends structured params for weather, calculator, etc.
- [ ] Model failover automatically tries backup models
- [ ] `/compact` summarizes conversations longer than 20 messages

### Phase 5 Complete When:

- [ ] `GET /health` returns server + LLM + memory status
- [ ] Setting `API_AUTH_TOKEN` blocks unauthenticated requests
- [ ] Chat responses include token usage stats when LLM is active
- [ ] README documents all new security features

---

## Appendix: Files Modified Per Phase

```
Phase 1:  runtime/tools.py, runtime/agent.py, requirements.txt, README.md
Phase 2:  llm/provider.py, runtime/agent.py, gateway/server.py, gateway/templates/index.html
Phase 3:  runtime/tools.py, (optional: runtime/sandbox.py, Dockerfile.sandbox)
Phase 4:  runtime/tools.py, llm/provider.py, runtime/agent.py
Phase 5:  gateway/server.py, config.py, llm/provider.py
```

---

_This document is the living comparison and roadmap for bringing AgentForge closer to OpenClaw's feature set while maintaining its Python-first, zero-dependency, single-developer philosophy._
