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
from tools import TOOL_REGISTRY
from llm_provider import LLMProvider, LLMConfig
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

Available tools:
{tool_list}

Respond with exactly ONE of these JSON formats:

1) To call a tool (USE THIS whenever a tool can help):
{{"action": "tool_call", "tool": "<tool_name>", "input": "<input_string>", "thought": "<why you chose this>"}}

2) To give a final answer (ONLY when no tool is needed or after receiving tool results):
{{"action": "answer", "text": "<your answer>", "thought": "<your reasoning>"}}

Tool input examples:
- weather_lookup: just the city name → "Tokyo"
- web_search: the search query → "python tutorials"
- wikipedia_lookup: the topic → "Alan Turing"
- calculator: Python math expression → "factorial(10) / sqrt(144)"
- unit_converter: full conversion → "100 km to miles"
- hash_encode: command + text → "sha256 hello world"
- note_taker: command + text → "save remember to buy milk"
- ip_lookup: empty string for own IP, or an IP address
- get_datetime: timezone offset "+5:30" or empty string
- system_info: empty string
- file_manager: command like "list ." or "read file.txt"
- url_fetcher: the full URL
- text_analyzer: the text to analyze
- document_ocr: command like "scan photo.png" or "search invoice" or "status"

Example interaction:
User: "What's the weather in London?"
You: {{"action": "tool_call", "tool": "weather_lookup", "input": "London", "thought": "User wants current weather, I must use the weather tool"}}

ALWAYS respond with valid JSON. Nothing else."""


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
        self.memory: list[dict] = []
        self.max_steps = int(os.getenv("AGENT_MAX_STEPS", "20"))
        self.llm_config = LLMConfig()
        self.llm = LLMProvider(self.llm_config)

    @property
    def use_llm(self) -> bool:
        """Check if LLM mode is active (not keyword mode)."""
        return self.llm_config.provider != "keyword"

    # ------------------------------------------------------------------
    # Build the tool list for the system prompt
    # ------------------------------------------------------------------
    def _build_tool_list(self) -> str:
        lines = []
        for name, info in self.tools.items():
            lines.append(f"  - {name}: {info['description']}")
        return "\n".join(lines)

    def _system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(tool_list=self._build_tool_list())

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

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": user_input},
        ]

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
                tool_input = parsed.get("input", "")
                plan.append(f"Call {tool_name}: {tool_input}")

                log.info("TOOL CALL: %s(\"%s\")", tool_name, tool_input)

                if tool_name not in self.tools:
                    result = f"Error: Unknown tool '{tool_name}'. Available: {', '.join(self.tools.keys())}"
                    log.error("%s", result)
                else:
                    try:
                        result = self.tools[tool_name]["function"](tool_input)
                    except Exception as e:
                        result = f"Tool error: {e}"
                        log.exception("Tool %s raised an exception", tool_name)
                    log.info("TOOL RESULT (%s): %s", tool_name, result[:300])

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
                    "content": FOLLOW_UP_PROMPT.format(tool=tool_name, result=result),
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
    def run(self, user_input: str) -> dict:
        """Run the agent. Uses LLM if configured, else keyword matching."""
        log.info("Agent.run() called  mode=%s  input=\"%s\"",
                 "llm" if self.use_llm else "keyword", user_input[:200])
        if self.use_llm:
            return self.run_with_llm(user_input)
        else:
            return self.run_with_keywords(user_input)

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
