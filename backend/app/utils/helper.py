import time
from app.memory.manager import MemoryManager

def validate_messages(msgs: list[dict]) -> list[dict]:
    """Filter empty messages and Claude errors."""
    return [m for m in msgs if m.get("content", "").strip() and "[Claude Error]" not in m.get("content", "")] or \
           [{"role": "user", "content": "Start conversation"}]

def log_interaction(mem: MemoryManager, role_id: str, question: str, answer: str, model: str):
    raw = f"User: {question}\n{model.capitalize()}: {answer}"
    mem.store_memory(role_id, mem.summarize_messages([raw]), raw)
