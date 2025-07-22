from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple

# ---------------------------- env helpers ----------------------------

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

def _getenv_int_opt(name: str) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None

def _getenv_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    if not raw:
        return tuple()
    return tuple([tok.strip() for tok in raw.split(",") if tok.strip()])

def _sanitize_model_key(s: str) -> str:
    """
    Convert a model string into an ENV-safe key segment.
    e.g. 'gpt-4o-mini' -> 'GPT_4O_MINI'
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", (s or "").strip()).upper()

# ------------------------------ settings -----------------------------

@dataclass(frozen=True)
class _Settings:
    """
    Centralized runtime configuration.
    All values are read once at import-time from environment variables.
    """

    # === Core model defaults (must match keys in MODEL_REGISTRY) ===
    DEFAULT_MODEL: str = _getenv_str("DEFAULT_MODEL", "gpt-5")
    OPENAI_DEFAULT_MODEL: str = _getenv_str("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")
    ANTHROPIC_DEFAULT_MODEL: str = _getenv_str("ANTHROPIC_DEFAULT_MODEL", "claude-sonnet-4-20250514")

    # Optional explicit fallbacks used by the factory when a provider/model fails
    OPENAI_FALLBACK_MODEL: str = _getenv_str("OPENAI_FALLBACK_MODEL", "gpt-4o-mini")
    ANTHROPIC_FALLBACK_MODEL: str = _getenv_str("ANTHROPIC_FALLBACK_MODEL", "claude-3-5-haiku-latest")

    # === History / autosummarize ===
    SUMMARIZE_TRIGGER_TOKENS: int = _getenv_int("SUMMARIZE_TRIGGER_TOKENS", 2000)
    HISTORY_MAX_TOKENS: int = _getenv_int("HISTORY_MAX_TOKENS", 1800)
    HISTORY_FETCH_LIMIT: int = _getenv_int("HISTORY_FETCH_LIMIT", 200)

    # Token cap for injecting memory summaries into the prompt (prompt builder)
    MEMORY_SUMMARY_BUDGET_TOKENS: int = _getenv_int("MEMORY_SUMMARY_BUDGET_TOKENS", 600)

    # === Token limits for /ask preflight (used by get_thresholds) ===
    # Defaults: soft=1500, hard=3000
    SOFT_TOKEN_LIMIT: int = _getenv_int("SOFT_TOKEN_LIMIT", 1500)
    HARD_TOKEN_LIMIT: int = _getenv_int("HARD_TOKEN_LIMIT", 3000)

    # Legacy budgets (back-compat with older code paths)
    SOFT_TOKEN_BUDGET: int = _getenv_int("SOFT_TOKEN_BUDGET", 6000)
    HARD_TOKEN_BUDGET: int = _getenv_int("HARD_TOKEN_BUDGET", 7800)

    # === Canonical Memory ===
    ENABLE_CANON: bool = _getenv_bool("ENABLE_CANON", False)
    CANON_TOPK: int = _getenv_int("CANON_TOPK", 6)
    CANON_EXTRACT_MODEL: str = _getenv_str("CANON_EXTRACT_MODEL", "gpt-4o-mini")

    # === Rendering modes / behavior flags ===
    ENABLE_CODE_DOC_AUTOMODE: bool = _getenv_bool("ENABLE_CODE_DOC_AUTOMODE", True)
    OMIT_TEMPERATURE_FOR_REASONING: bool = _getenv_bool("OMIT_TEMPERATURE_FOR_REASONING", True)
    JSON_MODE_DEFAULT: bool = _getenv_bool("JSON_MODE_DEFAULT", False)

    # === Provider-specific behavior ===
    CLAUDE_OVERLOAD_SHORTCIRCUIT: bool = _getenv_bool("CLAUDE_OVERLOAD_SHORTCIRCUIT", True)

    # === YouTube: chat intent (still supported) ===
    ENABLE_YT_IN_CHAT: bool = _getenv_bool("ENABLE_YT_IN_CHAT", True)
    YT_SEARCH_MAX_RESULTS: int = _getenv_int("YT_SEARCH_MAX_RESULTS", 3)
    YT_SEARCH_TIMEOUT: float = _getenv_float("YT_SEARCH_TIMEOUT", 6.0)

    # === Web search (Wikipedia-backed) ===
    WEB_SEARCH_MAX_RESULTS: int = _getenv_int("WEB_SEARCH_MAX_RESULTS", 3)

    # === Observability toggles ===
    ENABLE_PAYLOAD_PREVIEW_LOG: bool = _getenv_bool("ENABLE_PAYLOAD_PREVIEW_LOG", True)
    LOG_TOKEN_COUNTS: bool = _getenv_bool("LOG_TOKEN_COUNTS", True)

    # === Database ===
    DATABASE_URL: Optional[str] = _getenv_str("DATABASE_URL", "")
    
    # === API Keys (resolved here for convenience) ===
    OPENAI_API_KEY: Optional[str] = (
        _getenv_str("OPENAI_API_KEY", "") or _getenv_str("CHATITNOW_API_KEY", "") or _getenv_str("OPEN_API_KEY", "")
    )
    ANTHROPIC_API_KEY: Optional[str] = _getenv_str("ANTHROPIC_API_KEY", "") or _getenv_str("CLAUDE_API_KEY", "")
    YOUTUBE_API_KEY: Optional[str] = _getenv_str("YOUTUBE_API_KEY", "")

    # === YouTube deterministic search (new) ===
    YOUTUBE_REGION_CODE: str = _getenv_str("YOUTUBE_REGION_CODE", "US")
    YOUTUBE_SAFESEARCH: str = _getenv_str("YOUTUBE_SAFESEARCH", "moderate")  # none|moderate|strict
    YOUTUBE_ORDER: str = _getenv_str("YOUTUBE_ORDER", "relevance")  # relevance|date
    YOUTUBE_DEBUG: bool = _getenv_bool("YOUTUBE_DEBUG", False)

    # Fallback provider toggles (optional)
    PIPED_DISABLE: bool = _getenv_bool("PIPED_DISABLE", True)
    PIPED_HOSTS: tuple[str, ...] = _getenv_csv("PIPED_HOSTS")

    # Allowlist for preferred channels (names or IDs), optional
    YOUTUBE_CHANNEL_ALLOWLIST: tuple[str, ...] = _getenv_csv("YOUTUBE_CHANNEL_ALLOWLIST")

    # === Downloads feature flag (reserved for later steps) ===
    ENABLE_YT_DOWNLOADS: bool = _getenv_bool("ENABLE_YT_DOWNLOADS", False)

settings = _Settings()

# ------------------------- thresholds helper --------------------------

def get_thresholds(model: Optional[str] = None, provider: Optional[str] = None) -> Tuple[int, int]:
    """
    Returns (soft_limit, hard_limit) with override precedence:
      1) MODEL override env:
         - MODEL_<SANITIZED_MODEL>_SOFT_TOKEN_LIMIT / HARD_TOKEN_LIMIT
         - <SANITIZED_MODEL>_SOFT_TOKEN_LIMIT / HARD_TOKEN_LIMIT  (also accepted)
      2) PROVIDER override env:
         - <PROVIDER>_SOFT_TOKEN_LIMIT / <PROVIDER>_HARD_TOKEN_LIMIT
           (e.g., OPENAI_SOFT_TOKEN_LIMIT)
      3) Global defaults:
         - settings.SOFT_TOKEN_LIMIT / settings.HARD_TOKEN_LIMIT
    Ensures soft <= hard by clamping if misconfigured.
    """
    soft = settings.SOFT_TOKEN_LIMIT
    hard = settings.HARD_TOKEN_LIMIT

    # Provider-level override (OPENAI_*, ANTHROPIC_*, etc.)
    if provider:
        prov = (provider or "").strip().upper()
        soft_prov = _getenv_int_opt(f"{prov}_SOFT_TOKEN_LIMIT")
        hard_prov = _getenv_int_opt(f"{prov}_HARD_TOKEN_LIMIT")
        if soft_prov is not None:
            soft = soft_prov
        if hard_prov is not None:
            hard = hard_prov

    # Model-level override (MODEL_<KEY>_* preferred; <KEY>_* also supported)
    if model:
        key = _sanitize_model_key(model)
        soft_model = _getenv_int_opt(f"MODEL_{key}_SOFT_TOKEN_LIMIT")
        hard_model = _getenv_int_opt(f"MODEL_{key}_HARD_TOKEN_LIMIT")
        if soft_model is None:
            soft_model = _getenv_int_opt(f"{key}_SOFT_TOKEN_LIMIT")
        if hard_model is None:
            hard_model = _getenv_int_opt(f"{key}_HARD_TOKEN_LIMIT")
        if soft_model is not None:
            soft = soft_model
        if hard_model is not None:
            hard = hard_model

    # Safety: maintain invariant soft <= hard
    if soft > hard:
        soft = hard

    return soft, hard

__all__ = ["settings", "_Settings", "get_thresholds"]
