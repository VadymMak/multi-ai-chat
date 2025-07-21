from __future__ import annotations

import os, time, json
from typing import List
from anthropic import Anthropic, AnthropicError

DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
MAX_RETRIES = 3
BACKOFF_SEC = 1.0  # starting back-off (doubles each retry)

def _clean_history(raw: List[dict]) -> tuple[List[dict], str | None]:
    """Remove empty / error messages and pull out top-level system message."""
    system_msg = None
    out: List[dict] = []

    for m in raw:
        if m["role"] == "system":
            system_msg = m["content"]
            continue
        if "[Claude Error]" in m.get("content", "") or not m.get("content", "").strip():
            continue
        out.append(m)

    if not any(m["role"] == "user" for m in out):
        out.append({"role": "user", "content": "Please respond to the previous message."})

    return out, system_msg

def ask_claude(messages: List[dict], model: str = DEFAULT_MODEL) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Anthropic error: API key not configured")
        return "[Claude Error] ANTHROPIC_API_KEY not found in environment"

    try:
        client = Anthropic(api_key=api_key)
        clean_msgs, system_msg = _clean_history(messages)
        kwargs = dict(
            model=model,
            max_tokens=1024,
            temperature=0.7,
            messages=clean_msgs,
        )
        if system_msg:
            kwargs["system"] = system_msg

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"[Claude] attempt {attempt}/{MAX_RETRIES} → {json.dumps(kwargs, indent=2)[:500]}...")
                resp = client.messages.create(**kwargs)

                if not resp.content:
                    raise AnthropicError("Claude returned empty content")

                answer = resp.content[0].text.strip()
                return answer or "[Claude Error] Claude returned empty content"

            except AnthropicError as err:
                err_str = str(err).lower()
                if "overloaded" in err_str or "529" in err_str:
                    if attempt < MAX_RETRIES:
                        wait = BACKOFF_SEC * attempt
                        print(f"[Claude] overloaded – retrying in {wait:.1f}s")
                        time.sleep(wait)
                        continue
                    return "[Claude Error] Claude is temporarily overloaded – please retry."

                print(f"[Claude] API error: {err}")
                return f"[Claude Error] {err}"

            except Exception as err:
                print(f"[Claude] unexpected error: {err}")
                return f"[Claude Error] {err}"

        return "[Claude Error] Unknown failure after retries"

    except Exception as e:
        print(f"[Claude] unexpected error during client initialization: {e}")
        return f"[Claude Error] {e}"
