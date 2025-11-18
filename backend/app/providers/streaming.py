# app/providers/streaming.py
"""
Async streaming versions of OpenAI and Claude providers.
Yields text chunks as they arrive using Server-Sent Events.
"""
from __future__ import annotations

import os
from typing import AsyncIterator, List, Optional, Dict, Any

import httpx

# ---------------- Settings (optional) ----------------
try:
    from app.config.settings import settings
    _SETTINGS_OK = True
except Exception:
    _SETTINGS_OK = False

# ---------------- Type-safe imports / fallbacks ----------------
try:
    from openai import AsyncOpenAI  # type: ignore
    from openai import APIError as _OpenAIAPIError  # type: ignore
    from openai import AuthenticationError as _OpenAIAuthError  # type: ignore
    from openai import RateLimitError as _OpenAIRateLimitError  # type: ignore
    _HAVE_OPENAI = True
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore
    _OpenAIAPIError = Exception  # type: ignore
    _OpenAIAuthError = Exception  # type: ignore
    _OpenAIRateLimitError = Exception  # type: ignore
    _HAVE_OPENAI = False

try:
    from anthropic import AsyncAnthropic  # type: ignore
    from anthropic import APIError as _AnthropicAPIError  # type: ignore
    _HAVE_ANTHROPIC = True
except Exception:  # pragma: no cover
    AsyncAnthropic = None  # type: ignore
    _AnthropicAPIError = Exception  # type: ignore
    _HAVE_ANTHROPIC = False

# ---------------- OpenAI Config ----------------
OPENAI_DEFAULT_MODEL = (
    getattr(settings, "OPENAI_DEFAULT_MODEL", None) if _SETTINGS_OK else None
) or os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")

OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "4096"))
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
OPENAI_TIMEOUT_SECS = float(os.getenv("OPENAI_TIMEOUT", "60"))

# ---------------- Claude Config ----------------
ANTHROPIC_DEFAULT_MODEL = (
    getattr(settings, "ANTHROPIC_DEFAULT_MODEL", None) if _SETTINGS_OK else None
) or os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-sonnet-4-20250514")

ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "8192"))
ANTHROPIC_TIMEOUT_SECS = float(os.getenv("ANTHROPIC_TIMEOUT", "60"))

# Lazy singletons
_openai_async_client: Optional[Any] = None
_claude_async_client: Optional[Any] = None


def _get_openai_async_client() -> Any:
    """Lazily create and cache the AsyncOpenAI client."""
    global _openai_async_client

    if _openai_async_client is not None:
        return _openai_async_client

    if not _HAVE_OPENAI:
        raise RuntimeError("[OpenAI Streaming Error] openai package not installed")

    api_key = os.getenv("CHATITNOW_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("[OpenAI Streaming Error] API key not configured")

    base_url = os.getenv("OPENAI_BASE_URL") or None
    organization = os.getenv("OPENAI_ORG") or None

    try:
        # Create httpx client without proxy
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(OPENAI_TIMEOUT_SECS, connect=10.0),
            trust_env=False  # Don't read proxy from environment
        )

        _openai_async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            organization=organization,
            http_client=http_client
        )

        return _openai_async_client

    except Exception as e:
        print(f"❌ [OpenAI Streaming] Client initialization failed: {e}")
        raise


def _get_claude_async_client() -> Any:
    """Lazily create and cache the AsyncAnthropic client."""
    global _claude_async_client

    if _claude_async_client is not None:
        return _claude_async_client

    if not _HAVE_ANTHROPIC:
        raise RuntimeError("[Claude Streaming Error] anthropic package not installed")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("[Claude Streaming Error] Missing ANTHROPIC_API_KEY")

    base_url = os.getenv("ANTHROPIC_BASE_URL") or None

    try:
        _claude_async_client = AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=ANTHROPIC_TIMEOUT_SECS
        )
        return _claude_async_client

    except Exception as e:
        print(f"❌ [Claude Streaming] Client initialization failed: {e}")
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
    """Determine if model uses max_completion_tokens parameter."""
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


