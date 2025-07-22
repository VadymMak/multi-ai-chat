# app/config/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass

def _getenv_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _getenv_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _getenv_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    val = val.strip().lower()
    return val in {"1", "true", "t", "yes", "y", "on"}

def _getenv_str(name: str, default: str) -> str:
    return os.getenv(name, default)

@dataclass(frozen=True)
class _Settings:
    """
    Centralized runtime configuration.
    All values are read once at import-time from environment variables.
    """

    # === Core model defaults ===
    DEFAULT_MODEL: str = _getenv_str("DEFAULT_MODEL", "gpt-5")
    OPENAI_DEFAULT_MODEL: str = _getenv_str("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")
    ANTHROPIC_DEFAULT_MODEL: str = _getenv_str("ANTHROPIC_DEFAULT_MODEL", "claude-3-5-sonnet-20241022")

    # Optional explicit fallbacks used by the factory when a provider/model fails
    OPENAI_FALLBACK_MODEL: str = _getenv_str("OPENAI_FALLBACK_MODEL", "gpt-4o-mini")
    ANTHROPIC_FALLBACK_MODEL: str = _getenv_str("ANTHROPIC_FALLBACK_MODEL", "claude-3-5-haiku-latest")

    # === History / autosummarize ===
    # Router soft trigger for /chat/summarize legacy path
    SUMMARIZE_TRIGGER_TOKENS: int = _getenv_int("SUMMARIZE_TRIGGER_TOKENS", 2000)
    # How many tokens of trimmed turns we try to pass to the model
    HISTORY_MAX_TOKENS: int = _getenv_int("HISTORY_MAX_TOKENS", 1800)
    # How many rows to fetch from DB before trimming
    HISTORY_FETCH_LIMIT: int = _getenv_int("HISTORY_FETCH_LIMIT", 200)

    # Token cap for injecting memory summaries into the prompt (prompt builder)
    MEMORY_SUMMARY_BUDGET_TOKENS: int = _getenv_int("MEMORY_SUMMARY_BUDGET_TOKENS", 600)

    # === Token preflight (used by /ask) ===
    SOFT_TOKEN_BUDGET: int = _getenv_int("SOFT_TOKEN_BUDGET", 6000)
    HARD_TOKEN_BUDGET: int = _getenv_int("HARD_TOKEN_BUDGET", 7800)

    # === Canonical Memory ===
    ENABLE_CANON: bool = _getenv_bool("ENABLE_CANON", False)
    CANON_TOPK: int = _getenv_int("CANON_TOPK", 6)
    CANON_EXTRACT_MODEL: str = _getenv_str("CANON_EXTRACT_MODEL", "gpt-4o-mini")

    # === Rendering modes / behavior flags ===
    # Auto-detect code vs doc replies and normalize output
    ENABLE_CODE_DOC_AUTOMODE: bool = _getenv_bool("ENABLE_CODE_DOC_AUTOMODE", True)
    # Omit temperature for “reasoning” model families (handled in OpenAI wrapper)
    OMIT_TEMPERATURE_FOR_REASONING: bool = _getenv_bool("OMIT_TEMPERATURE_FOR_REASONING", True)
    # Default for JSON mode; wrappers can override per-request
    JSON_MODE_DEFAULT: bool = _getenv_bool("JSON_MODE_DEFAULT", False)

    # === Provider-specific behavior ===
    # Anthropic: immediately short-circuit on 529 to allow fallback
    CLAUDE_OVERLOAD_SHORTCIRCUIT: bool = _getenv_bool("CLAUDE_OVERLOAD_SHORTCIRCUIT", True)

    # === YouTube on-demand (chat intent) ===
    ENABLE_YT_IN_CHAT: bool = _getenv_bool("ENABLE_YT_IN_CHAT", True)
    YT_SEARCH_MAX_RESULTS: int = _getenv_int("YT_SEARCH_MAX_RESULTS", 3)
    YT_SEARCH_TIMEOUT: float = _getenv_float("YT_SEARCH_TIMEOUT", 6.0)

    # === Observability toggles ===
    ENABLE_PAYLOAD_PREVIEW_LOG: bool = _getenv_bool("ENABLE_PAYLOAD_PREVIEW_LOG", True)
    LOG_TOKEN_COUNTS: bool = _getenv_bool("LOG_TOKEN_COUNTS", True)

settings = _Settings()

__all__ = ["settings", "_Settings"]
