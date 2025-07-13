import os
from typing import List, Dict, Optional
from openai import OpenAI


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
if not client.api_key:
    raise ValueError("OPENAI_API_KEY not found in environment")

DEFAULT_MODEL = "gpt-4o"

def ask_openai(*, prompt: Optional[str] = None, messages: Optional[List[Dict[str, str]]] = None,
               model: str = DEFAULT_MODEL, temperature: float = 0.7) -> str:
    if messages is None:
        if prompt is None:
            raise ValueError("ask_openai: either `prompt` or `messages` must be provided")
        messages = [{"role": "user", "content": prompt}]

    try:
        print(f"OpenAI request: model={model}, messages={messages}")
        response = client.chat.completions.create(
            model=model, messages=messages, max_tokens=1024, temperature=temperature
        )
        content = response.choices[0].message.content.strip()
        print(f"OpenAI response: {content[:50]}...")
        return content
    except Exception as e:
        print(f"OpenAI error: {e}")
        return f"[OpenAI Error] {e}"