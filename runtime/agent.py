"""
agent.py — The AI Agent core (LLM-powered with keyword fallback).

Architecture:
  • ReAct loop:  Reason → Act → Observe → repeat
  • The LLM decides WHICH tool to call and extracts the parameters
  • If no LLM is available, falls back to keyword matching (always works)
  • Supports Ollama (local) and OpenAI (cloud)

The agent sends a system prompt listing all tools with descriptions.
The LLM responds with structured JSON:
  {"action": "tool_call", "tool": "...", "input": "..."}
  {"action": "answer",    "text": "..."}
"""

import json
import os
import re
import time
import datetime
import threading
from pathlib import Path
from runtime.tools import TOOL_REGISTRY
from runtime.memory import MemoryStore
from llm.provider import LLMProvider, LLMConfig
from log_config import get_logger

log = get_logger("agent")


# ── System prompt template ────────────────────────────────────────────
SYSTEM_PROMPT = """You are a helpful AI assistant with access to real-world tools.
You must respond ONLY with valid JSON — no extra text, no markdown.

CRITICAL RULES:
- You MUST call a tool whenever the question involves real-world data (weather, search, time, IP, etc.)
- You MUST use the calculator tool for ANY math calculation — do NOT compute math yourself, you make errors.
- NEVER fabricate, guess, or hallucinate data. If a tool exists for it, CALL THE TOOL.
- You do NOT have real-time knowledge. Use tools to get current information.
- Only use "answer" when no tool is relevant (e.g. explaining a concept, greetings, opinions).

Available tools (signature shows required and optional? params):
{tool_list}

RESPOND WITH EXACTLY ONE OF THESE JSON FORMATS:

1) Call a tool — PREFERRED, use typed params:
{{"action": "tool_call", "tool": "<name>", "params": {{"<param>": "<value>"}}, "thought": "<why>"}}

2) Call a tool — also accepted, free-text input:
{{"action": "tool_call", "tool": "<name>", "input": "<string>", "thought": "<why>"}}

3) Final answer — only after tool results, or when no tool is needed:
{{"action": "answer", "text": "<your answer>", "thought": "<reasoning>"}}

Typed params examples:
  {{"action": "tool_call", "tool": "weather_lookup", "params": {{"city": "Tokyo"}}, "thought": "Need current weather"}}
  {{"action": "tool_call", "tool": "web_search", "params": {{"query": "python async tutorial"}}, "thought": "Need web results"}}
  {{"action": "tool_call", "tool": "calculator", "params": {{"expression": "sqrt(144) + factorial(5)"}}, "thought": "Need math result"}}
  {{"action": "tool_call", "tool": "file_manager", "params": {{"action": "read", "path": "notes.txt"}}, "thought": "Read a file"}}
  {{"action": "tool_call", "tool": "note_taker", "params": {{"action": "save", "text": "buy milk"}}, "thought": "Save a note"}}
  {{"action": "answer", "text": "Hello! How can I help?", "thought": "Greeting, no tool needed"}}

ALWAYS respond with valid JSON. Nothing else."""


# Path for heartbeat scheduler state (persisted across restarts)
_HEARTBEAT_STATE_FILE = Path(__file__).parent / "heartbeat_state.json"


FOLLOW_UP_PROMPT = """Tool "{tool}" returned this result:

{result}

Now synthesize a clear, helpful answer for the user based on this tool result.
Respond ONLY with JSON:
{{"action": "answer", "text": "<your synthesized answer based on the tool result above>", "thought": "<brief reasoning>"}}

Remember: base your answer ONLY on the tool result above. Do not make up additional data."""


