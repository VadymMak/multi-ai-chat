from __future__ import annotations

import os
import time
import json
from typing import List, Tuple
from anthropic import Anthropic, AnthropicError

DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
MAX_RETRIES = 3
BACKOFF_SEC = 1.5


def _clean_history(raw: List[dict]) -> Tuple[List[dict], str | None]:
    """
    Filters the input messages:
    - Removes invalid/empty/error messages
    - Keeps at most 6 most recent messages
    - Ensures the last message is from user
    """
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


def ask_claude(messages: List[dict], model: str = DEFAULT_MODEL) -> str:
    """
    Sends a message to Claude and returns the response text.
    Automatically retries if the API is overloaded.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "[Claude Error] Missing ANTHROPIC_API_KEY in environment"

    try:
        client = Anthropic(api_key=api_key)
    except Exception as e:
        print(f"[Claude] Client init failed: {e}")
        return f"[Claude Error] {e}"

    clean_msgs, system_msg = _clean_history(messages)

    kwargs = {
        "model": model,
        "max_tokens": 1024,
        "temperature": 0.7,
        "messages": clean_msgs
    }

    if system_msg:
        kwargs["system"] = system_msg

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"[Claude] attempt {attempt}/{MAX_RETRIES} → {json.dumps(kwargs, indent=2)[:400]}...")
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
