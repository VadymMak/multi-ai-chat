# app/providers/openai_provider.py
from __future__ import annotations

import os
from typing import Any, List, Optional, Dict

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

# ---------------- Settings (optional) ----------------
try:
    from app.config.settings import settings
    _SETTINGS_OK = True
except Exception:
    _SETTINGS_OK = False

# ---------------- Type-safe imports / fallbacks ----------------
try:
    from openai import OpenAI as _RuntimeOpenAIClient  # type: ignore
    from openai import APIError as _RuntimeAPIError  # type: ignore
    from openai import AuthenticationError as _RuntimeAuthError  # type: ignore
    from openai import RateLimitError as _RuntimeRateLimitError  # type: ignore
    _HAVE_OPENAI = True
except Exception:  # pragma: no cover
    _RuntimeOpenAIClient = None  # type: ignore
    _RuntimeAPIError = Exception  # type: ignore
    _RuntimeAuthError = Exception  # type: ignore
    _RuntimeRateLimitError = Exception  # type: ignore
    _HAVE_OPENAI = False

# ---------------- Config ----------------
DEFAULT_MODEL = (
    getattr(settings, "OPENAI_DEFAULT_MODEL", None) if _SETTINGS_OK else None
) or os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")

FALLBACK_MODEL = (
    getattr(settings, "OPENAI_FALLBACK_MODEL", None) if _SETTINGS_OK else None
) or os.getenv("OPENAI_FALLBACK_MODEL", "gpt-4o-mini")

MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "4096"))
TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
TIMEOUT_SECS = float(os.getenv("OPENAI_TIMEOUT", "60"))

# JSON mode default (settings) or env override
JSON_MODE_DEFAULT = (
    bool(getattr(settings, "JSON_MODE_DEFAULT", False)) if _SETTINGS_OK else False
)
JSON_MODE_ENV = (os.getenv("OPENAI_JSON_MODE") or "").strip().lower() in {"1", "true", "yes", "on"}
JSON_MODE = JSON_MODE_DEFAULT or JSON_MODE_ENV

FORCE_TEXT_ONLY = (os.getenv("OPENAI_FORCE_TEXT_RESPONSES") or "").strip().lower() in {"1", "true", "yes", "on"}

_client: Optional[Any] = None  # lazy singleton


