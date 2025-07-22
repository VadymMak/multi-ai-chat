# app/providers/factory.py
from __future__ import annotations

import os
from typing import List, Optional, Dict, Any

from app.config.settings import settings
from app.config.model_registry import MODEL_REGISTRY
from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude


def _normalize_messages(messages: List[dict]) -> List[Dict[str, str]]:
    """Ensure every item has {role, content}, drop empties."""
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
        if content.strip():
            out.append({"role": role, "content": content})

    if not out:
        out = [{"role": "user", "content": "[empty]"}]
    return out


def _ensure_user_last(msgs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Claude/OpenAI respond best when the last role is 'user'."""
    if not msgs:
        return [{"role": "user", "content": "Hello"}]
    if msgs[-1]["role"] != "user":
        msgs = msgs + [{"role": "user", "content": "Please continue with a concise plain text answer."}]
    return msgs


def _is_bad(answer: Optional[str]) -> bool:
    """Treat empty/error/overload responses as bad."""
    if not answer or not str(answer).strip():
        return True
    s = str(answer).strip()
    low = s.lower()
    if s.startswith("[OpenAI Error]") or s.startswith("[Claude Error]") or s.startswith("[Claude Overloaded]"):
        return True
    if "overloaded" in low:
        return True
    return False


def _is_overloaded(answer: Optional[str]) -> bool:
    if not answer:
        return False
    return "overloaded" in str(answer).lower()


def _registry_key_for_model_name(model_name: Optional[str]) -> Optional[str]:
    if not model_name:
        return None
    for k, v in MODEL_REGISTRY.items():
        if v.get("model") == model_name:
            return k
    return None


def _fallback_key_for_provider(provider: str) -> Optional[str]:
    """
    Prefer explicit env keys; otherwise:
    - try settings fallback MODEL NAME → map to registry key
    - else choose a small model from the registry by heuristic
    NOTE: OPENAI_FALLBACK_KEY / ANTHROPIC_FALLBACK_KEY must be registry keys.
    """
    p = (provider or "").lower()
    if p == "openai":
        env_key = os.getenv("OPENAI_FALLBACK_KEY")
        if env_key and env_key in MODEL_REGISTRY:
            return env_key
        # settings fallback by model name → to registry key
        name = getattr(settings, "OPENAI_FALLBACK_MODEL", None)
        key = _registry_key_for_model_name(name)
        if key:
            return key
        for guess in ("gpt-4o-mini", "gpt-4o", "gpt-5-mini", "gpt-5-nano"):
            if guess in MODEL_REGISTRY:
                return guess
        return None
    if p == "anthropic":
        env_key = os.getenv("ANTHROPIC_FALLBACK_KEY")
        if env_key and env_key in MODEL_REGISTRY:
            return env_key
        name = getattr(settings, "ANTHROPIC_FALLBACK_MODEL", None)
        key = _registry_key_for_model_name(name)
        if key:
            return key
        for guess in ("claude-3-haiku", "claude-3-haiku-20240307", "claude-3-5-haiku-latest"):
            if guess in MODEL_REGISTRY:
                return guess
        return None
    return None


# ---- OpenAI reasoning-family helpers (omit temperature if configured) ----
_OMIT_TEMP_FOR_REASONING = bool(getattr(settings, "OMIT_TEMPERATURE_FOR_REASONING", True))

def _is_reasoning_model(model: str) -> bool:
    """Cheap check for OpenAI 'reasoning' families."""
    m = (model or "").lower()
    # extend as needed
    return any(tag in m for tag in ("gpt-5", "o4", "o3", "reasoning"))


def ask_model(
    messages: List[dict],
    model_key: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """
    Unified LLM caller. Picks provider+model via registry key and adds resilience:
      • ensures last turn is a 'user' message
      • quick fallback on Anthropic overload (529)
      • single repair retry for other failure modes
      • provider-specific registry fallback if needed
      • (OpenAI) optionally omits temperature for reasoning families
    """
    # Resolve primary registry entry
    requested_key = (model_key or settings.DEFAULT_MODEL) or ""
    info = MODEL_REGISTRY.get(requested_key)
    if not info:
        fallback_key = settings.DEFAULT_MODEL
        info = MODEL_REGISTRY.get(fallback_key)
        print(f"⚠️ Unknown model_key '{requested_key}'. Falling back to '{fallback_key}'.")
        if not info:
            raise RuntimeError("MODEL_REGISTRY missing DEFAULT_MODEL mapping")

    provider = info["provider"]
    model = info["model"]
    temp = float(info.get("temperature", temperature))
    out_tokens = int(info.get("max_tokens", max_tokens))

    norm_messages = _ensure_user_last(_normalize_messages(messages))
    sys_prompt = (system_prompt or "").strip() or None

    print(f"🧩 ask_model → provider={provider} model={model} key={requested_key or settings.DEFAULT_MODEL}")

    # ---- attempt #1
    if provider == "openai":
        # Build kwargs so we can *omit* temperature for reasoning families safely
        openai_kwargs: Dict[str, Any] = {
            "messages": norm_messages,
            "model": model,
            "max_tokens": out_tokens,
            "system_prompt": sys_prompt,
        }
        if not (_OMIT_TEMP_FOR_REASONING and _is_reasoning_model(model)):
            openai_kwargs["temperature"] = temp  # include temp normally
        answer = ask_openai(**openai_kwargs)
    elif provider == "anthropic":
        answer = ask_claude(
            messages=norm_messages,
            model=model,
            system=sys_prompt,
            temperature=temp,
        )
    else:
        raise RuntimeError(f"Unsupported provider '{provider}' for model_key '{requested_key}'")

    # Immediate fast-fallback on Anthropic overload (avoid looping)
    if provider == "anthropic" and _is_overloaded(answer):
        fb_key = _fallback_key_for_provider(provider)
        if fb_key and fb_key in MODEL_REGISTRY:
            fb = MODEL_REGISTRY[fb_key]
            print(f"🛟 Anthropic overloaded → switching immediately to fallback '{fb_key}' ({fb['model']})")
            return ask_claude(
                messages=norm_messages,
                model=fb["model"],
                system=sys_prompt,
                temperature=float(fb.get("temperature", temp)),
            )

    if not _is_bad(answer):
        return str(answer).strip()

    # ---- attempt #2: single repair retry (same model)
    print(f"🔁 First response unsatisfactory from {provider}. Retrying same model with repair hint.")
    repaired = norm_messages + [{"role": "user", "content": "Respond with a short plain text answer only."}]
    if provider == "openai":
        openai_kwargs2: Dict[str, Any] = {
            "messages": repaired,
            "model": model,
            "max_tokens": out_tokens,
            "system_prompt": sys_prompt,
        }
        if not (_OMIT_TEMP_FOR_REASONING and _is_reasoning_model(model)):
            openai_kwargs2["temperature"] = temp
        answer2 = ask_openai(**openai_kwargs2)
    else:
        answer2 = ask_claude(
            messages=repaired,
            model=model,
            system=sys_prompt,
            temperature=temp,
        )

    if provider == "anthropic" and _is_overloaded(answer2):
        fb_key = _fallback_key_for_provider(provider)
        if fb_key and fb_key in MODEL_REGISTRY:
            fb = MODEL_REGISTRY[fb_key]
            print(f"🛟 Anthropic overloaded (retry) → switching to fallback '{fb_key}' ({fb['model']})")
            return ask_claude(
                messages=repaired,
                model=fb["model"],
                system=sys_prompt,
                temperature=float(fb.get("temperature", temp)),
            )

    if not _is_bad(answer2):
        return str(answer2).strip()

    # ---- attempt #3: provider-level fallback model
    fb_key = _fallback_key_for_provider(provider)
    if fb_key and fb_key in MODEL_REGISTRY:
        fb = MODEL_REGISTRY[fb_key]
        print(f"🛟 Switching to provider fallback '{fb_key}' → model={fb['model']}")
        if provider == "openai":
            openai_kwargs3: Dict[str, Any] = {
                "messages": repaired,
                "model": fb["model"],
                "max_tokens": int(fb.get("max_tokens", out_tokens)),
                "system_prompt": sys_prompt,
            }
            if not (_OMIT_TEMP_FOR_REASONING and _is_reasoning_model(fb["model"])):
                openai_kwargs3["temperature"] = float(fb.get("temperature", temp))
            answer3 = ask_openai(**openai_kwargs3)
        else:
            answer3 = ask_claude(
                messages=repaired,
                model=fb["model"],
                system=sys_prompt,
                temperature=float(fb.get("temperature", temp)),
            )
        if not _is_bad(answer3):
            return str(answer3).strip()

    print(f"❌ Fallbacks exhausted for provider={provider}. Returning guarded error text.")
    return f"[{provider.capitalize()} Error] Unable to produce a text answer right now."
