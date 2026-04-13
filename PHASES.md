# AgentForge — Development Phases

> **Last updated:** April 13, 2026
> **Overall progress:** ~65% feature coverage vs all competitors
> **Next task:** T3-4A — TF-IDF semantic memory retrieval

---

## Phase Map

```
Phase 0  Pre-plan     ✅  Tool expansion, bug fixes, UI enhancements
Tier 1   Week 1       ✅  Security, configurability, personality, session control
Tier 2   Week 2       ✅  Streaming, compaction, background autonomy
Tier 3   Week 3+      🔄  Intelligence, extensibility, semantic memory  ← HERE
Phase 5  Week 4+      ⬜  Production hardening: auth, health, token tracking
```

---

## Phase 0 — Foundation (Pre-plan) ✅ COMPLETE

> Baseline work done before the formal implementation plan was written.

| Item | What | Status |
|------|------|--------|
| Tool expansion | 14 → 25 tools added to `TOOL_REGISTRY` | ✅ |
| Bug fix | Unicode startup crash (cp1252 encoding) | ✅ |
| Bug fix | `KeyError: 'json'` in `SYSTEM_PROMPT` formatting | ✅ |
| Bug fix | WebSocket infinite reconnect loop | ✅ |
| Chat UI | Filter bar, tool color coding, citation badges | ✅ |
| Research | Studied Nanobot, OpenClaw, NanoClaw, memU, SuperAGI, AnythingLLM, Claude Code | ✅ |

**Outcome:** Working agent with 25 tools, stable WebSocket, good UI baseline.

---

## Tier 1 — Quick Wins (Week 1) ✅ COMPLETE

> No new dependencies. Self-contained improvements. All tested.

| ID | What | Files | Status |
|----|------|-------|--------|
| **T1-1** | Raise `max_steps` 5 → 20 via `AGENT_MAX_STEPS` env var | `runtime/agent.py` | ✅ |
| **T1-2** | Externalize agent personality into 5 editable `.md` files | `runtime/agent.py` + 5 new `runtime/*.md` | ✅ |
| **T1-3** | Slash commands: `/new /help /tools /model /status /memory /compact` | `gateway/server.py` | ✅ |
| **T1-4** | Path traversal security guard — `_safe_path()` + `WORKSPACE_ROOT` | `runtime/tools.py` | ✅ |

**Outcome:** Secure, configurable, personality-driven agent with full session control.

**Key personality files created:**

| File | Purpose |
|------|---------|
| `runtime/SOUL.md` | Agent personality, tone, communication style |
| `runtime/USER.md` | User profile — agent can self-update this via `file_manager` |
| `runtime/AGENTS.md` | Hard rules the agent must never break |
| `runtime/TOOLS.md` | Tool usage hints injected after the tool list |
| `runtime/HEARTBEAT.md` | Scheduled background task definitions |

---

## Tier 2 — Core Upgrades (Week 2) ✅ COMPLETE

> Production-grade agent behaviour. Made the agent proactive and visible.