def _get_client() -> Any:
    """Lazily create and cache the OpenAI client with disabled proxies."""
    global _client
    _client = None
    
    if _client is not None:
        return _client
    
    if not _HAVE_OPENAI:
        raise RuntimeError("[OpenAI Error] openai package not installed; cannot create client")

    # API key
    api_key = os.getenv("CHATITNOW_API_KEY") or os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        raise RuntimeError("[OpenAI Error] API key not configured (CHATITNOW_API_KEY or OPENAI_API_KEY)")

    base_url = os.getenv("OPENAI_BASE_URL") or None
    organization = os.getenv("OPENAI_ORG") or None
    
    try:
        # Полностью игнорировать системные proxy настройки
        # Используем пустой dict вместо None - это предотвращает автоматическое чтение env
        http_client = httpx.Client(
            timeout=httpx.Timeout(TIMEOUT_SECS, connect=10.0),
            trust_env=False  # КРИТИЧНО: не читать переменные окружения!
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise
    
    try:
        # Создать OpenAI клиент с нашим http_client
        _client = _RuntimeOpenAIClient(
            api_key=api_key,
            base_url=base_url,
            organization=organization,
            http_client=http_client  # Использовать наш клиент без proxy
        )
        
        return _client
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise


def _get_client_with_key(api_key: str) -> Any:
    """Create a NEW OpenAI client with a specific API key (for user BYOK)."""
    if not _HAVE_OPENAI:
        raise RuntimeError("[OpenAI Error] openai package not installed; cannot create client")

    if not api_key:
        raise RuntimeError("[OpenAI Error] API key not provided")

    base_url = os.getenv("OPENAI_BASE_URL") or None
    organization = os.getenv("OPENAI_ORG") or None
    
    try:
        http_client = httpx.Client(
            timeout=httpx.Timeout(TIMEOUT_SECS, connect=10.0),
            trust_env=False
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise
    
    try:
        return _RuntimeOpenAIClient(
            api_key=api_key,
            base_url=base_url,
            organization=organization,
            http_client=http_client
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise


def _normalize_messages(messages: List[dict]) -> List[Dict[str, str]]:
    """Ensure each message has {role, content} and drop empties."""
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


def _should_use_max_completion_tokens(model_name: str) -> bool:
    """
    Reasoning/GPT-5 families often use `max_completion_tokens`.
    Env override: OPENAI_FORCE_COMPLETION_PARAM=max_completion_tokens|max_tokens
    """
    force = (os.getenv("OPENAI_FORCE_COMPLETION_PARAM") or "").strip().lower()
    if force == "max_completion_tokens":
        return True
    if force == "max_tokens":
        return False
    m = (model_name or "").lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4", "gpt-4.1"))


def _supports_temperature(model_name: str) -> bool:
    """Some models ignore temperature—omit when not supported."""
    if (os.getenv("OPENAI_DISABLE_TEMPERATURE") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    m = (model_name or "").lower()
    if m.startswith(("gpt-5", "o1", "o3", "o4", "gpt-4.1")):
        return False
    return True


def _extract_text_from_choice(choice: Any) -> str:
    """
    Pull best-available text from a chat.completions choice:
    - message.content (string or list of parts)
    - function_call.arguments (legacy)
    - tool_calls[0].function.arguments (current)
    """
    try:
        msg = getattr(choice, "message", None) or (isinstance(choice, dict) and choice.get("message"))
        if not msg:
            return ""

        content = getattr(msg, "content", None) or (isinstance(msg, dict) and msg.get("content"))
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, (list, tuple)):
            parts: List[str] = []
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str):
                    parts.append(c["text"])
            if parts:
                return "\n".join(p for p in parts if p.strip()).strip()

        fn_call = getattr(msg, "function_call", None) or (isinstance(msg, dict) and msg.get("function_call"))
        if fn_call:
            args = getattr(fn_call, "arguments", None) or (isinstance(fn_call, dict) and fn_call.get("arguments"))
            if args:
                return str(args).strip()

        tool_calls = getattr(msg, "tool_calls", None) or (isinstance(msg, dict) and msg.get("tool_calls"))
        if tool_calls and isinstance(tool_calls, (list, tuple)) and tool_calls:
            tc0 = tool_calls[0]
            fn = getattr(tc0, "function", None) or (isinstance(tc0, dict) and tc0.get("function"))
            if fn:
                args = getattr(fn, "arguments", None) or (isinstance(fn, dict) and fn.get("arguments"))
                if args:
                    return str(args).strip()
    except Exception:
        pass
    return ""


def _extract_text_from_response(resp: Any) -> str:
    """
    Extract plain text from the Responses API payload:
    resp.output -> list of items with .type == 'message' and content parts
    """
    try:
        output = getattr(resp, "output", None) or getattr(resp, "data", None) or []
        items = output if isinstance(output, list) else []
        for it in items:
            content = getattr(it, "content", None) or (isinstance(it, dict) and it.get("content"))
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if "text" in part and isinstance(part["text"], str):
                            if part["text"].strip():
                                return part["text"].strip()
                        val = part.get("text", {}).get("value") if isinstance(part.get("text"), dict) else None
                        if isinstance(val, str) and val.strip():
                            return val.strip()
        for attr in ("output_text", "text", "content"):
            v = getattr(resp, attr, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
    except Exception:
        pass
    return ""


def _build_messages(msgs: List[dict], sys_prompt: Optional[str], *, force_text_only: bool) -> List[dict]:
    norm = _normalize_messages(msgs)
    sys = (sys_prompt or "").strip()
    if FORCE_TEXT_ONLY or force_text_only:
        extra = " Always respond in plain text. Do not call tools or functions. Do not return JSON unless explicitly requested."
        sys = (sys + extra) if sys else ("You are a helpful assistant." + extra)

    out: List[dict] = []
    if sys:
        out.append({"role": "system", "content": sys})
    out.extend(norm)
    if not out:
        out = [{"role": "user", "content": "[empty]"}]
    return out


def _client_with_timeout(client: Any) -> Any:
    """Prefer with_options(timeout=..); fallback to passing timeout per request."""
    try:
        return client.with_options(timeout=TIMEOUT_SECS)  # type: ignore[attr-defined]
    except Exception:
        return client


def _call_chat_create(
    client: Any,
    *,
    model: str,
    final_messages: List[dict],
    include_temp: bool,
    temp: float,
    out_tokens: int,
    use_completion_param: bool,
    json_mode: bool,
):
    client2 = _client_with_timeout(client)
    kwargs: Dict[str, Any] = {"model": model, "messages": final_messages}
    if include_temp:
        kwargs["temperature"] = temp
    if use_completion_param:
        kwargs["max_completion_tokens"] = out_tokens
    else:
        kwargs["max_tokens"] = out_tokens
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    kwargs["timeout"] = TIMEOUT_SECS
    return client2.chat.completions.create(**kwargs)  # type: ignore[attr-defined]


def _call_responses_create(
    client: Any,
    *,
    model: str,
    final_messages: List[dict],
    include_temp: bool,
    temp: float,
    out_tokens: int,
    use_completion_param: bool,
    json_mode: bool,
):
    """Minimal bridge to Responses API using the same messages."""
    client2 = _client_with_timeout(client)

    def _flatten(mm: List[dict]) -> str:
        parts: List[str] = []
        for m in mm:
            r = m.get("role", "user")
            c = str(m.get("content", "") or "")
            if not c.strip():
                continue
            if r == "system":
                parts.append(f"[system]\n{c}")
            elif r == "assistant":
                parts.append(f"[assistant]\n{c}")
            else:
                parts.append(f"[user]\n{c}")
        return "\n\n".join(parts)

    prompt_text = _flatten(final_messages)
    kwargs: Dict[str, Any] = {
        "model": model,
        "input": prompt_text,
        "timeout": TIMEOUT_SECS,
        "max_output_tokens": out_tokens,  # Responses API param
    }
    if include_temp:
        kwargs["temperature"] = temp
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    return client2.responses.create(**kwargs)  # type: ignore[attr-defined]


@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=1, min=2, max=10))
def ask_openai(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    system_prompt: Optional[str] = None,
    *,
    json_mode: Optional[bool] = None,
    force_text_only: Optional[bool] = None,
    api_key: Optional[str] = None,
) -> str:
    """
    Chat Completions wrapper with adaptors & robust fallbacks:
      • Uses `max_completion_tokens` for reasoning models.
      • Omits `temperature` for models that ignore it.
      • If the API returns an empty content (e.g., tool_calls), try to extract from tool args.
      • If Chat Completions fails due to parameter/API shape, retry via Responses API.
      • If still empty, retry once on FALLBACK_MODEL with a text-only nudge and JSON mode OFF.
    """
    try:
        # Use user-provided API key if available, otherwise use env/cached client
        client = _get_client_with_key(api_key) if api_key else _get_client()
        final_messages = _build_messages(messages, system_prompt, force_text_only=bool(force_text_only))

        # Clamp params
        try:
            temperature = float(temperature)
        except Exception:
            temperature = TEMPERATURE
        temperature = max(0.0, min(2.0, temperature))

        try:
            max_tokens = int(max_tokens)
        except Exception:
            max_tokens = MAX_TOKENS
        max_tokens = max(1, max_tokens)

        use_completion = _should_use_max_completion_tokens(model)
        include_temp = _supports_temperature(model)
        json_mode_flag = JSON_MODE if json_mode is None else bool(json_mode)

        # First attempt: Chat Completions
        resp = None
        try:
            resp = _call_chat_create(
                client,
                model=model,
                final_messages=final_messages,
                include_temp=include_temp,
                temp=temperature,
                out_tokens=max_tokens,
                use_completion_param=use_completion,
                json_mode=json_mode_flag,
            )
        except Exception as e1:
            msg = str(e1).lower()
            param_err = ("unsupported parameter" in msg or "unrecognized request argument" in msg) and \
                        ("max_tokens" in msg or "max_completion_tokens" in msg)
            temp_err = ("unsupported value" in msg and "temperature" in msg) or \
                       ("does not support" in msg and "temperature" in msg)
            responses_hint = any(h in msg for h in [
                "use the responses api",
                "responses api",
                "chat.completions is not supported",
                "this model is only available in the responses api",
            ])

            if param_err or temp_err:
                # Retry Chat after toggling the conflicting param
                try:
                    resp = _call_chat_create(
                        client,
                        model=model,
                        final_messages=final_messages,
                        include_temp=(False if temp_err else include_temp),
                        temp=temperature,
                        out_tokens=max_tokens,
                        use_completion_param=(not use_completion if param_err else use_completion),
                        json_mode=json_mode_flag,
                    )
                except Exception as e2:
                    # If still fails and suggests Responses API, switch over
                    if responses_hint or "responses" in str(e2).lower():
                        try:
                            resp = _call_responses_create(
                                client,
                                model=model,
                                final_messages=final_messages,
                                include_temp=include_temp,
                                temp=temperature,
                                out_tokens=max_tokens,
                                use_completion_param=use_completion,
                                json_mode=json_mode_flag,
                            )
                        except Exception as e3:
                            print(f"❌ [OpenAI] Chat->Responses retry failed. first={e1} second={e2} third={e3}")
                            return f"[OpenAI Error] {e3}"
                    else:
                        print(f"❌ [OpenAI] Retry failed. first={e1} second={e2}")
                        return f"[OpenAI Error] {e2}"
            elif responses_hint:
                try:
                    resp = _call_responses_create(
                        client,
                        model=model,
                        final_messages=final_messages,
                        include_temp=include_temp,
                        temp=temperature,
                        out_tokens=max_tokens,
                        use_completion_param=use_completion,
                        json_mode=json_mode_flag,
                    )
                except Exception as e2:
                    print(f"❌ [OpenAI] Responses API call failed: {e2}")
                    return f"[OpenAI Error] {e2}"
            else:
                print(f"❌ [OpenAI] Call failed: {e1}")
                return f"[OpenAI Error] {e1}"

        # Extract text from either API path
        text = ""
        try:
            if hasattr(resp, "choices"):  # Chat Completions path
                if not getattr(resp, "choices", None):
                    print("⚠️ [OpenAI Warning] Empty response from API")
                    return _fallback_plain_text(client, fallback_messages=final_messages)
                text = _extract_text_from_choice(resp.choices[0]).strip()
            else:  # Responses API path
                text = _extract_text_from_response(resp).strip()
        except Exception:
            text = ""

        if not text:
            print("⚠️ [OpenAI Warning] No text content; trying fallback plain-text pass")
            return _fallback_plain_text(client, fallback_messages=final_messages)

        # Usage log (best effort)
        try:
            usage = getattr(resp, "usage", None)
            if usage:
                total = getattr(usage, "total_tokens", None)
                prompt_toks = getattr(usage, "prompt_tokens", None)
                comp_toks = getattr(usage, "completion_tokens", None)
                print(f"✅ [OpenAI] model={model} out≤{max_tokens} usage total={total} prompt={prompt_toks} completion={comp_toks}")
            else:
                print(f"✅ [OpenAI] model={model} out≤{max_tokens}")
        except Exception:
            pass

        return text

    except _RuntimeAuthError as e:  # type: ignore[name-defined]
        print(f"❌ [OpenAI Auth Error] {e}")
        return f"[OpenAI Error] Invalid API key: {str(e)}"
    except _RuntimeRateLimitError as e:  # type: ignore[name-defined]
        print(f"❌ [OpenAI Rate Limit] {e}")
        return f"[OpenAI Error] Rate limit exceeded: {str(e)}"
    except _RuntimeAPIError as e:  # type: ignore[name-defined]
        print(f"❌ [OpenAI API Error] {e}")
        return f"[OpenAI Error] API failure: {str(e)}"
    except RuntimeError as e:
        print(f"❌ [OpenAI Config Error] {e}")
        return f"[OpenAI Error] {str(e)}"
    except Exception as e:
        print(f"❌ [OpenAI Unexpected Error] {e}")
        return f"[OpenAI Error] {str(e)}"


def _fallback_plain_text(client: Any, *, fallback_messages: List[dict]) -> str:
    """
    One last attempt on a safer chat model with explicit text-only nudge
    and JSON mode disabled, to avoid tool-only outputs.
    """
    try:
        fb_model = FALLBACK_MODEL or "gpt-4o-mini"
        use_completion_fb = _should_use_max_completion_tokens(fb_model)
        include_temp_fb = _supports_temperature(fb_model)

        fb_msgs = list(fallback_messages)
        has_system = any(m.get("role") == "system" for m in fb_msgs)
        if has_system:
            fb_msgs.append({
                "role": "user",
                "content": "Return a concise plain-text answer. Do not call tools/functions."
            })
        else:
            fb_msgs = [{
                "role": "system",
                "content": "You are a helpful assistant. Return a concise plain-text answer. Do not call tools/functions."
            }] + fb_msgs

        client2 = _client_with_timeout(client)
        kwargs: Dict[str, Any] = {"model": fb_model, "messages": fb_msgs, "timeout": TIMEOUT_SECS}
        if include_temp_fb:
            kwargs["temperature"] = TEMPERATURE
        if use_completion_fb:
            kwargs["max_completion_tokens"] = MAX_TOKENS
        else:
            kwargs["max_tokens"] = MAX_TOKENS
        # Disable tool calls to ensure text-only responses
        kwargs["tool_choice"] = "none"

        resp2 = client2.chat.completions.create(**kwargs)  # type: ignore[attr-defined]
        if not resp2 or not getattr(resp2, "choices", None):
            return "[OpenAI Error] Empty response from fallback model"

        text2 = _extract_text_from_choice(resp2.choices[0]).strip()
        if not text2:
            print("⚠️ [OpenAI Warning] Fallback also had no content")
            return "[OpenAI Error] No content in response"
        print(f"✅ [OpenAI] Fallback model={fb_model} produced text")
        return text2
    except Exception as e:
        print(f"❌ [OpenAI Fallback Error] {e}")
        return f"[OpenAI Error] {e}"
