from datetime import datetime
from typing import List
import tiktoken
from sqlalchemy.orm import Session

from app.memory.models import MemoryEntry
from app.providers.openai_provider import ask_openai

TOKEN_LIMIT = 8192
SUMMARIZE_MODEL = "gpt-4o"

# ✅ Tokenizer setup
enc = tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    return len(enc.encode(text))


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
            summary = ask_openai(
                messages=[{"role": "user", "content": prompt}],
                model=SUMMARIZE_MODEL
            )
            return summary.strip()
        except Exception as e:
            print(f"[Summary Error] {e}")
            return "Summary unavailable due to error."

    def store_memory(self, project_id: str, role_id: int, summary: str, raw_text: str) -> MemoryEntry:
        tokens = self.count_tokens(raw_text)
        entry = MemoryEntry(
            project_id=project_id,
            role_id=role_id,
            tokens=tokens,
            summary=summary,
            raw_text=raw_text[:2000],  # limit stored text
            timestamp=datetime.utcnow()
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def load_recent_summaries(self, project_id: str, role_id: int, limit: int = 5) -> List[str]:
        rows = (
            self.db.query(MemoryEntry.summary)
            .filter(
                MemoryEntry.project_id == project_id,
                MemoryEntry.role_id == role_id
            )
            .order_by(MemoryEntry.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [r.summary for r in rows]

    def retrieve_messages(self, project_id: str, role_id: int, limit: int = 6) -> List[dict]:
        rows = (
            self.db.query(MemoryEntry.raw_text)
            .filter(
                MemoryEntry.project_id == project_id,
                MemoryEntry.role_id == role_id
            )
            .order_by(MemoryEntry.timestamp.desc())
            .limit(limit)
            .all()
        )

        messages = []
        for row in reversed(rows):
            raw = row.raw_text.strip()
            if not raw:
                continue

            lines = raw.split("\n")
            valid_dialog_found = False

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if line.startswith("User:"):
                    messages.append({"role": "user", "content": line[len("User:"):].strip()})
                    valid_dialog_found = True
                elif line.startswith(("OpenAI:", "Anthropic:", "Final:")):
                    model, content = line.split(":", 1)
                    messages.append({"role": "assistant", "content": f"[{model}] {content.strip()}"})
                    valid_dialog_found = True
                else:
                    continue

            if not valid_dialog_found:
                # fallback: treat whole block as assistant memory
                messages.append({"role": "assistant", "content": raw})

        if not messages:
            messages.append({"role": "user", "content": "Start conversation"})

        print(f"✅ Retrieved messages: {messages}")
        return messages