| ID | What | Files | Status |
|----|------|-------|--------|
| **T2-1** | Context compaction + `MEMORY.md` self-write (auto at 20 msgs or `/compact`) | `runtime/memory.py`, `runtime/agent.py`, `gateway/server.py` | ✅ |
| **T2-2** | HEARTBEAT.md background scheduler — `threading.Timer` daemon loop every 30 min | `runtime/agent.py` | ✅ |
| **T2-3** | `schedule_tool` (#25) — agent-managed cron tasks stored in `agent_schedule.json` | `runtime/tools.py`, `gateway/server.py` | ✅ |
| **T2-4** | LLM token streaming over WebSocket — thinking/tool/token/done event types | `llm/provider.py`, `runtime/agent.py`, `gateway/server.py`, `index.html` | ✅ |

**Outcome:** Agent streams replies in real-time, auto-compacts memory, and runs scheduled tasks autonomously in the background without any user input.

**Schedule formats supported by T2-2/T2-3:**
- `every 30m` / `every 2h` — recurring interval
- `daily HH:MM` — fires once per day at that time
- `weekly DAY HH:MM` — fires once per week (e.g. `weekly Monday 08:00`)

---

## Tier 3 — Intelligence & Extensibility (Week 3+) 🔄 IN PROGRESS

> Multi-day efforts. New architecture pieces. Implement after Tier 2 is stable.

| ID | What | Files | Status | Priority |
|----|------|-------|--------|----------|
| **T3-1** | Typed tool schemas — `params` schema + `params_to_str` on all 25 tools | `runtime/tools.py`, `runtime/agent.py` | ✅ DONE | Foundation |
| **T3-4A** | TF-IDF semantic memory retrieval (scikit-learn, no new deps) | `runtime/memory.py` | ⬜ Next | High |
| **T3-2** | Skill/plugin system — `skills/` directory + `/install <skill>` command | `runtime/tools.py`, `gateway/server.py` | ⬜ | High |
| **T3-3** | MCP client — external tool servers via `MCP_SERVERS` env var | `runtime/mcp_client.py` (new) | ⬜ | Medium |
| **T3-4B** | ChromaDB vector memory — semantic search with embeddings | `runtime/memory.py` | ⬜ | Medium |

### T3-1 — Typed Tool Schemas ✅ (2026-04-13)

**What changed:**
- Every tool in `TOOL_REGISTRY` now has a `"params"` schema dict and `"params_to_str"` bridge callable
- `_build_tool_list()` auto-generates typed signatures: `weather_lookup(city)`, `file_manager(action, path, content?)`
- `SYSTEM_PROMPT` now shows typed params as the preferred call format
- `_resolve_tool_input()` handles both new typed `params` dicts and old legacy `input` strings (fully backward compatible)

**Before T3-1 — LLM sent:**
```json
{"action": "tool_call", "tool": "weather_lookup", "input": "Paris"}
```

**After T3-1 — LLM sends:**
```json
{"action": "tool_call", "tool": "weather_lookup", "params": {"city": "Paris"}, "thought": "Need current weather"}
```

**Dispatch bridge (no tool function changes required):**
```
params_to_str({"city": "Paris"}) → "Paris" → weather_lookup("Paris")
```

---

### T3-4A — TF-IDF Memory Retrieval ⬜ NEXT

**Problem:** SQLite `LIKE` search is substring-only. "user prefers Python" won't find "likes Python development."
**Fix:** Add `retrieve_relevant_facts(query, session_id)` using `sklearn.TfidfVectorizer` + cosine similarity.
**No new deps** — scikit-learn is already available.
**Expected accuracy improvement:** ~60% (substring) → ~80%+ (semantic TF-IDF).

---

### T3-2 — Skills / Plugin System ⬜

**What it enables:** Drop a `skill.py` + `SKILL.md` into `skills/` → new tools auto-register at startup. `/install <name>` slash command to load on demand.

**Directory structure:**
```
skills/
  weather-pro/
    SKILL.md     ← YAML frontmatter: name, description, version, tools[]
    skill.py     ← exports TOOLS = {"tool_name": function}
  git-helper/
    SKILL.md
    skill.py
```

---

### T3-3 — MCP Client ⬜

**What it enables:** Set `MCP_SERVERS=http://localhost:3001` → all tools from that MCP server automatically appear in the agent's tool list at startup.
**New file:** `runtime/mcp_client.py`

---

### T3-4B — ChromaDB Vector Memory ⬜

**Requires:** `pip install chromadb` (pure Python, no Docker)
**What it enables:** Semantic embedding search over stored facts — surpasses TF-IDF for long-tail queries.
**Only implement if T3-4A proves insufficient at scale.**

---

## Phase 5 — Production Hardening (Week 4+) ⬜ TODO

> ~1 day of work. Required for any deployment beyond localhost.

| Item | What | File |
|------|------|------|
| `/health` endpoint | Returns model, tool count, uptime, memory db status | `gateway/server.py` |
| `API_AUTH_TOKEN` middleware | Bearer token auth on all `/api/*` and `/ws/*` routes | `gateway/server.py`, `config.py` |
| Token usage tracking | Per-request and per-session token counts in responses | `runtime/agent.py`, `llm/provider.py` |
| Model failover | Auto-rotate providers if primary LLM is down | `llm/provider.py` |

---

## Coverage Score by Phase

| Phase | Before | After | vs OpenClaw | vs Nanobot | vs NanoClaw |
|-------|--------|-------|-------------|------------|-------------|
| Phase 0 (baseline) | — | ~35% | 100% | 85% | 70% |
| After Tier 1 | 35% | ~50% | 100% | 85% | 70% |
| After Tier 2 | 50% | ~62% | 100% | 85% | 70% |
| After T3-1 | 62% | ~65% | 100% | 85% | 70% |
| After full Tier 3 | 65% | ~77% | 100% | **58%** | **51%** |
| After Phase 5 | 77% | ~82% | 100% | 58% | 51% |

> After Tier 3: AgentForge at ~77% **surpasses Nanobot (~58%) and NanoClaw (~51%)** overall.

---

## Unique Advantages — What No Competitor Has

| Feature | Detail |
|---------|--------|
| Zero API key mode | All 25 tools work with Ollama — no external keys needed |
| LLM-free keyword fallback | Always answers even without any LLM running |
| Tool result cache with TTL | SQLite cache avoids redundant API calls |
| Activity journal + stats | Timestamped log with export and category filtering |
| Log streaming (SSE) | `/api/logs/stream` Server-Sent Events endpoint |
| Chat filter bar | Color-coded tool citations, filter chips per category |
| Full web dashboard (SPA) | Feature-complete with channels config UI |
| Swagger API docs | `/docs` — full interactive API documentation |
| Management scripts | `manage.sh/.bat` start/stop/restart/status/logs |
| MS Teams channel | Native webhook adapter |
| Email inbound channel | Inbound parse webhook for chat via email |
| OCR + searchable index | Tesseract OCR with `ocr_index.json` persistent index |
| Single-file install | `pip install -r requirements.txt && python main.py` |

---

## File Change Map

```
Phase 0:   runtime/tools.py (tool additions), gateway/templates/index.html (UI)

Tier 1:    runtime/agent.py      — max_steps, _load_md(), _system_prompt()
           runtime/tools.py      — _safe_path(), WORKSPACE_ROOT
           gateway/server.py     — _handle_slash_command(), uptime tracking
           NEW: runtime/SOUL.md, USER.md, AGENTS.md, TOOLS.md, HEARTBEAT.md

Tier 2:    runtime/memory.py     — consolidate(), count_messages(), trim_to_last_n()
           runtime/agent.py      — consolidate_session(), _maybe_consolidate(),
                                   _parse_heartbeat_md(), _start_heartbeat(),
                                   run_with_llm_streaming(), run_streaming()
           runtime/tools.py      — schedule_tool(), _load_schedule(), _save_schedule()
           llm/provider.py       — chat_stream(), _stream_ollama(), _stream_openai()
           gateway/server.py     — WebSocket streaming queue bridge, /compact fix
           gateway/templates/    — streaming bubble, token accumulation
           AUTO: runtime/MEMORY.md (written by agent during compaction)
           AUTO: runtime/heartbeat_state.json (scheduler state)
           AUTO: runtime/agent_schedule.json (user-defined tasks)

Tier 3:    runtime/tools.py      — params + params_to_str on all 25 tools  [T3-1 ✅]
           runtime/agent.py      — _resolve_tool_input(), _build_tool_list(),
                                   SYSTEM_PROMPT typed format               [T3-1 ✅]
           runtime/memory.py     — retrieve_relevant_facts() TF-IDF        [T3-4A ⬜]
           runtime/tools.py      — _load_skills() skill autoloader          [T3-2 ⬜]
           gateway/server.py     — /install slash command                   [T3-2 ⬜]
           NEW: runtime/mcp_client.py                                       [T3-3 ⬜]
           NEW: skills/ directory                                            [T3-2 ⬜]
           DEPS: scikit-learn (T3-4A), chromadb (T3-4B)

Phase 5:   gateway/server.py     — /health endpoint, auth middleware
           config.py             — API_AUTH_TOKEN setting
           llm/provider.py       — token tracking, model failover
```

---

## Quick Reference — What to Do Next

```
1.  T3-4A  TF-IDF retrieval    runtime/memory.py       ~1 day   no new deps
2.  T3-2   Skills system        runtime/tools.py +      ~1 day   no new deps
                                gateway/server.py
3.  Phase 5 /health + auth      gateway/server.py       ~1 day   no new deps
4.  T3-3   MCP client           runtime/mcp_client.py   ~1 day   pip install httpx
5.  T3-4B  ChromaDB memory      runtime/memory.py       ~2 days  pip install chromadb
```
