# app/providers/claude_provider.py
from __future__ import annotations
import os
from typing import Any, List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

# ---------------- Settings (optional) ----------------
try:
    from app.config.settings import settings
    _SETTINGS_OK = True
except Exception:
    _SETTINGS_OK = False

# ---------------- Type-safe imports / fallbacks ----------------
try:
    from anthropic import Anthropic  # type: ignore
    from anthropic import APIError as _AnthropicAPIError  # type: ignore
    from anthropic import RateLimitError as _AnthropicRateLimitError  # type: ignore
    _HAVE_ANTHROPIC = True
except Exception:  # pragma: no cover
    Anthropic = None  # type: ignore
    _AnthropicAPIError = Exception  # type: ignore
    _AnthropicRateLimitError = Exception  # type: ignore
    _HAVE_ANTHROPIC = False

# ---------------- Config ----------------
DEFAULT_MODEL = (
    getattr(settings, "ANTHROPIC_DEFAULT_MODEL", None) if _SETTINGS_OK else None
) or os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-sonnet-4-20250514")

FALLBACK_MODEL = (
    getattr(settings, "ANTHROPIC_FALLBACK_MODEL", None) if _SETTINGS_OK else None
) or os.getenv("ANTHROPIC_FALLBACK_MODEL", "claude-3-5-haiku-latest")

MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "8192"))
TEMPERATURE = float(os.getenv("ANTHROPIC_TEMPERATURE", "0.7"))
MAX_RETRIES = int(os.getenv("ANTHROPIC_MAX_RETRIES", "3"))
TIMEOUT_SECS = float(os.getenv("ANTHROPIC_TIMEOUT", "120"))

_client: Optional[Any] = None


def _get_client() -> Any:
    """
    Create/cache Anthropic client with optimized timeouts.
    Allows system proxy/network settings (trust_env=True by default).
    """
    global _client
    if _client is not None:
        return _client
    
    if not _HAVE_ANTHROPIC:
        raise RuntimeError(
            "[Claude Error] anthropic package not installed; cannot create client"
        )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "[Claude Error] Missing ANTHROPIC_API_KEY in environment"
        )

    base_url = os.getenv("ANTHROPIC_BASE_URL") or None

    # ✅ Create client with generous timeouts for high-latency connections
    # NOTE: We do NOT use trust_env=False to allow system proxy settings
    try:
        import httpx
        
        http_client = httpx.Client(
            timeout=httpx.Timeout(
                timeout=120.0,   # Total timeout: 2 minutes
                connect=30.0,    # Connect: 30 seconds (was causing issues at 10s)
                read=90.0,       # Read: 90 seconds
                write=30.0       # Write: 30 seconds
            ),
            # trust_env=True by default - allows system proxy/network settings
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=30.0
            )
        )
        
        _client = Anthropic(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            max_retries=3,  # Built-in retries
        )  # type: ignore[call-arg]
        
    except Exception as e:
        # Fallback to default client if httpx config fails
        print(f"⚠️ [Claude] Failed to create custom http_client: {e}")
        print(f"⚠️ [Claude] Falling back to default client")
        _client = Anthropic(api_key=api_key, base_url=base_url)  # type: ignore[call-arg]
        
        # Try to apply timeout via with_options
        try:
            _client = _client.with_options(timeout=TIMEOUT_SECS)  # type: ignore[attr-defined]
        except Exception:
            pass

    return _client


def _get_client_with_key(api_key: str) -> Any:
    """Create a NEW Anthropic client with a specific API key (for user BYOK)."""
    if not _HAVE_ANTHROPIC:
        raise RuntimeError(
            "[Claude Error] anthropic package not installed; cannot create client"
        )

    if not api_key:
        raise RuntimeError("[Claude Error] API key not provided")

    base_url = os.getenv("ANTHROPIC_BASE_URL") or None

    try:
        import httpx
        
        http_client = httpx.Client(
            timeout=httpx.Timeout(
                timeout=120.0,
                connect=30.0,
                read=90.0,
                write=30.0
            ),
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=30.0
            )
        )
        
        return Anthropic(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            max_retries=3,
        )  # type: ignore[call-arg]
        
    except Exception as e:
        print(f"⚠️ [Claude] Failed to create custom http_client: {e}")
        print(f"⚠️ [Claude] Falling back to default client")
        client = Anthropic(api_key=api_key, base_url=base_url)  # type: ignore[call-arg]
        
        try:
            return client.with_options(timeout=TIMEOUT_SECS)  # type: ignore[attr-defined]
        except Exception:
            return client


def _normalize_messages(messages: List[dict]) -> List[dict]:
    """Ensure each message has {role, content} and drop empties."""
    out: List[dict] = []
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


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    reraise=True
)
def ask_claude(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    system: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    """
    Chat wrapper with robust fallbacks and retry logic.
    """
    try:
        # Use user-provided API key if available, otherwise use env/cached client
        client = _get_client_with_key(api_key) if api_key else _get_client()
        normalized = _normalize_messages(messages)
        
        # Clamp params
        try:
            temperature = float(temperature)
        except Exception:
            temperature = TEMPERATURE
        temperature = max(0.0, min(1.0, temperature))

        try:
            max_tokens = int(max_tokens)
        except Exception:
            max_tokens = MAX_TOKENS
        max_tokens = max(1, max_tokens)

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": normalized,
        }
        if system:
            kwargs["system"] = system

        response = client.messages.create(**kwargs)  # type: ignore[attr-defined]

        if not response or not getattr(response, "content", None):
            print("⚠️ [Claude Warning] Empty response from API")
            return "[Claude Error] No content in response"

        # Extract text
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
            print("⚠️ [Claude Warning] No text content in response")
            return "[Claude Error] No text content"

        # Usage log (best effort)
        try:
            usage = getattr(response, "usage", None)
            if usage:
                in_toks = getattr(usage, "input_tokens", None)
                out_toks = getattr(usage, "output_tokens", None)
                print(f"✅ [Claude] model={model} max_tokens={max_tokens} usage in={in_toks} out={out_toks}")
            else:
                print(f"✅ [Claude] model={model} max_tokens={max_tokens}")
        except Exception:
            pass

        return text

    except _AnthropicRateLimitError as e:  # type: ignore[name-defined]
        print(f"❌ [Claude Rate Limit] {e}")
        return f"[Claude Error] Rate limit exceeded: {str(e)}"
    except _AnthropicAPIError as e:  # type: ignore[name-defined]
        print(f"❌ [Claude API Error] {e}")
        return f"[Claude Error] API failure: {str(e)}"
    except RuntimeError as e:
        print(f"❌ [Claude Config Error] {e}")
        return f"[Claude Error] {str(e)}"
    except Exception as e:
        print(f"❌ [Claude Unexpected Error] {e}")
        return f"[Claude Error] {str(e)}"
