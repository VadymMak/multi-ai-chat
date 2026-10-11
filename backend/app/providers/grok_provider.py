"""
xAI Grok provider — OpenAI-compatible via https://api.x.ai/v1.

Reads GROK_API_KEY from settings only (never logs or exposes it).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

try:
    from app.config.settings import settings
    _SETTINGS_OK = True
except Exception:
    _SETTINGS_OK = False

try:
    from openai import OpenAI as _XAI_Client
    _HAVE_OPENAI = True
except Exception:
    _XAI_Client = None  # type: ignore
    _HAVE_OPENAI = False

_BASE_URL = "https://api.x.ai/v1"
_TIMEOUT  = 30.0


def _get_key() -> str:
    key = ""
    if _SETTINGS_OK:
        key = getattr(settings, "GROK_API_KEY", "") or ""
    if not key:
        key = os.getenv("GROK_API_KEY", "") or ""
    return key


def ask_grok(
    messages: List[dict],
    model: str = "grok-4.3",
    system: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    api_key: Optional[str] = None,
) -> str:
    """
    Call xAI Grok via the OpenAI-compatible chat/completions endpoint.

    Raises RuntimeError if GROK_API_KEY is not configured.
    Never logs the key.
    """
    if not _HAVE_OPENAI:
        raise RuntimeError("[Grok Error] openai package not installed")

    key = api_key or _get_key()
    if not key:
        raise RuntimeError("[Grok Error] GROK_API_KEY not configured")

    client = _XAI_Client(
        api_key=key,
        base_url=_BASE_URL,
        http_client=httpx.Client(
            timeout=httpx.Timeout(_TIMEOUT, connect=10.0),
            trust_env=False,
        ),
    )

    # Build message list (system prepended if provided)
    final: List[Dict[str, Any]] = []
    if system and system.strip():
        final.append({"role": "system", "content": system.strip()})
    for m in messages:
        role = str((m.get("role") or "user")).strip().lower() or "user"
        content = str(m.get("content") or "")
        if content.strip():
            final.append({"role": role, "content": content})
    if not final:
        final = [{"role": "user", "content": "[empty]"}]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=final,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = resp.choices[0].message.content or ""
        return text.strip()
    except Exception as exc:
        return f"[Grok Error] {exc}"


def ask_grok_with_usage(
    messages: List[dict],
    model: str = "grok-4.3",
    system: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    api_key: Optional[str] = None,
) -> "tuple[str, int, int]":
    """Single-shot call → (text, input_tokens, output_tokens). No retry or fallback."""
    if not _HAVE_OPENAI:
        raise RuntimeError("[Grok Error] openai package not installed")
    key = api_key or _get_key()
    if not key:
        raise RuntimeError("[Grok Error] GROK_API_KEY not configured")
    client = _XAI_Client(
        api_key=key,
        base_url=_BASE_URL,
        http_client=httpx.Client(
            timeout=httpx.Timeout(_TIMEOUT, connect=10.0),
            trust_env=False,
        ),
    )
    final: List[Dict[str, Any]] = []
    if system and system.strip():
        final.append({"role": "system", "content": system.strip()})
    for m in messages:
        role = str((m.get("role") or "user")).strip().lower() or "user"
        content = str(m.get("content") or "")
        if content.strip():
            final.append({"role": role, "content": content})
    if not final:
        final = [{"role": "user", "content": "[empty]"}]
    resp = client.chat.completions.create(
        model=model, messages=final, max_tokens=max_tokens, temperature=temperature,
    )
    text = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    in_toks = int(getattr(usage, "prompt_tokens", 0) or 0)
    out_toks = int(getattr(usage, "completion_tokens", 0) or 0)
    return text.strip(), in_toks, out_toks