class AgentForge:
    """AI Agent with LLM-powered reasoning and keyword fallback."""

    def __init__(self, name: str = "Agent"):
        self.name = name
        self.tools = TOOL_REGISTRY
        self.memory: list[dict] = []          # legacy in-memory per-request
        self.memory_store = MemoryStore()      # persistent SQLite memory
        self.max_steps = int(os.getenv("AGENT_MAX_STEPS", "20"))
        self.llm_config = LLMConfig()
        self.llm = LLMProvider(self.llm_config)
        self._session_id: str | None = None   # set per-request by gateway
        self._start_heartbeat()               # T2-2: background HEARTBEAT scheduler

    @property
    def use_llm(self) -> bool:
        """Check if LLM mode is active (not keyword mode)."""
        return self.llm_config.provider != "keyword"

    # ------------------------------------------------------------------
    # Build the tool list for the system prompt (T3-1: typed signatures)
    # ------------------------------------------------------------------
    def _build_tool_list(self) -> str:
        lines = []
        for name, info in self.tools.items():
            params = info.get("params", {})
            if params:
                sig = ", ".join(params.keys())
                lines.append(f"  - {name}({sig}): {info['description']}")
            else:
                lines.append(f"  - {name}(): {info['description']}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # T3-1: Resolve tool input — typed params dict OR legacy string
    # ------------------------------------------------------------------
    def _resolve_tool_input(self, tool_name: str, parsed: dict) -> str:
        """Convert typed params (preferred) or legacy 'input' string to the
        string the tool function expects.

        Priority:
          1. parsed["params"] dict  → call tool's params_to_str()
          2. parsed["input"] string → use directly (backward compat)
          3. empty string           → fallback
        """
        params = parsed.get("params")
        if params and isinstance(params, dict):
            tool_info = self.tools.get(tool_name, {})
            params_to_str = tool_info.get("params_to_str")
            if callable(params_to_str):
                try:
                    result = params_to_str(params)
                    log.debug("T3-1 typed dispatch: %s(%s) → %r", tool_name, params, result)
                    return result
                except Exception as exc:
                    log.warning("params_to_str failed for %s: %s — falling back to join", tool_name, exc)
            # Generic fallback: join all non-empty values with spaces
            return " ".join(str(v) for v in params.values() if v is not None and str(v).strip())
        return parsed.get("input", "")

    # ------------------------------------------------------------------
    # Load personality / config markdown files
    # ------------------------------------------------------------------
    @staticmethod
    def _load_md(filename: str) -> str:
        """Load a markdown file from the runtime/ directory. Returns '' if missing."""
        path = Path(__file__).parent / filename
        try:
            return path.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError):
            return ""

    def _system_prompt(self) -> str:
        """Build full system prompt with personality files injected."""
        soul        = self._load_md("SOUL.md")
        user        = self._load_md("USER.md")
        rules       = self._load_md("AGENTS.md")
        tools_hints = self._load_md("TOOLS.md")
        memory_log  = self._load_md("MEMORY.md")  # T2-1: compacted session summaries
        base  = SYSTEM_PROMPT.replace("{tool_list}", self._build_tool_list())
        parts = []
        if soul:
            parts.append(f"## Agent Personality\n{soul}")
        if rules:
            parts.append(f"## Agent Rules\n{rules}")
        if user:
            parts.append(f"## User Profile\n{user}")
        if memory_log:
            parts.append(f"## Agent Memory Log (past conversation summaries)\n{memory_log}")
        parts.append(base)
        if tools_hints:
            parts.append(f"## Tool Usage Hints\n{tools_hints}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Parse LLM JSON response (with fallback for malformed output)
    # ------------------------------------------------------------------
    def _parse_llm_response(self, raw: str) -> dict:
        """Parse the LLM's JSON response, handling common issues."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in the response
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Give up — return as a direct answer
        return {"action": "answer", "text": cleaned}

    # ------------------------------------------------------------------
    # LLM-POWERED AGENT LOOP
    # ------------------------------------------------------------------
    def run_with_llm(self, user_input: str) -> dict:
        """
        Full ReAct loop using the LLM.
        Returns {"answer": str, "steps": list[dict], "plan": list[str]}
        """
        log.info("="*50)
        log.info("%s [LLM: %s] received: \"%s\"", self.name, self.llm_config.model, user_input)
        log.info("="*50)

        # Build system prompt — inject relevant facts (T3-4A: TF-IDF ranked, falls back to all)
        sys_content = self._system_prompt()
        relevant_facts = self.memory_store.retrieve_relevant_facts(
            user_input, session_id=self._session_id, top_n=8
        )
        if relevant_facts:
            lines = ["Relevant facts about the user/context:"]
            for f in relevant_facts:
                lines.append(f"  - {f.key}: {f.value}")
            sys_content += "\n\n" + "\n".join(lines)
        elif not relevant_facts:
            # Fallback: inject all facts if TF-IDF returned nothing
            facts_ctx = self.memory_store.all_facts_as_context(limit=20)
            if facts_ctx:
                sys_content += "\n\n" + facts_ctx

        messages = [
            {"role": "system", "content": sys_content},
        ]

        # Inject recent conversation history for multi-turn context
        if self._session_id:
            history = self.memory_store.get_conversation(self._session_id, limit=10)
            for msg in history:
                if msg.role in ("user", "assistant"):
                    messages.append({"role": msg.role, "content": msg.content})

        # Current user message
        messages.append({"role": "user", "content": user_input})

        steps_log = []
        plan = []

        for step_num in range(1, self.max_steps + 1):
            log.info("--- LLM Step %d/%d ---", step_num, self.max_steps)

            # Ask the LLM
            try:
                raw_response = self.llm.chat(messages, json_mode=True)
            except Exception as e:
                error_msg = f"LLM error: {e}"
                log.error("%s", error_msg)
                log.warning("Switching to keyword matching for this query")
                return self.run_with_keywords(user_input)

            log.debug("LLM raw response: %s", raw_response[:300])
            parsed = self._parse_llm_response(raw_response)

            action = parsed.get("action", "answer")
            thought = parsed.get("thought", "")

            # Normalize action — some LLMs use the tool name as action
            tool_name_from_action = None
            if action not in ("tool_call", "answer"):
                # Check if "action" is actually a tool name
                if action in self.tools:
                    tool_name_from_action = action
                    action = "tool_call"
                elif parsed.get("tool") and parsed["tool"] in self.tools:
                    action = "tool_call"
                else:
                    # Treat unknown actions as answer
                    action = "answer"
                    if not parsed.get("text"):
                        parsed["text"] = raw_response

            if thought:
                log.info("THINK: %s", thought)

            # ── Direct answer ──
            if action == "answer":
                answer_text = parsed.get("text", raw_response)

                # Validate: if empty/useless answer on step 1, nudge LLM to use tools
                if step_num == 1 and len(answer_text.strip()) < 3:
                    log.warning("LLM returned empty answer on step 1 — nudging to use tools")
                    messages.append({"role": "assistant", "content": raw_response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your answer was empty. You have tools available. "
                            "Please use a tool to help answer the question. "
                            "For time/date questions use get_datetime, for weather use weather_lookup, etc. "
                            "Respond with JSON: {\"action\": \"tool_call\", \"tool\": \"<name>\", \"input\": \"<input>\"}"
                        ),
                    })
                    continue

                log.info("ANSWER: %s", answer_text[:300])

                steps_log.append({
                    "step": thought or "Final answer",
                    "tool": None,
                    "input": "",
                    "result": answer_text,
                })

                return {
                    "answer": answer_text,
                    "steps": steps_log,
                    "plan": plan or [thought or "Direct answer"],
                    "mode": "llm",
                    "model": self.llm_config.model,
                }

            # ── Tool call ──
            if action == "tool_call":
                tool_name = tool_name_from_action or parsed.get("tool", "")
                tool_input = self._resolve_tool_input(tool_name, parsed)  # T3-1
                plan.append(f"Call {tool_name}: {tool_input}")

                log.info("TOOL CALL: %s(\"%s\")", tool_name, tool_input)

                if tool_name not in self.tools:
                    result = f"Error: Unknown tool '{tool_name}'. Available: {', '.join(self.tools.keys())}"
                    log.error("%s", result)
                else:
                    # Check tool cache first
                    cached = self.memory_store.get_cached_result(tool_name, tool_input)
                    if cached:
                        result = cached
                        log.info("CACHE HIT (%s): %s", tool_name, result[:300])
                    else:
                        try:
                            result = self.tools[tool_name]["function"](tool_input)
                        except Exception as e:
                            result = f"Tool error: {e}"
                            log.exception("Tool %s raised an exception", tool_name)
                        log.info("TOOL RESULT (%s): %s", tool_name, result[:300])
                        # Cache the result (5 min TTL for most tools)
                        ttl = 60 if tool_name == "get_datetime" else 300
                        self.memory_store.cache_tool_result(tool_name, tool_input, result, ttl=ttl)

                # Save to memory
                self.memory.append({
                    "step": thought or f"Call {tool_name}",
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result,
                })

                steps_log.append({
                    "step": thought or f"Use {tool_name}",
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result,
                })

                # Send the tool result back to the LLM for synthesis
                messages.append({"role": "assistant", "content": raw_response})
                messages.append({
                    "role": "user",
                    "content": FOLLOW_UP_PROMPT.replace("{tool}", tool_name).replace("{result}", result),
                })
                continue

        # Max steps reached
        log.warning("Max steps (%d) reached without final answer", self.max_steps)
        final = "\n".join(s["result"] for s in steps_log) or (
            f"[Agent reached {self.max_steps}-step limit. "
            f"Set AGENT_MAX_STEPS env to increase. Last partial results above.]"
        )
        return {
            "answer": final,
            "steps": steps_log,
            "plan": plan,
            "mode": "llm",
            "model": self.llm_config.model,
        }

    # ------------------------------------------------------------------
    # KEYWORD-BASED AGENT LOOP (original fallback)
    # ------------------------------------------------------------------
    def run_with_keywords(self, user_input: str) -> dict:
        """
        Original keyword-matching agent loop.
        Returns {"answer": str, "steps": list[dict], "plan": list[str]}
        """
        log.info("="*50)
        log.info("%s [KEYWORD] received: \"%s\"", self.name, user_input)
        log.info("="*50)

        plan = self._plan_keywords(user_input)
        log.info("PLAN: %d step(s): %s", len(plan), plan)

        steps_log = []
        for i, step in enumerate(plan[:self.max_steps], 1):
            log.info("--- Keyword Step %d/%d ---", i, len(plan))

            tool_name, tool_input = self._think_keywords(step)

            if tool_name is None:
                log.info("Direct answer: %s", tool_input[:200])
                steps_log.append({"step": step, "tool": None, "input": "", "result": tool_input})
                continue

            log.info("TOOL CALL: %s(\"%s\")", tool_name, tool_input)
            result = self.tools[tool_name]["function"](tool_input) if tool_name in self.tools else f"Unknown tool: {tool_name}"
            log.info("TOOL RESULT (%s): %s", tool_name, result[:300])

            self.memory.append({"step": step, "tool": tool_name, "input": tool_input, "result": result})
            steps_log.append({"step": step, "tool": tool_name, "input": tool_input, "result": result})

        final = "\n".join(s["result"] for s in steps_log)
        return {
            "answer": final,
            "steps": steps_log,
            "plan": plan,
            "mode": "keyword",
            "model": None,
        }

    # ------------------------------------------------------------------
    # Main entry point — routes to LLM or keyword
    # ------------------------------------------------------------------
    def run(self, user_input: str, session_id: str | None = None) -> dict:
        """Run the agent. Uses LLM if configured, else keyword matching."""
        self._session_id = session_id
        log.info("Agent.run() called  mode=%s  session=%s  input=\"%s\"",
                 "llm" if self.use_llm else "keyword",
                 session_id or "none", user_input[:200])
        # Persist the user message
        if session_id:
            self.memory_store.add_message(session_id, "user", user_input)
            self._maybe_consolidate(session_id)  # T2-1: auto-compact if threshold reached
        if self.use_llm:
            result = self.run_with_llm(user_input)
        else:
            result = self.run_with_keywords(user_input)
        # Persist the assistant reply
        if session_id:
            self.memory_store.add_message(
                session_id, "assistant", result.get("answer", ""),
                metadata={"mode": result.get("mode"), "model": result.get("model")},
            )
        return result

    # ==================================================================
    # KEYWORD MATCHING (preserved from original — used as fallback)
    # ==================================================================
    def _plan_keywords(self, user_input: str) -> list[str]:
        steps = []
        lower = user_input.lower()

        if any(w in lower for w in ["calculate", "math", "+", "-", "*", "/",
                                     "sqrt", "sum", "multiply", "factorial",
                                     "sin", "cos", "log", "power", "^"]):
            steps.append(f"Use calculator to solve: {user_input}")

        if any(w in lower for w in ["weather", "temperature outside", "forecast",
                                     "how hot", "how cold", "raining"]):
            steps.append(f"Look up weather: {user_input}")

        if any(w in lower for w in ["date", "time", "today", "day", "clock",
                                     "timezone", "utc", "epoch"]):
            steps.append(f"Get current date and time: {user_input}")

        if any(w in lower for w in ["convert", "to cm", "to m", "to kg",
                                     "to lb", "to f", "to c", "to miles",
                                     "to km", "to gallons", "to liters",
                                     "to gb", "to mb", "fahrenheit", "celsius",
                                     "how many"]):
            steps.append(f"Convert units: {user_input}")

        if any(w in lower for w in ["search", "google", "look up", "find info",
                                     "latest", "news", "current events"]):
            steps.append(f"Web search: {user_input}")

        if any(w in lower for w in ["wikipedia", "wiki", "who is", "what is",
                                     "tell me about", "define", "biography",
                                     "history of", "explain"]):
            steps.append(f"Wikipedia lookup: {user_input}")

        if any(w in lower for w in ["fetch", "open url", "get page", "http://",
                                     "https://", "www.", ".com", ".org"]):
            steps.append(f"Fetch URL: {user_input}")

        if any(w in lower for w in ["read file", "write file", "list dir",
                                     "list files", "file info", "open file",
                                     "create file", "append"]):
            steps.append(f"File operation: {user_input}")

        if any(w in lower for w in ["system info", "os", "python version",
                                     "hostname", "cpu", "platform", "machine"]):
            steps.append(f"Get system info: {user_input}")

        if any(w in lower for w in ["analyze text", "word count", "char count",
                                     "reading time", "text stats", "analyze this"]):
            steps.append(f"Analyze text: {user_input}")

        if any(w in lower for w in ["hash", "md5", "sha256", "sha1",
                                     "base64", "encode", "decode", "urlencode"]):
            steps.append(f"Hash/encode: {user_input}")

        if any(w in lower for w in ["my ip", "ip address", "ip lookup",
                                     "whois", "dns", "network", "geolocation"]):
            steps.append(f"IP lookup: {user_input}")

        if any(w in lower for w in ["note", "save", "remember", "remind",
                                     "list notes", "delete note"]):
            steps.append(f"Handle note: {user_input}")

        if any(w in lower for w in ["json", "yaml", "yml", "toml",
                                     "validate json", "format json",
                                     "minify", "json2yaml", "yaml2json"]):
            steps.append(f"Process JSON/YAML: {user_input}")

        if any(w in lower for w in ["csv", "comma separated", "spreadsheet",
                                     "parse csv", "csv stats", "csv data"]):
            steps.append(f"Process CSV: {user_input}")

        if any(w in lower for w in ["pdf", "read pdf", "extract pdf",
                                     "pdf text", "pdf page"]):
            steps.append(f"Read PDF: {user_input}")

        if any(w in lower for w in ["run code", "execute code", "python code",
                                     "run python", "execute python",
                                     "code runner", "run script"]):
            steps.append(f"Run code: {user_input}")

        if any(w in lower for w in ["process", "processes", "pid",
                                     "top processes", "running processes",
                                     "task manager", "kill process"]):
            steps.append(f"Process manager: {user_input}")

        if any(w in lower for w in ["ping", "dns lookup", "port scan",
                                     "ports open", "traceroute", "network diag",
                                     "speed test", "network speed"]):
            steps.append(f"Network diagnostic: {user_input}")

        if any(w in lower for w in ["password", "generate password",
                                     "passphrase", "pin code", "uuid",
                                     "random token", "password strength"]):
            steps.append(f"Generate password: {user_input}")

        if any(w in lower for w in ["regex", "regular expression", "regexp",
                                     "pattern match", "regex test"]):
            steps.append(f"Regex tool: {user_input}")

        if any(w in lower for w in ["zip", "unzip", "archive", "tar",
                                     "compress", "extract archive",
                                     "create zip", "create archive"]):
            steps.append(f"Archive operation: {user_input}")

        if any(w in lower for w in ["currency", "exchange rate", "convert currency",
                                     "usd to", "eur to", "gbp to",
                                     "dollar to", "euro to", "forex"]):
            steps.append(f"Currency conversion: {user_input}")

        if not steps:
            steps.append(f"Web search: {user_input}")

        return steps

    def _think_keywords(self, step: str) -> tuple[str | None, str]:
        lower = step.lower()

        if "calculator" in lower or any(op in lower for op in ["+", "-", "*", "/", "sqrt",
                                                                 "factorial", "sin(", "cos(",
                                                                 "log(", "^"]):
            expr = step.split(":")[-1].strip() if ":" in step else step
            for word in ["calculate", "what is", "solve", "compute", "what's",
                         "use calculator to solve"]:
                expr = expr.lower().replace(word, "").strip()
            expr = expr.replace("^", "**")
            return ("calculator", expr)

        if "weather" in lower or "forecast" in lower:
            text = step.split(":")[-1].strip() if ":" in step else step
            for w in ["weather", "in", "for", "of", "the", "look up", "what is",
                      "what's", "forecast", "how's", "?"]:
                text = text.lower().replace(w, "")
            return ("weather_lookup", text.strip() or "London")

        if "date" in lower or "time" in lower or "clock" in lower or "epoch" in lower:
            query = step.split(":")[-1].strip() if ":" in step else ""
            return ("get_datetime", query)

        if "convert" in lower or "unit" in lower:
            expr = step.split(":")[-1].strip() if ":" in step else step
            return ("unit_converter", expr)

        if "web search" in lower or "search" in lower:
            query = step.split(":")[-1].strip() if ":" in step else step
            for w in ["web search", "search for", "search", "google", "look up",
                      "find info on", "find info about"]:
                query = query.lower().replace(w, "").strip()
            return ("web_search", query)

        if "wikipedia" in lower or "wiki" in lower:
            topic = step.split(":")[-1].strip() if ":" in step else step
            for w in ["wikipedia lookup", "wikipedia", "wiki", "who is",
                      "what is", "tell me about", "define", "explain",
                      "biography of", "history of"]:
                topic = topic.lower().replace(w, "").strip()
            return ("wikipedia_lookup", topic)

        if "fetch" in lower or "url" in lower or "http" in lower or "www." in lower:
            url_match = re.search(r'(https?://\S+|www\.\S+)', step)
            if url_match:
                return ("url_fetcher", url_match.group(1))
            text = step.split(":")[-1].strip() if ":" in step else step
            return ("url_fetcher", text)

        if re.search(r'\bfiles?\b', lower) or re.search(r'\bdir(ectory)?\b', lower):
            command = step.split(":")[-1].strip() if ":" in step else step
            return ("file_manager", command)

        if "system" in lower or "platform" in lower or "hostname" in lower:
            return ("system_info", "")

        if "analyze" in lower or "word count" in lower or "text stats" in lower:
            text = step.split(":")[-1].strip() if ":" in step else step
            return ("text_analyzer", text)

        if any(w in lower for w in ["hash", "md5", "sha256", "sha1",
                                     "base64", "encode", "decode", "urlencode"]):
            text = step.split(":")[-1].strip() if ":" in step else step
            return ("hash_encode", text)

        if re.search(r'\bip\b', lower) or "network" in lower or "dns" in lower or "geolocation" in lower:
            query = step.split(":")[-1].strip() if ":" in step else ""
            for w in ["ip lookup", "my ip", "ip address", "look up", "lookup"]:
                query = query.lower().replace(w, "").strip()
            return ("ip_lookup", query)

        if re.search(r'\bnotes?\b', lower) or re.search(r'\bsave\b', lower) or re.search(r'\bremember\b', lower):
            text = step.split(":")[-1].strip() if ":" in step else step
            if not text.lower().startswith(("save", "list", "search", "delete", "clear")):
                text = f"save {text}"
            return ("note_taker", text)

        if any(w in lower for w in ["json", "yaml", "yml", "toml", "json2yaml",
                                     "yaml2json", "minify", "validate json", "format json"]):
            text = step.split(":")[-1].strip() if ":" in step else step
            return ("json_yaml_tool", text)

        if any(w in lower for w in ["csv", "comma separated", "spreadsheet",
                                     "parse csv", "csv stats"]):
            text = step.split(":")[-1].strip() if ":" in step else step
            return ("csv_data_tool", text)

        if any(w in lower for w in ["pdf", "read pdf", "extract pdf", "pdf text"]):
            text = step.split(":")[-1].strip() if ":" in step else step
            if not text.lower().startswith(("read", "page", "search", "info", "count")):
                text = f"read {text}"
            return ("pdf_reader", text)

        if any(w in lower for w in ["run code", "execute code", "python code",
                                     "run python", "execute python", "code runner"]):
            text = step.split(":")[-1].strip() if ":" in step else step
            return ("code_runner", text)

        if any(w in lower for w in ["process", "processes", "pid",
                                     "top processes", "running processes", "task manager"]):
            text = step.split(":")[-1].strip() if ":" in step else step
            if not text.lower().startswith(("list", "top", "memory", "search", "info", "count", "tree")):
                text = "top"
            return ("process_manager", text)

        if any(w in lower for w in ["ping", "dns lookup", "port scan",
                                     "ports open", "network diag", "speed test"]):
            text = step.split(":")[-1].strip() if ":" in step else step
            return ("network_diag", text)

        if any(w in lower for w in ["password", "generate password", "passphrase",
                                     "pin code", "uuid", "random token"]):
            text = step.split(":")[-1].strip() if ":" in step else step
            if not text.lower().startswith(("generate", "gen", "strong", "pin",
                                            "passphrase", "uuid", "token", "check")):
                text = f"generate"
            return ("password_gen", text)

        if any(w in lower for w in ["regex", "regular expression", "regexp",
                                     "pattern match"]):
            text = step.split(":")[-1].strip() if ":" in step else step
            return ("regex_tool", text)

        if any(w in lower for w in ["zip", "unzip", "archive", "tar",
                                     "compress", "extract archive"]):
            text = step.split(":")[-1].strip() if ":" in step else step
            return ("archive_tool", text)

        if any(w in lower for w in ["currency", "exchange rate", "convert currency",
                                     "usd to", "eur to", "gbp to", "dollar to", "forex"]):
            text = step.split(":")[-1].strip() if ":" in step else step
            return ("currency_convert", text)

        available = ", ".join(self.tools.keys())
        return (None, f"I'm not sure how to help with that. My tools: {available}")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    def show_memory(self):
        log.info("%s's Memory: %d entries", self.name, len(self.memory))
        for i, m in enumerate(self.memory, 1):
            log.debug("  %d. Step: %s  Tool: %s  Result: %s",
                      i, m['step'], m['tool'] or 'none', m['result'][:80])

    def available_tools_summary(self) -> str:
        lines = ["Available tools:"]
        for name, info in self.tools.items():
            lines.append(f"  - {name}: {info['description']}")
        return "\n".join(lines)

    # ==================================================================
    # T2-1 — Context Compaction + MEMORY.md
    # ==================================================================

    def consolidate_session(self, session_id: str) -> str:
        """Compact the session history using the LLM. Returns the summary text."""
        if not session_id:
            return "No session to compact."
        if not self.use_llm:
            return "LLM not available for compaction (running in keyword mode)."

        def llm_fn(prompt: str) -> str:
            return self.llm.chat([{"role": "user", "content": prompt}])

        return self.memory_store.consolidate(session_id, llm_fn=llm_fn)

    def _maybe_consolidate(self, session_id: str) -> None:
        """Auto-compact if the session message count reaches CONSOLIDATE_EVERY."""
        consolidate_every = int(os.getenv("CONSOLIDATE_EVERY", "20"))
        try:
            count = self.memory_store.count_messages(session_id)
            if count >= consolidate_every:
                log.info(
                    "Auto-compact triggered: session=%s  messages=%d  threshold=%d",
                    session_id, count, consolidate_every,
                )
                self.consolidate_session(session_id)
        except Exception as e:
            log.warning("Auto-compact failed for session %s: %s", session_id, e)

    # ==================================================================
    # T2-2 — HEARTBEAT.md Background Scheduler
    # ==================================================================

    def _parse_heartbeat_md(self) -> list[dict]:
        """Parse HEARTBEAT.md → list of {name, schedule, prompt} dicts.
        Strips HTML comment blocks (<!-- ... -->) before parsing."""
        raw = self._load_md("HEARTBEAT.md")
        # Remove HTML comment blocks (examples are wrapped in <!-- -->)
        raw = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
        tasks: list[dict] = []
        current: dict | None = None
        for line in raw.splitlines():
            stripped = line.strip()
            if re.match(r"^## .+", stripped):
                if current and current.get("prompt"):
                    tasks.append(current)
                current = {"name": stripped[3:].strip(), "schedule": "", "prompt": ""}
            elif current and stripped.lower().startswith("schedule:"):
                current["schedule"] = stripped.split(":", 1)[1].strip()
            elif current and stripped.startswith("> "):
                current["prompt"] = (current["prompt"] + " " + stripped[2:].strip()).strip()
        if current and current.get("prompt"):
            tasks.append(current)
        return tasks

    def _parse_next_run(self, schedule: str, last_run: float) -> float:
        """Return the next Unix timestamp this task should fire."""
        schedule = schedule.lower().strip()
        # "every Nm" / "every Nh"
        m = re.match(r"every\s+(\d+)\s*(m|min|h|hr|hour)s?", schedule)
        if m:
            qty = int(m.group(1))
            delta = qty * (3600 if m.group(2).startswith("h") else 60)
            return last_run + delta
        # "daily HH:MM"
        m = re.match(r"daily\s+(\d{1,2}):(\d{2})", schedule)
        if m:
            now = datetime.datetime.now()
            target = now.replace(
                hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0
            )
            if target.timestamp() <= last_run:
                target += datetime.timedelta(days=1)
            return target.timestamp()
        # "weekly DAY HH:MM"
        m = re.match(r"weekly\s+(\w+)\s+(\d{1,2}):(\d{2})", schedule)
        if m:
            day_names = ["monday", "tuesday", "wednesday", "thursday",
                         "friday", "saturday", "sunday"]
            day_name = m.group(1).lower()
            day_idx = day_names.index(day_name) if day_name in day_names else 0
            now = datetime.datetime.now()
            target = now.replace(
                hour=int(m.group(2)), minute=int(m.group(3)), second=0, microsecond=0
            )
            days_ahead = (day_idx - target.weekday()) % 7
            target += datetime.timedelta(days=days_ahead)
            if target.timestamp() <= last_run:
                target += datetime.timedelta(weeks=1)
            return target.timestamp()
        # Default: every 30 minutes
        return last_run + 1800

    def _load_heartbeat_state(self) -> dict:
        try:
            if _HEARTBEAT_STATE_FILE.exists():
                return json.loads(_HEARTBEAT_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_heartbeat_state(self, state: dict) -> None:
        try:
            _HEARTBEAT_STATE_FILE.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as e:
            log.warning("Could not save heartbeat state: %s", e)

    def _run_heartbeat_tasks(self) -> None:
        """Execute any HEARTBEAT.md tasks + user schedule_tool tasks that are due."""
        now = time.time()
        state = self._load_heartbeat_state()

        # Collect tasks from HEARTBEAT.md
        tasks = self._parse_heartbeat_md()

        # Also include user-defined tasks from schedule_tool (agent_schedule.json)
        schedule_file = Path(__file__).parent / "agent_schedule.json"
        if schedule_file.exists():
            try:
                user_tasks = json.loads(schedule_file.read_text(encoding="utf-8"))
                tasks.extend(user_tasks)
            except Exception:
                pass

        for task in tasks:
            name = task.get("name", "unnamed")
            schedule = task.get("schedule", "")
            prompt = task.get("prompt", "")
            if not prompt or not schedule:
                continue
            last_run = state.get(name, 0)
            next_run = self._parse_next_run(schedule, last_run)
            if now < next_run:
                continue
            log.info("[HEARTBEAT] Running task: %s", name)
            try:
                result = self.run(prompt, session_id="heartbeat")
                answer = result.get("answer", "")
                if answer:
                    note_fn = self.tools.get("note_taker", {}).get("function")
                    if note_fn:
                        note_fn(f"save [heartbeat:{name}] {answer[:500]}")
                state[name] = now
                log.info("[HEARTBEAT] Task '%s' done: %s", name, answer[:80])
            except Exception as e:
                log.error("[HEARTBEAT] Task '%s' failed: %s", name, e)
                state[name] = now  # advance to avoid rapid retry on error

        self._save_heartbeat_state(state)

    def _start_heartbeat(self) -> None:
        """Start the HEARTBEAT background daemon thread."""
        if os.getenv("HEARTBEAT_ENABLED", "1") == "0":
            log.info("HEARTBEAT scheduler disabled (HEARTBEAT_ENABLED=0)")
            return
        interval = int(os.getenv("HEARTBEAT_INTERVAL_SECS", "1800"))

        def tick():
            try:
                self._run_heartbeat_tasks()
            except Exception as e:
                log.error("[HEARTBEAT] Tick error: %s", e)
            t = threading.Timer(interval, tick)
            t.daemon = True
            t.start()

        # First tick fires after one full interval (not immediately on startup)
        t = threading.Timer(interval, tick)
        t.daemon = True
        t.start()
        log.info("HEARTBEAT scheduler started  interval=%ds (%dm)", interval, interval // 60)

    # ==================================================================
    # T2-4 — Streaming Agent Loop
    # ==================================================================

    def run_with_llm_streaming(self, user_input: str):
        """ReAct loop that yields live events as the agent works.

        Event types yielded:
          {"type": "thinking",   "step": N, "thought": "..."}
          {"type": "tool_call",  "tool": name, "input": inp}
          {"type": "tool_result","tool": name, "result": snippet}
          {"type": "token",      "token": chunk}   ← final answer tokens
          {"type": "done",       "answer": text, "steps": [...], ...}
        """
        # T3-4A: inject relevant facts (TF-IDF ranked, falls back to all)
        sys_content = self._system_prompt()
        relevant_facts = self.memory_store.retrieve_relevant_facts(
            user_input, session_id=self._session_id, top_n=8
        )
        if relevant_facts:
            lines = ["Relevant facts about the user/context:"]
            for f in relevant_facts:
                lines.append(f"  - {f.key}: {f.value}")
            sys_content += "\n\n" + "\n".join(lines)
        else:
            facts_ctx = self.memory_store.all_facts_as_context(limit=20)
            if facts_ctx:
                sys_content += "\n\n" + facts_ctx

        messages = [{"role": "system", "content": sys_content}]
        if self._session_id:
            history = self.memory_store.get_conversation(self._session_id, limit=10)
            for msg in history:
                if msg.role in ("user", "assistant"):
                    messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": user_input})
        steps_log: list[dict] = []
        plan: list[str] = []

        for step_num in range(1, self.max_steps + 1):
            # Intermediate steps: synchronous JSON mode (reliable tool-call detection)
            try:
                raw_response = self.llm.chat(messages, json_mode=True)
            except Exception as e:
                log.error("LLM error in streaming loop: %s — keyword fallback", e)
                result = self.run_with_keywords(user_input)
                yield {"type": "token", "token": result.get("answer", "")}
                yield {
                    "type": "done",
                    "answer": result.get("answer", ""),
                    "steps": result.get("steps", []),
                    "plan": result.get("plan", []),
                    "mode": "keyword",
                    "model": None,
                }
                return

            parsed = self._parse_llm_response(raw_response)
            action = parsed.get("action", "answer")
            thought = parsed.get("thought", "")

            # Normalize non-standard action values
            tool_name_from_action = None
            if action not in ("tool_call", "answer"):
                if action in self.tools:
                    tool_name_from_action = action
                    action = "tool_call"
                elif parsed.get("tool") and parsed["tool"] in self.tools:
                    action = "tool_call"
                else:
                    action = "answer"
                    if not parsed.get("text"):
                        parsed["text"] = raw_response

            if thought:
                yield {"type": "thinking", "step": step_num, "thought": thought}

            # ── Final answer: stream tokens via chat_stream ──────────
            if action == "answer":
                answer_text = parsed.get("text", raw_response)

                # Nudge on suspiciously empty answer
                if step_num == 1 and len(answer_text.strip()) < 3:
                    messages.append({"role": "assistant", "content": raw_response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your answer was empty. Use a tool to help. "
                            "Respond with typed params JSON: "
                            "{\"action\": \"tool_call\", \"tool\": \"<name>\", \"params\": {\"<param>\": \"<value>\"}, \"thought\": \"<why>\"}"
                        ),
                    })
                    continue

                # Ask LLM to present the answer in natural plain prose and stream it
                synth_messages = messages + [
                    {"role": "assistant", "content": raw_response},
                    {
                        "role": "user",
                        "content": (
                            "Present your answer clearly in natural prose or markdown. "
                            "Do not use JSON format."
                        ),
                    },
                ]
                streamed_text = ""
                try:
                    for chunk in self.llm.chat_stream(synth_messages):
                        if chunk:
                            streamed_text += chunk
                            yield {"type": "token", "token": chunk}
                except Exception as se:
                    log.warning("chat_stream failed (%s) — falling back to parsed answer", se)

                if not streamed_text.strip():
                    # Streaming unavailable — yield pre-computed answer
                    streamed_text = answer_text
                    yield {"type": "token", "token": answer_text}

                steps_log.append({
                    "step": thought or "Final answer",
                    "tool": None, "input": "", "result": streamed_text,
                })
                yield {
                    "type": "done",
                    "answer": streamed_text,
                    "steps": steps_log,
                    "plan": plan or [thought or "Direct answer"],
                    "mode": "llm",
                    "model": self.llm_config.model,
                }
                return

            # ── Tool call ─────────────────────────────────────────────
            if action == "tool_call":
                tool_name = tool_name_from_action or parsed.get("tool", "")
                tool_input = self._resolve_tool_input(tool_name, parsed)  # T3-1
                plan.append(f"Call {tool_name}: {tool_input}")

                yield {"type": "tool_call", "tool": tool_name, "input": tool_input}

                if tool_name not in self.tools:
                    result_text = f"Error: Unknown tool '{tool_name}'."
                else:
                    cached = self.memory_store.get_cached_result(tool_name, tool_input)
                    if cached:
                        result_text = cached
                    else:
                        try:
                            result_text = self.tools[tool_name]["function"](tool_input)
                        except Exception as e:
                            result_text = f"Tool error: {e}"
                        ttl = 60 if tool_name == "get_datetime" else 300
                        self.memory_store.cache_tool_result(
                            tool_name, tool_input, result_text, ttl=ttl
                        )

                yield {"type": "tool_result", "tool": tool_name, "result": result_text[:300]}

                steps_log.append({
                    "step": thought or f"Use {tool_name}",
                    "tool": tool_name, "input": tool_input, "result": result_text,
                })
                messages.append({"role": "assistant", "content": raw_response})
                messages.append({
                    "role": "user",
                    "content": FOLLOW_UP_PROMPT.replace("{tool}", tool_name)
                                               .replace("{result}", result_text),
                })
                continue

        # Max steps exceeded
        final = "\n".join(s["result"] for s in steps_log)
        yield {"type": "token", "token": final}
        yield {
            "type": "done",
            "answer": final,
            "steps": steps_log,
            "plan": plan,
            "mode": "llm",
            "model": self.llm_config.model,
        }

    def run_streaming(self, user_input: str, session_id: str | None = None):
        """Public streaming entry point. Routes to LLM streaming or keyword.

        Yields the same event dicts as run_with_llm_streaming().
        Also persists messages; auto-triggers compaction if threshold reached.
        """
        self._session_id = session_id
        if session_id:
            self.memory_store.add_message(session_id, "user", user_input)
            self._maybe_consolidate(session_id)

        if self.use_llm:
            gen = self.run_with_llm_streaming(user_input)
        else:
            result = self.run_with_keywords(user_input)
            gen = iter([
                {"type": "token", "token": result.get("answer", "")},
                {**result, "type": "done"},
            ])

        final_answer = ""
        for event in gen:
            if event.get("type") == "token":
                final_answer += event.get("token", "")
            elif event.get("type") == "done":
                final_answer = event.get("answer", final_answer)
            yield event

        if session_id and final_answer:
            self.memory_store.add_message(
                session_id, "assistant", final_answer,
                metadata={"mode": "streaming"},
            )