async def stream_openai(
    messages: List[dict],
    model: str = OPENAI_DEFAULT_MODEL,
    temperature: float = OPENAI_TEMPERATURE,
    max_tokens: int = OPENAI_MAX_TOKENS,
    system_prompt: Optional[str] = None,
) -> AsyncIterator[str]:
    """
    Async streaming version of ask_openai().
    
    Yields text chunks as they arrive from OpenAI's streaming API.
    Reuses same API key logic from openai_provider.py.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        model: OpenAI model name
        temperature: Temperature for generation (0.0-2.0)
        max_tokens: Maximum tokens to generate
        system_prompt: Optional system prompt to prepend
        
    Yields:
        str: Text chunks as they arrive from the API
        
    Raises:
        RuntimeError: If OpenAI client cannot be initialized
    """
    try:
        client = _get_openai_async_client()
        
        # Normalize and build messages
        norm_messages = _normalize_messages(messages)
        final_messages: List[Dict[str, str]] = []
        
        if system_prompt and system_prompt.strip():
            final_messages.append({"role": "system", "content": system_prompt.strip()})
        
        final_messages.extend(norm_messages)
        
        if not final_messages:
            final_messages = [{"role": "user", "content": "[empty]"}]
        
        # Clamp parameters
        try:
            temperature = float(temperature)
        except Exception:
            temperature = OPENAI_TEMPERATURE
        temperature = max(0.0, min(2.0, temperature))
        
        try:
            max_tokens = int(max_tokens)
        except Exception:
            max_tokens = OPENAI_MAX_TOKENS
        max_tokens = max(1, max_tokens)
        
        # Determine which parameters to use
        use_completion_param = _should_use_max_completion_tokens(model)
        include_temp = _supports_temperature(model)
        
        # Build kwargs for streaming
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": final_messages,
            "stream": True,
        }
        
        if include_temp:
            kwargs["temperature"] = temperature
            
        if use_completion_param:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
        
        print(f"🌊 [OpenAI Streaming] Starting stream for model={model}")
        
        # Create streaming request
        stream = await client.chat.completions.create(**kwargs)
        
        # Iterate through chunks
        async for chunk in stream:
            if not chunk.choices:
                continue
                
            delta = chunk.choices[0].delta
            
            # Extract content from delta
            content = getattr(delta, "content", None)
            if content:
                yield content
        
        print(f"✅ [OpenAI Streaming] Stream completed for model={model}")
        
    except _OpenAIAuthError as e:  # type: ignore
        error_msg = f"[OpenAI Streaming Auth Error] {e}"
        print(f"❌ {error_msg}")
        yield error_msg
        
    except _OpenAIRateLimitError as e:  # type: ignore
        error_msg = f"[OpenAI Streaming Rate Limit] {e}"
        print(f"❌ {error_msg}")
        yield error_msg
        
    except _OpenAIAPIError as e:  # type: ignore
        error_msg = f"[OpenAI Streaming API Error] {e}"
        print(f"❌ {error_msg}")
        yield error_msg
        
    except RuntimeError as e:
        error_msg = f"[OpenAI Streaming Config Error] {e}"
        print(f"❌ {error_msg}")
        yield error_msg
        
    except Exception as e:
        error_msg = f"[OpenAI Streaming Error] {e}"
        print(f"❌ {error_msg}")
        yield error_msg


async def stream_claude(
    messages: List[dict],
    model: str = ANTHROPIC_DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = ANTHROPIC_MAX_TOKENS,
    system: Optional[str] = None,
) -> AsyncIterator[str]:
    """
    Async streaming version of ask_claude().
    
    Yields text chunks as they arrive from Claude's streaming API.
    Reuses same API key logic from claude_provider.py.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        model: Claude model name
        temperature: Temperature for generation (0.0-1.0)
        max_tokens: Maximum tokens to generate
        system: Optional system prompt
        
    Yields:
        str: Text chunks as they arrive from the API
        
    Raises:
        RuntimeError: If Claude client cannot be initialized
    """
    try:
        client = _get_claude_async_client()
        
        # Normalize messages
        norm_messages = _normalize_messages(messages)
        
        # Convert to Claude format
        claude_messages: List[Dict[str, Any]] = []
        for msg in norm_messages:
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            
            # Skip system messages (they go in system parameter)
            if role == "system":
                continue
                
            if role in {"user", "assistant"} and content:
                claude_messages.append({
                    "role": role,
                    "content": [{"type": "text", "text": content}]
                })
        
        # Ensure last message is from user
        if not claude_messages or claude_messages[-1]["role"] != "user":
            claude_messages.append({
                "role": "user",
                "content": [{"type": "text", "text": "Please respond to the previous message."}]
            })
        
        # System prompt
        system_prompt = (system or "You are a helpful assistant.").strip()
        
        # Clamp parameters
        try:
            temperature = float(temperature)
        except Exception:
            temperature = 0.7
        temperature = max(0.0, min(1.0, temperature))
        
        try:
            max_tokens = int(max_tokens)
        except Exception:
            max_tokens = ANTHROPIC_MAX_TOKENS
        max_tokens = max(1, max_tokens)
        
        print(f"🌊 [Claude Streaming] Starting stream for model={model}")
        
        # Create streaming request
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=claude_messages,
            system=system_prompt,
        ) as stream:
            # Iterate through text chunks
            async for text in stream.text_stream:
                if text:
                    yield text
        
        print(f"✅ [Claude Streaming] Stream completed for model={model}")
        
    except _AnthropicAPIError as e:  # type: ignore
        error_msg = f"[Claude Streaming API Error] {e}"
        print(f"❌ {error_msg}")
        yield error_msg
        
    except RuntimeError as e:
        error_msg = f"[Claude Streaming Config Error] {e}"
        print(f"❌ {error_msg}")
        yield error_msg
        
    except Exception as e:
        error_msg = f"[Claude Streaming Error] {e}"
        print(f"❌ {error_msg}")
        yield error_msg
