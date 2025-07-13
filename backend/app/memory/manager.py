# backend/app/memory/manager.py
from datetime import datetime
from typing import List
import tiktoken
from sqlalchemy.orm import Session
from app.memory.models import MemoryEntry
from app.providers.openai_provider import ask_openai

TOKEN_LIMIT = 8192
SUMMARIZE_MODEL = "gpt-4o"

enc = tiktoken.get_encoding("o200k_base")  # This is the correct tokenizer for gpt-4o

class MemoryManager:
    def __init__(self, db: Session):
        self.db = db

    def count_tokens(self, text: str) -> int:
        return len(enc.encode(text))

    def summarize_messages(self, messages: List[str]) -> str:
        prompt = (
            "Summarize the following conversation in 3 concise bullet points. "
            "Focus on key facts and decisions:\n\n"
            + "\n".join(messages)
        )
        try:
            summary = ask_openai(messages=[{"role": "user", "content": prompt}], model=SUMMARIZE_MODEL)
            return summary.strip()
        except Exception as e:
            print(f"Error summarizing messages: {e}")
            return "Summary unavailable due to error."

    def store_memory(self, role_id: int, summary: str, raw_text: str) -> MemoryEntry:
        tokens = self.count_tokens(raw_text)
        entry = MemoryEntry(
            role_id=role_id,
            tokens=tokens,
            summary=summary,
            raw_text=raw_text[:2000],
            timestamp=datetime.utcnow(),
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def load_recent_summaries(self, role_id: int, limit: int = 5) -> List[str]:
        rows = (
            self.db.query(MemoryEntry.summary)
            .filter(MemoryEntry.role_id == role_id)
            .order_by(MemoryEntry.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [r.summary for r in rows]

    def retrieve_messages(self, role_id: int, limit: int = 6) -> List[dict]:
        rows = (
            self.db.query(MemoryEntry.raw_text)
            .filter(MemoryEntry.role_id == role_id)
            .order_by(MemoryEntry.timestamp.desc())
            .limit(limit)
            .all()
        )

        messages = []
        for row in reversed(rows):
            if not row.raw_text or not row.raw_text.strip():
                print(f"Skipping empty raw_text: {row.raw_text}")
                continue
            blocks = row.raw_text.strip().split("\n")
            for b in blocks:
                if not b.strip():
                    continue
                if b.startswith("User:"):
                    messages.append({"role": "user", "content": b[len("User:"):].strip()})
                elif b.startswith(("OpenAI:", "Anthropic:", "Final:")):
                    model = b.split(":", 1)[0]
                    messages.append({"role": "assistant", "content": f"[{model}] {b.split(':', 1)[1].strip()}"})
                else:
                    print(f"Skipping malformed raw_text: {b}")
                    continue
        # Ensure at least one message
        if not messages:
            messages.append({"role": "user", "content": "Start conversation"})
        print(f"Retrieved messages: {messages}")
        return messages