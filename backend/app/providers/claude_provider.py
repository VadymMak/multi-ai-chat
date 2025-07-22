from __future__ import annotations

import os
import time
import json
from typing import List, Tuple, Optional
from anthropic import Anthropic, AnthropicError
from anthropic.types import Message, MessageParam, TextBlock

DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
MAX_RETRIES = 3
BACKOFF_SEC = 1.5


def _clean_history(raw: List[dict]) -> Tuple[List[dict], Optional[str]]:
    clean: List[dict] = []
    system_msg = None

    for msg in raw:
        content = msg.get("content", "").strip()
        if msg["role"] == "system":
            system_msg = content
            continue
        if not content or "[Claude Error]" in content:
            continue
        clean.append({"role": msg["role"], "content": content})

    if not clean or clean[-1]["role"] != "user":
        clean.append({
            "role": "user",
            "content": "Please respond to the previous message."
        })

    return clean[-6:], system_msg


def ask_claude(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    system: Optional[str] = None,
    memory: Optional[List[dict]] = None,
    temperature: float = 0.7
) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "[Claude Error] Missing ANTHROPIC_API_KEY in environment"

    try:
        client = Anthropic(api_key=api_key)
    except Exception as e:
        print(f"[Claude] Client init failed: {e}")
        return f"[Claude Error] {e}"

    # Step 1: Clean input
    if memory is None:
        memory, inferred_system = _clean_history(messages)
    else:
        inferred_system = None

    full_history = (memory or []) + messages

    # Convert to Claude-compatible format
    final_messages: List[MessageParam] = []
    for msg in full_history:
        role = msg.get("role")
        content = msg.get("content", "").strip()
        if role not in {"user", "assistant"} or not content:
            print(f"[Claude] ⚠️ Skipping invalid message: {msg}")
            continue
        final_messages.append({
            "role": role,
            "content": [{"type": "text", "text": content}]
        })

    # Step 2: Build API call
    system_prompt = system or inferred_system or "You are a helpful assistant."
    kwargs = {
        "model": model,
        "max_tokens": 1024,
        "temperature": temperature,
        "messages": final_messages,
        "system": system_prompt
    }

    # Step 3: Send request with retries
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"✅ Final messages being sent:")
            print(json.dumps(kwargs, indent=2)[:500] + "...")

            response: Message = client.messages.create(**kwargs)
            print(f"[Claude] full response: {response}")

            if not response.content or not isinstance(response.content, list):
                raise AnthropicError("Claude returned invalid content structure")

            first_block = response.content[0]
            if not first_block.text.strip():
                raise AnthropicError("Claude returned empty text")

            return first_block.text.strip()

        except AnthropicError as ae:
            if "overloaded" in str(ae).lower() and attempt < MAX_RETRIES:
                print(f"[Claude] retrying due to overload: {ae}")
                time.sleep(BACKOFF_SEC * attempt)
                continue
            print(f"[Claude] Anthropic API error: {ae}")
            return f"[Claude Error] {ae}"

        except Exception as e:
            print(f"[Claude] Unexpected error: {e}")
            return f"[Claude Error] {e}"

    return "[Claude Error] Exhausted retries without success"
