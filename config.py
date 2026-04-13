"""
config.py — Centralised configuration for the Agent platform.

All settings can be overridden via environment variables.
Uses dataclasses for simplicity (no external dependencies).

Environment variables:
  APP_PORT          — Server port (default: 5000)
  APP_HOST          — Server host (default: 0.0.0.0)
  LLM_PROVIDER      — "ollama" | "openai" | "keyword" (default: ollama)
  LLM_MODEL          — Model name (auto-detected if empty)
  OLLAMA_URL         — Ollama server URL (default: http://localhost:11434)
  OPENAI_API_KEY     — OpenAI API key
  OPENAI_BASE_URL    — OpenAI base URL (for compatible servers)
  LLM_TEMPERATURE    — LLM temperature 0.0-1.0 (default: 0.2)
  LLM_MAX_TOKENS     — Max response tokens (default: 1024)
  SESSION_TTL        — Session timeout in seconds (default: 1800 = 30 min)
  MAX_UPLOAD_MB      — Max upload size in MB (default: 16)
  LOG_LEVEL          — Logging level (default: DEBUG)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


# ── Paths ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "gateway" / "templates"
OCR_UPLOADS_DIR = BASE_DIR / "ocr_uploads"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


@dataclass
class AppConfig:
    """Application-level settings."""
    host: str = field(default_factory=lambda: _env("APP_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("APP_PORT", 5000))
    max_upload_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_MB", 16))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "DEBUG"))
    session_ttl: int = field(default_factory=lambda: _env_int("SESSION_TTL", 1800))
    base_dir: Path = BASE_DIR
    data_dir: Path = DATA_DIR
    templates_dir: Path = TEMPLATES_DIR


@dataclass
class LLMSettings:
    """LLM provider settings (runtime-editable)."""
    provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "ollama"))
    model: str = field(default_factory=lambda: _env("LLM_MODEL", ""))
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://localhost:11434"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", ""))
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.2))
    max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 1024))

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
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


# ── Singleton instances ───────────────────────────────────────────────
app_config = AppConfig()
llm_settings = LLMSettings()
