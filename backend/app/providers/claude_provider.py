# app/providers/claude_provider.py
from __future__ import annotations

import os
import time
import json
import random
from typing import List, Tuple, Optional, Dict, Any

# Settings (optional)
try:
    from app.config.settings import settings
    _SETTINGS_OK = True
except Exception:
    _SETTINGS_OK = False

# Anthropic SDK
try:
    from anthropic import Anthropic  # type: ignore
    from anthropic import APIError as _AnthropicAPIError  # type: ignore
    _HAVE_ANTHROPIC = True
except Exception:  # pragma: no cover
    Anthropic = None  # type: ignore
    _AnthropicAPIError = Exception  # type: ignore
    _HAVE_ANTHROPIC = False

# ---------------- Config ----------------
DEFAULT_MODEL = (
    getattr(settings, "ANTHROPIC_DEFAULT_MODEL", None) if _SETTINGS_OK else None
) or os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-3-5-sonnet-20241022")

MAX_RETRIES = int(os.getenv("ANTHROPIC_MAX_RETRIES", "3"))
BACKOFF_SEC = float(os.getenv("ANTHROPIC_BACKOFF", "1.0"))
MAX_TOKENS_DEFAULT = int(os.getenv("ANTHROPIC_MAX_TOKENS", "1024"))
TIMEOUT_SECS = float(os.getenv("ANTHROPIC_TIMEOUT", "60"))

# Optional stop sequences (comma-separated)
_STOP_SEQS = [s for s in (os.getenv("ANTHROPIC_STOP") or "").split(",") if s.strip()]

_client: Optional[Any] = None  # lazy singleton


def _get_client() -> Any:
    """Create/cache Anthropic client (supports ANTHROPIC_BASE_URL)."""
    global _client
    if _client is not None:
        return _client

    if not _HAVE_ANTHROPIC:
        raise RuntimeError("[Claude Error] anthropic package not installed; cannot create client")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("[Claude Error] Missing ANTHROPIC_API_KEY in environment")

    base_url = os.getenv("ANTHROPIC_BASE_URL") or None
    _client = Anthropic(api_key=api_key, base_url=base_url)  # type: ignore[call-arg]
    try:
        _client = _client.with_options(timeout=TIMEOUT_SECS)  # type: ignore[attr-defined]
    except Exception:
        pass
    return _client


def _normalize_messages(messages: List[dict]) -> List[Dict[str, str]]:
    """Ensure {role, content}; keep only user/assistant/system; drop empties."""
    out: List[Dict[str, str]] = []
    if not isinstance(messages, list):
        messages = []
    for m in messages:
        if isinstance(m, dict):
            role = str(m.get("role", "user")).strip().lower() or "user"
            content = m.get("content", "")
        else:
            role = "user"
            content = str(m) if m is not None else ""
        content = "" if content is None else str(content)
        if content.strip() and role in {"user", "assistant", "system"}:
            out.append({"role": role, "content": content})
    return out


def _clean_history(raw: List[dict]) -> Tuple[List[dict], Optional[str]]:
    """Strip invalid entries, collect a single system message, ensure last is user."""
    norm = _normalize_messages(raw)
    clean: List[dict] = []
    system_msg: Optional[str] = None

    for msg in norm:
        role = msg["role"]
        content = (msg["content"] or "").strip()
        if role == "system":
            if content:
                system_msg = content  # keep last system seen
            continue
        if not content or content.startswith("[Claude Error]"):
            continue
        if role in {"user", "assistant"}:
            clean.append({"role": role, "content": content})

    if not clean or clean[-1]["role"] != "user":
        clean.append({"role": "user", "content": "Please respond to the previous message with a concise plain-text answer."})
    # keep most recent ~6 turns (cheap safety)
    return clean[-6:], system_msg


def _to_claude_messages(history: List[dict]) -> List[Dict[str, Any]]:
    """Convert [{'role','content'}] → Anthropic message blocks."""
    final: List[Dict[str, Any]] = []
    for msg in history:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        final.append({"role": role, "content": [{"type": "text", "text": content}]})
    return final


