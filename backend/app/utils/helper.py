import time
from app.memory.manager import MemoryManager

def validate_messages(msgs: list[dict]) -> list[dict]:
    """Filter empty messages and Claude errors."""
    return [m for m in msgs if m.get("content", "").strip() and "[Claude Error]" not in m.get("content", "")] or \
           [{"role": "user", "content": "Start conversation"}]

def log_interaction(mem: MemoryManager, role_id: str, question: str, answer: str, model: str):
    raw = f"User: {question}\n{model.capitalize()}: {answer}"
    mem.store_memory(role_id, mem.summarize_messages([raw]), raw)

def generate_prompt_for_claude(
    topic: str,
    youtube_links: list[dict],
    web_results: list[dict],
    openai_summary: str
) -> str:
    prompt = f"""You are a smart assistant helping summarize a topic using multi-source research.

## Topic:
{topic}

## Answer from OpenAI:
{openai_summary}

## YouTube Insights:
"""
    for yt in youtube_links[:3]:
        desc = yt.get("description", "").strip()[:200]
        prompt += f"- {yt['title']}: {desc}... ({yt['url']})\n"

    prompt += "\n## Web Results:\n"
    for w in web_results[:3]:
        prompt += f"- {w['title']}: {w['snippet']} ({w['url']})\n"

    prompt += """

## Final Task:
Write a clear, complete, and professional explanation for the topic, combining the OpenAI answer, YouTube insights, and web research. Format with proper headings, steps, or bullet points if helpful.

Respond in a helpful, structured, and confident tone.
"""
    return prompt
