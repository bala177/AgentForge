"""
llm_provider.py — LLM abstraction layer.

Supports multiple backends:
  • Ollama     (local, free — default)
  • OpenAI     (cloud, API key required)
  • Fallback   (keyword matching — always available)

All providers expose the same interface so the agent doesn't care
which backend is active.  Switching is a one-line config change.

Ollama API docs:  https://github.com/ollama/ollama/blob/main/docs/api.md
"""

import json
import requests
from dataclasses import dataclass, field
from log_config import get_logger

log = get_logger("llm")

# ── Constants ─────────────────────────────────────────────────────────
OLLAMA_BASE = "http://localhost:11434"
OPENAI_BASE = "https://api.openai.com/v1"
HTTP_TIMEOUT = 60  # LLMs can be slow on first load


# ── Configuration ─────────────────────────────────────────────────────
@dataclass
class LLMConfig:
    """Runtime-editable LLM settings."""
    provider: str = "ollama"            # "ollama" | "openai" | "keyword"
    model: str = ""                     # Auto-detected on startup (or set manually)
    ollama_url: str = OLLAMA_BASE       # Ollama server URL
    openai_api_key: str = ""            # OpenAI API key (if using openai)
    openai_base_url: str = OPENAI_BASE  # For OpenAI-compatible servers
    temperature: float = 0.2            # Lower = more deterministic
    max_tokens: int = 1024              # Max response length

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        # Mask API key for safety
        if d["openai_api_key"]:
            d["openai_api_key"] = d["openai_api_key"][:8] + "..." 
        return d

    def update(self, data: dict):
        for k, v in data.items():
            if hasattr(self, k):
                expected = type(getattr(self, k))
                try:
                    setattr(self, k, expected(v))
                except (ValueError, TypeError):
                    pass


# ── Provider base ─────────────────────────────────────────────────────
class LLMProvider:
    """Thin wrapper around an LLM HTTP API."""

    def __init__(self, config: LLMConfig):
        self.config = config
        log.info("LLMProvider init  provider=%s  model=%s", config.provider, config.model or "(auto)")
        # Auto-detect model if not set
        if not self.config.model and self.config.provider == "ollama":
            self._auto_detect_model()

    def _auto_detect_model(self):
        """Auto-detect the best available Ollama model on startup."""
        try:
            r = requests.get(f"{self.config.ollama_url}/api/tags", timeout=5)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            if models:
                # Prefer larger models: llama3 > llama3.2 > tinyllama > anything
                preferred = ["llama3:latest", "llama3.2:latest", "llama3.1:latest",
                             "mistral:latest", "tinyllama:latest"]
                for pref in preferred:
                    if pref in models:
                        self.config.model = pref
                        log.info("Auto-detected model: %s", pref)
                        return
                # Fall back to first model
                self.config.model = models[0]
                log.info("Auto-detected model: %s", models[0])
            else:
                self.config.model = "llama3:latest"  # Will fail gracefully later
                log.warning("No models found - defaulting to llama3:latest")
        except Exception:
            self.config.model = "llama3:latest"
            log.warning("Ollama not reachable - defaulting to llama3:latest")

    # ── Core method: chat completion ──────────────────────────────────
    def chat(self, messages: list[dict], json_mode: bool = False) -> str:
        """
        Send a list of messages and return the assistant's reply as a string.

        messages = [
            {"role": "system", "content": "..."},
            {"role": "user",   "content": "..."},
            {"role": "assistant", "content": "..."},   # optional
        ]
        """
        provider = self.config.provider.lower()
        log.debug("chat() called  provider=%s  model=%s  messages=%d  json_mode=%s",
                  provider, self.config.model, len(messages), json_mode)

        if provider == "ollama":
            return self._chat_ollama(messages, json_mode)
        elif provider == "openai":
            return self._chat_openai(messages, json_mode)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    # ── Ollama ────────────────────────────────────────────────────────
    def _chat_ollama(self, messages: list[dict], json_mode: bool) -> str:
        url = f"{self.config.ollama_url}/api/chat"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"

        try:
            r = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            content = data.get("message", {}).get("content", "").strip()
            log.info("Ollama response received  len=%d", len(content))
            log.debug("Ollama response: %s", content[:300])
            return content
        except requests.ConnectionError:
            log.error("Cannot connect to Ollama at %s", self.config.ollama_url)
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.config.ollama_url}. "
                "Make sure Ollama is running (ollama serve)."
            )
        except requests.Timeout:
            log.error("Ollama request timed out")
            raise TimeoutError("Ollama request timed out. The model may be loading.")
        except Exception as e:
            log.exception("Ollama error")
            raise RuntimeError(f"Ollama error: {e}")

    # ── OpenAI / OpenAI-compatible ────────────────────────────────────
    def _chat_openai(self, messages: list[dict], json_mode: bool) -> str:
        url = f"{self.config.openai_base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.openai_api_key}",
        }
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            r = requests.post(url, json=payload, headers=headers, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"].strip()
            log.info("OpenAI response received  len=%d", len(content))
            log.debug("OpenAI response: %s", content[:300])
            return content
        except requests.ConnectionError:
            log.error("Cannot connect to OpenAI API at %s", self.config.openai_base_url)
            raise ConnectionError(f"Cannot connect to OpenAI API at {self.config.openai_base_url}")
        except Exception as e:
            log.exception("OpenAI error")
            raise RuntimeError(f"OpenAI error: {e}")

    # ── Status / introspection ────────────────────────────────────────
    def is_available(self) -> tuple[bool, str]:
        """Check if the current provider is reachable."""
        try:
            if self.config.provider == "ollama":
                r = requests.get(f"{self.config.ollama_url}/api/tags", timeout=5)
                r.raise_for_status()
                models = [m["name"] for m in r.json().get("models", [])]
                if not models:
                    return False, "Ollama is running but no models are installed. Run: ollama pull llama3.2"
                return True, f"Ollama OK — {len(models)} model(s): {', '.join(models[:5])}"
            elif self.config.provider == "openai":
                if not self.config.openai_api_key:
                    return False, "OpenAI API key not configured"
                r = requests.get(
                    f"{self.config.openai_base_url}/models",
                    headers={"Authorization": f"Bearer {self.config.openai_api_key}"},
                    timeout=5,
                )
                r.raise_for_status()
                return True, "OpenAI API OK"
            elif self.config.provider == "keyword":
                return True, "Keyword matching (no LLM)"
            else:
                return False, f"Unknown provider: {self.config.provider}"
        except requests.ConnectionError:
            return False, f"Cannot connect to {self.config.provider}. Is it running?"
        except Exception as e:
            return False, str(e)

    def list_models(self) -> list[str]:
        """List available models from the current provider."""
        try:
            if self.config.provider == "ollama":
                r = requests.get(f"{self.config.ollama_url}/api/tags", timeout=5)
                r.raise_for_status()
                return [m["name"] for m in r.json().get("models", [])]
            elif self.config.provider == "openai":
                if not self.config.openai_api_key:
                    return []
                r = requests.get(
                    f"{self.config.openai_base_url}/models",
                    headers={"Authorization": f"Bearer {self.config.openai_api_key}"},
                    timeout=5,
                )
                r.raise_for_status()
                return sorted([m["id"] for m in r.json().get("data", [])])
            else:
                return []
        except Exception:
            return []
