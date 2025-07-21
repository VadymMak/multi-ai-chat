from __future__ import annotations
import os
import openai
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential

DEFAULT_MODEL = "gpt-4o"
MAX_TOKENS = 1024
TEMPERATURE = 0.7
MAX_RETRIES = 3
BACKOFF_SEC = 1.0

@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=1, min=4, max=10))
def ask_openai(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> str:
    api_key = os.getenv("CHATITNOW_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[OpenAI Error] API key not found in environment")
        return "[OpenAI Error] API key not configured"

    try:
        client = openai.OpenAI(api_key=api_key)  # Add base_url if ChatItNow requires
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if not response or not response.choices:
            return "[OpenAI Error] Empty response from OpenAI"
        answer = response.choices[0].message.content.strip()
        return answer or "[OpenAI Error] Empty response"
    except openai.AuthenticationError as e:
        print(f"[OpenAI] Authentication error: {e}")
        return f"[OpenAI Error] Invalid API key: {str(e)}"
    except openai.RateLimitError as e:
        print(f"[OpenAI] Rate limit error: {e}")
        return f"[OpenAI Error] Rate limit exceeded: {str(e)}"
    except openai.APIError as e:
        print(f"[OpenAI] API error: {e}")
        return f"[OpenAI Error] API failure: {str(e)}"
    except Exception as e:
        print(f"[OpenAI] Unexpected error: {e}")
        return f"[OpenAI Error] {str(e)}"