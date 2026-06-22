# app/providers/glm_provider.py
#
# Z.ai GLM provider — Anthropic-SDK compatible endpoint.
# Uses the same wire protocol as Claude but points at api.z.ai.
# Completely isolated from Claude Code / ANTHROPIC_* env vars.
from __future__ import annotations

import os
from typing import Any, List, Optional

import httpx

try:
    from app.config.settings import settings
    _SETTINGS_OK = True
except Exception:
    _SETTINGS_OK = False

try:
    from anthropic import Anthropic
    _HAVE_ANTHROPIC = True
except Exception:
    Anthropic = None  # type: ignore
    _HAVE_ANTHROPIC = False

_DEFAULT_BASE_URL = "https://api.z.ai/api/anthropic"
_DEFAULT_MODEL = "glm-5.2"
MAX_TOKENS = 8192
TEMPERATURE = 0.7
TIMEOUT_SECS = 120.0


def _resolve(attr: str, env_name: str, default: str) -> str:
    if _SETTINGS_OK:
        val = getattr(settings, attr, None)
        if val:
            return val
    return os.getenv(env_name, default)


def _make_client(api_key: str, base_url: str) -> Any:
    if not _HAVE_ANTHROPIC:
        raise RuntimeError("[GLM Error] anthropic package not installed")
    http_client = httpx.Client(
        timeout=httpx.Timeout(timeout=TIMEOUT_SECS, connect=30.0, read=90.0, write=30.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    )
    return Anthropic(api_key=api_key, base_url=base_url, http_client=http_client)


def _normalize_messages(messages: List[dict]) -> List[dict]:
    out: List[dict] = []
    for m in messages:
        if isinstance(m, dict):
            role = str(m.get("role", "user")).strip().lower() or "user"
            content = m.get("content", "")
        else:
            role = "user"
            content = str(m) if m is not None else ""
        content = "" if content is None else str(content)
        if content.strip():
            out.append({"role": role, "content": content})
    if not out:
        out = [{"role": "user", "content": "[empty]"}]
    return out


def ask_glm(
    messages: List[dict],
    model: Optional[str] = None,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    system: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    resolved_api_key = api_key or _resolve("GLM_API_KEY", "GLM_API_KEY", "")
    if not resolved_api_key:
        return "[GLM Error] Missing GLM_API_KEY in environment"

    base_url = _resolve("GLM_BASE_URL", "GLM_BASE_URL", _DEFAULT_BASE_URL)
    resolved_model = model or _resolve("GLM_MODEL", "GLM_MODEL", _DEFAULT_MODEL)

    try:
        client = _make_client(resolved_api_key, base_url)
        normalized = _normalize_messages(messages)
        temperature = max(0.0, min(1.0, float(temperature)))
        max_tokens = max(1, int(max_tokens))

        kwargs: dict = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": normalized,
        }
        if system:
            kwargs["system"] = system

        response = client.messages.create(**kwargs)  # type: ignore[attr-defined]

        content = getattr(response, "content", [])
        if isinstance(content, list) and content:
            first = content[0]
            if hasattr(first, "text"):
                text = str(getattr(first, "text", "")).strip()
            elif isinstance(first, dict) and "text" in first:
                text = str(first["text"]).strip()
            else:
                text = str(first).strip()
        else:
            text = str(content).strip()

        if not text:
            return "[GLM Error] No text content"

        try:
            usage = getattr(response, "usage", None)
            if usage:
                print(f"✅ [GLM] model={resolved_model} in={getattr(usage, 'input_tokens', '?')} out={getattr(usage, 'output_tokens', '?')}")
            else:
                print(f"✅ [GLM] model={resolved_model} max_tokens={max_tokens}")
        except Exception:
            pass

        return text

    except RuntimeError as e:
        print(f"❌ [GLM Config Error] {e}")
        return f"[GLM Error] {str(e)}"
    except Exception as e:
        print(f"❌ [GLM Unexpected Error] {e}")
        return f"[GLM Error] {str(e)}"