def _extract_text(response: Any) -> str:
    """Safely pull text from Claude blocks."""
    try:
        blocks = getattr(response, "content", None)
        if not isinstance(blocks, list):
            return ""
        parts: List[str] = []
        for b in blocks:
            # SDK v1: each block has .type and .text
            if getattr(b, "type", None) == "text":
                txt = getattr(b, "text", "") or ""
                if txt:
                    parts.append(str(txt))
        return "\n".join(p.strip() for p in parts if p.strip()).strip()
    except Exception:
        return ""


def _is_overloaded_error(e: Exception) -> bool:
    s = str(e).lower()
    return (
        "overloaded" in s
        or "status code: 529" in s
        or "http/1.1 529" in s
        or "code: 529" in s
        or "status: 529" in s
        or "reduce your request rate" in s
    )


def ask_claude(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    system: Optional[str] = None,
    memory: Optional[List[dict]] = None,
    temperature: float = 0.7,
    *,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Anthropic Messages API wrapper with FAST overload short-circuit.
    Returns plain text on success, or:
      • '[Claude Overloaded] ...'  ← factory uses this to fast-fallback
      • '[Claude Error] ...'
    """
    # 0) Build client
    try:
        client = _get_client()
    except Exception as e:
        print(f"❌ [Claude] Client init failed: {e}")
        return f"[Claude Error] {e}"

    # 1) Build history
    if memory and isinstance(memory, list):
        history = _normalize_messages(memory)
        inferred_system = None
    else:
        history, inferred_system = _clean_history(messages)

    if not history:
        history = [{"role": "user", "content": "Hello. Please respond with a concise plain-text answer."}]

    final_messages = _to_claude_messages(history)
    if not final_messages:
        final_messages = [{"role": "user", "content": [{"type": "text", "text": "Hello. Please respond."}]}]

    system_prompt = (system or inferred_system or "You are a helpful assistant.").strip()

    # 2) Clamp params
    try:
        temperature = float(temperature)
    except Exception:
        temperature = 0.7
    temperature = max(0.0, min(1.0, temperature))

    out_tokens = int(max_tokens if max_tokens is not None else MAX_TOKENS_DEFAULT)
    out_tokens = max(1, out_tokens)

    kwargs: Dict[str, Any] = {
        "model": model,
        "max_tokens": out_tokens,
        "temperature": temperature,
        "messages": final_messages,
        "system": system_prompt,
    }
    if _STOP_SEQS:
        kwargs["stop_sequences"] = _STOP_SEQS

    # 3) Call with bounded retries; short-circuit overload
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Minimal payload log (no secrets / truncation)
            try:
                to_log = {
                    "model": kwargs["model"],
                    "max_tokens": kwargs["max_tokens"],
                    "temperature": kwargs["temperature"],
                    "system": (system_prompt[:300] if system_prompt else None),
                    "messages": [
                        {"role": m["role"], "content": [{"type": "text", "text": c["text"][:200]} for c in m["content"]]}
                        for m in kwargs["messages"]
                    ],
                }
                print("📅 [Claude] Sending message payload:")
                print((json.dumps(to_log, indent=2)[:1200] + "..."))
            except Exception:
                pass

            response: Any = client.messages.create(**kwargs)
            text = _extract_text(response)
            if not text:
                raise _AnthropicAPIError("Claude returned empty response")  # type: ignore[arg-type]
            print(f"✅ [Claude] model={model} temp={temperature} max_tok={out_tokens}")
            return text

        except _AnthropicAPIError as ae:  # type: ignore[misc]
            if _is_overloaded_error(ae):
                # FAST PATH for factory fallback
                print("⚠️ [Claude] Overloaded → short-circuiting for factory fallback")
                return "[Claude Overloaded] " + str(ae)

            if attempt < MAX_RETRIES:
                delay = BACKOFF_SEC * (2 ** (attempt - 1)) * (1 + random.uniform(0.1, 0.5))
                print(f"🔁 [Claude] Transient error, retrying ({attempt}/{MAX_RETRIES}) in {delay:.2f}s ...")
                time.sleep(delay)
                continue

            print(f"❌ [Claude] Anthropic API error: {ae}")
            return f"[Claude Error] {ae}"

        except Exception as e:
            print(f"❌ [Claude] Unexpected error: {e}")
            return f"[Claude Error] {e}"

    return "[Claude Overloaded] Exhausted retries without success"
