from __future__ import annotations

from typing import Dict, Literal, TypedDict

# Try modern Required/NotRequired; gracefully degrade if unavailable
_HAS_REQ_NOTREQ = True
try:
    from typing import Required, NotRequired  # Python 3.11+
except Exception:  # pragma: no cover
    try:
        from typing_extensions import Required, NotRequired  # type: ignore
    except Exception:  # pragma: no cover
        _HAS_REQ_NOTREQ = False

Provider = Literal["openai", "anthropic"]

if _HAS_REQ_NOTREQ:
    class ModelInfo(TypedDict):
        provider: Required[Provider]
        model: Required[str]
        # Optional per-model overrides used by factory.ask_model(...)
        temperature: NotRequired[float]
        max_tokens: NotRequired[int]
else:
    # Fallback: permissive TypedDict (runtime data still includes provider/model).
    class ModelInfo(TypedDict, total=False):  # type: ignore[misc]
        provider: Provider
        model: str
        temperature: float
        max_tokens: int


# Registry keys (left side) are accepted as `model_key` by your API.
# "provider" and "model" are consumed by the provider wrappers.
MODEL_REGISTRY: Dict[str, ModelInfo] = {
    # ---------------------------------------------------------------------
    # OpenAI
    # ---------------------------------------------------------------------
    "gpt-4o": {
        "provider": "openai",
        "model": "gpt-4o",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "gpt-4o-mini": {  # factory fallback candidate
        "provider": "openai",
        "model": "gpt-4o-mini",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "gpt-4.1-mini": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "gpt-3.5-turbo": {
        "provider": "openai",
        "model": "gpt-3.5-turbo",
        "max_tokens": 4096,
        "temperature": 0.7,
    },

    # Optional GPT-5 family (only if your gateway/account supports them).
    # The factory may omit temperature for "reasoning" families.
    "gpt-5": {
        "provider": "openai",
        "model": "gpt-5",
        "max_tokens": 4096,
    },
    "gpt-5-mini": {  # factory fallback candidate
        "provider": "openai",
        "model": "gpt-5-mini",
        "max_tokens": 4096,
    },
    "gpt-5-nano": {  # factory fallback candidate
        "provider": "openai",
        "model": "gpt-5-nano",
        "max_tokens": 4096,
    },
    "gpt-5-chat": {
        "provider": "openai",
        "model": "gpt-5-chat-latest",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "gpt-5-chat-latest": {
        "provider": "openai",
        "model": "gpt-5-chat-latest",
        "max_tokens": 4096,
        "temperature": 0.7,
    },

    # ---------------------------------------------------------------------
    # Anthropic (Claude)
    # ---------------------------------------------------------------------
    "claude-3-5-sonnet": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    # Factory fallback candidates (small/fast)
    "claude-3-5-haiku-20241022": {
        "provider": "anthropic",
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "claude-3-5-haiku-latest": {  # alias used by factory fallback
        "provider": "anthropic",
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "claude-3-haiku-20240307": {
        "provider": "anthropic",
        "model": "claude-3-haiku-20240307",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "claude-3-haiku": {  # alias used by factory fallback
        "provider": "anthropic",
        "model": "claude-3-haiku-20240307",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    # Alias (full id as key)
    "claude-sonnet-4-20250514": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    # Claude Opus 4 (premium quality)
    "claude-opus-4": {
        "provider": "anthropic",
        "model": "claude-opus-4-20250514",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "claude-opus-4-20250514": {
        "provider": "anthropic",
        "model": "claude-opus-4-20250514",
        "max_tokens": 4096,
        "temperature": 0.7,
    },
}

# Force reload - change this comment to trigger module reload
# Version: 2024-11-17-v2


