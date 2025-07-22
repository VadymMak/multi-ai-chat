from datetime import datetime
from typing import List, Optional
import tiktoken
from sqlalchemy.orm import Session

from app.memory.models import MemoryEntry, AuditLog
from app.providers.openai_provider import ask_openai

TOKEN_LIMIT = 8192
SUMMARIZE_MODEL = "gpt-4o"
enc = tiktoken.get_encoding("o200k_base")


class MemoryManager:
    def __init__(self, db: Session):
        self.db = db

    def count_tokens(self, text: str) -> int:
        tokens = len(enc.encode(text))
        print(f"[Token Count] {tokens} tokens in: {text[:60]}...")
        return tokens

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
            print(f"[Summarized] {summary.strip()[:100]}...")
            return summary.strip()
        except Exception as e:
            print(f"[Summary Error] {e}")
            return "Summary unavailable due to error."

    def store_memory(
        self,
        project_id: str,
        role_id: int,
        summary: str,
        raw_text: str,
        chat_session_id: Optional[str] = None
    ) -> MemoryEntry:
        tokens = self.count_tokens(raw_text)
        entry = MemoryEntry(
            project_id=project_id,
            role_id=role_id,
            chat_session_id=chat_session_id,
            tokens=tokens,
            summary=summary,
            raw_text=raw_text[:2000],
            timestamp=datetime.utcnow()
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        print(f"[Memory Stored] tokens={tokens}, summary={summary[:80]}...")
        return entry

    def store_chat_message(
        self,
        project_id: str,
        role_id: int,
        chat_session_id: Optional[str],
        sender: str,
        content: str,
    ) -> MemoryEntry:
        tokens = self.count_tokens(content)
        raw_text = f"{sender}: {content.strip()}"
        summary = content.strip()[:400]

        entry = MemoryEntry(
            project_id=project_id,
            role_id=role_id,
            chat_session_id=chat_session_id,
            tokens=tokens,
            summary=summary,
            raw_text=raw_text,
            timestamp=datetime.utcnow()
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        print(f"[Chat Message Stored] sender={sender}, tokens={tokens}, text={content[:80]}...")
        return entry

    def retrieve_messages(
        self,
        project_id: str,
        role_id: int,
        limit: int = 6,
        chat_session_id: Optional[str] = None
    ) -> List[dict]:
        query = self.db.query(MemoryEntry).filter(
            MemoryEntry.project_id == project_id,
            MemoryEntry.role_id == role_id
        )
        if chat_session_id:
            query = query.filter(MemoryEntry.chat_session_id == chat_session_id)

        rows = (
            query.order_by(MemoryEntry.timestamp.desc())
            .limit(limit)
            .all()
        )

        messages = []
        for row in reversed(rows):
            raw = (row.raw_text or "").strip()
            if not raw:
                continue

            if ":" in raw:
                sender, content = raw.split(":", 1)
            else:
                sender, content = "assistant", raw

            messages.append({
                "sender": sender.strip(),
                "text": content.strip(),
                "role_id": row.role_id,
                "project_id": row.project_id,
                "chat_session_id": row.chat_session_id,
                "isTyping": False,
                "isSummary": False,
            })

        if not messages:
            messages.append({
                "sender": "user",
                "text": "Start conversation",
                "role_id": role_id,
                "project_id": project_id,
                "chat_session_id": chat_session_id,
                "isTyping": False,
                "isSummary": False,
            })

        print(f"✅ Retrieved messages (count={len(messages)}): {messages}")
        return messages

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
        print(f"[Summaries Loaded] count={len(rows)}")
        return [r.summary for r in rows]

    def delete_chat_messages(self, project_id: str, role_id: int, chat_session_id: Optional[str] = None):
        try:
            query = self.db.query(MemoryEntry).filter_by(
                project_id=project_id,
                role_id=role_id,
                chat_session_id=chat_session_id
            )
            deleted_count = query.delete()
            self.db.commit()
            print(f"🧹 Deleted {deleted_count} chat messages after summarization.")
        except Exception as e:
            print(f"❌ Failed to delete chat messages: {e}")

    def get_last_session(self) -> Optional[dict]:
        row = (
            self.db.query(
                MemoryEntry.project_id,
                MemoryEntry.role_id,
                MemoryEntry.chat_session_id
            )
            .order_by(MemoryEntry.timestamp.desc())
            .first()
        )
        if row:
            print(f"[Last Session] Found → project_id={row.project_id}, role_id={row.role_id}, session_id={row.chat_session_id}")
            return {
                "project_id": row.project_id,
                "role_id": row.role_id,
                "chat_session_id": row.chat_session_id
            }
        print("[Last Session] None found.")
        return None

    def insert_audit_log(
        self,
        project_id: str,
        role_id: int,
        chat_session_id: Optional[str],
        provider: str,
        action: str,
        query: Optional[str] = None,
        model_version: Optional[str] = None
    ) -> None:
        try:
            entry = AuditLog(
                project_id=str(project_id),
                role_id=role_id,
                chat_session_id=chat_session_id,
                provider=provider,
                action=action,
                query=query,
                model_version=model_version,
                timestamp=datetime.utcnow()
            )
            self.db.add(entry)
            self.db.commit()
            print(f"📝 Audit log inserted: {provider} | {action} | version={model_version}")
        except Exception as e:
            print(f"❌ Failed to insert audit log: {e}")
