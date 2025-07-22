from datetime import datetime
from typing import List, Optional
import tiktoken
import unicodedata
from sqlalchemy.orm import Session

from app.memory.models import MemoryEntry, Role as MemoryRole, Project, AuditLog

from app.providers.openai_provider import ask_openai

TOKEN_LIMIT = 8192
SUMMARIZE_MODEL = "gpt-4o"
enc = tiktoken.get_encoding("o200k_base")


def safe_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    try:
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if unicodedata.category(c) != "Cs")
        return text.encode("utf-8", "ignore").decode("utf-8")
    except Exception as e:
        print(f"[Safe Text Error] → {e}")
        return ""


class MemoryManager:
    def __init__(self, db: Session):
        self.db = db
        print("🧠 MemoryManager initialized")

    def count_tokens(self, text: str) -> int:
        tokens = len(enc.encode(text))
        print(f"[Token Count] → {tokens} tokens in: {text[:60]}...")
        return tokens

    def summarize_messages(self, messages: List[str]) -> str:
        prompt = (
            "Summarize the following conversation in 3 concise bullet points. "
            "Focus on key facts and decisions:\n\n" + "\n".join(messages)
        )
        try:
            summary = ask_openai(
                messages=[{"role": "user", "content": prompt}],
                model=SUMMARIZE_MODEL
            )
            print(f"[Summarized] → {summary.strip()[:100]}...")
            return safe_text(summary.strip())
        except Exception as e:
            print(f"[Summary Error] → {e}")
            return f"Summary unavailable: {e}"

    def store_memory(
        self,
        project_id: str,
        role_id: int,
        summary: str,
        raw_text: str,
        chat_session_id: Optional[str] = None,
        is_ai_to_ai: bool = False
    ) -> MemoryEntry:
        print(f"[Store Memory] role={role_id}, project={project_id}, session={chat_session_id}")
        summary = safe_text(summary)
        raw_text = safe_text(raw_text)
        tokens = self.count_tokens(raw_text)

        entry = MemoryEntry(
            project_id=project_id,
            role_id=role_id,
            chat_session_id=chat_session_id,
            tokens=tokens,
            summary=summary,
            raw_text=raw_text[:2000],
            is_ai_to_ai=is_ai_to_ai,
            is_summary=True,
            timestamp=datetime.utcnow()
        )

        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        print(f"[Memory Stored] → tokens={tokens}, summary={summary[:80]}...")
        return entry

    def store_chat_message(
        self,
        project_id: str,
        role_id: int,
        chat_session_id: Optional[str],
        sender: str,
        content: str,
        is_summary: bool = False,
        is_ai_to_ai: bool = False
    ) -> MemoryEntry:
        print(f"[Store Chat Message] sender={sender}, role={role_id}, project={project_id}, session={chat_session_id}")
        content = safe_text(content)
        sender = safe_text(sender)
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
            is_summary=is_summary,
            is_ai_to_ai=is_ai_to_ai,
            timestamp=datetime.utcnow()
        )

        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        print(f"[Chat Message Stored] → sender={sender}, tokens={tokens}, text={content[:80]}...")
        return entry

    def retrieve_messages(
        self,
        project_id: str,
        role_id: int,
        limit: int = 6,
        chat_session_id: Optional[str] = None
    ) -> List[dict]:
        print(f"[Retrieve Messages] role={role_id}, project={project_id}, session={chat_session_id}, limit={limit}")
        query = self.db.query(MemoryEntry).filter(
            MemoryEntry.project_id == project_id,
            MemoryEntry.role_id == role_id
        )
        if chat_session_id:
            query = query.filter(MemoryEntry.chat_session_id == chat_session_id)

        rows = query.order_by(MemoryEntry.timestamp.desc()).limit(limit).all()

        messages = []
        for row in reversed(rows):
            raw = safe_text((row.raw_text or "").strip())
            if not raw:
                continue

            sender, content = "assistant", raw
            if ":" in raw:
                parts = raw.split(":", 1)
                sender, content = parts[0], parts[1]

            cid = row.chat_session_id or chat_session_id
            if not cid:
                cid_row = (
                    self.db.query(MemoryEntry.chat_session_id)
                    .filter(
                        MemoryEntry.project_id == project_id,
                        MemoryEntry.role_id == role_id,
                        MemoryEntry.chat_session_id.isnot(None)
                    )
                    .order_by(MemoryEntry.timestamp.desc())
                    .first()
                )
                cid = cid_row.chat_session_id if cid_row else None

            messages.append({
                "sender": sender.strip(),
                "text": content.strip(),
                "role_id": row.role_id,
                "project_id": row.project_id,
                "chat_session_id": cid,
                "isTyping": False,
                "isSummary": row.is_summary or False
            })

        if not messages:
            print("[Retrieve Messages] No chat messages found, creating starter")
            messages.append({
                "sender": "user",
                "text": "Start conversation",
                "role_id": role_id,
                "project_id": project_id,
                "chat_session_id": chat_session_id,
                "isTyping": False,
                "isSummary": False
            })

        print(f"[Messages Retrieved] → count={len(messages)}")
        return messages

    def load_recent_summaries(self, project_id: str, role_id: int, limit: int = 5) -> List[str]:
        print(f"[Load Summaries] role={role_id}, project={project_id}, limit={limit}")
        rows = (
            self.db.query(MemoryEntry.summary)
            .filter(
                MemoryEntry.project_id == project_id,
                MemoryEntry.role_id == role_id,
                MemoryEntry.is_summary == True
            )
            .order_by(MemoryEntry.timestamp.desc())
            .limit(limit)
            .all()
        )
        print(f"[Summaries Loaded] → count={len(rows)}")
        return [safe_text(r.summary) for r in rows]

    def delete_chat_messages(self, project_id: str, role_id: int, chat_session_id: Optional[str] = None) -> None:
        print(f"[Delete Messages] project={project_id}, role={role_id}, session={chat_session_id}")
        try:
            query = self.db.query(MemoryEntry).filter_by(
                project_id=project_id,
                role_id=role_id
            )
            if chat_session_id:
                query = query.filter(MemoryEntry.chat_session_id == chat_session_id)
            deleted_count = query.delete()
            self.db.commit()
            print(f"[Cleanup] Deleted {deleted_count} chat messages.")
        except Exception as e:
            print(f"[Cleanup Error] → {e}")

    def get_last_session(
        self,
        role_id: Optional[int] = None,
        project_id: Optional[str] = None
    ) -> Optional[dict]:
        print(f"[Get Last Session] role={role_id}, project={project_id}")
        query = (
            self.db.query(
                MemoryEntry.project_id,
                MemoryEntry.role_id,
                MemoryEntry.chat_session_id,
                MemoryRole.name.label("role_name")
            )
            .join(MemoryRole, MemoryEntry.role_id == MemoryRole.id)
            .order_by(MemoryEntry.timestamp.desc())
        )

        if role_id is not None:
            query = query.filter(MemoryEntry.role_id == role_id)
        if project_id is not None:
            query = query.filter(MemoryEntry.project_id == project_id)

        row = query.first()

        if row:
            print(
                f"[Last Session] → project_id={row.project_id}, role_id={row.role_id}, "
                f"session_id={row.chat_session_id}, role_name={row.role_name}"
            )
            return {
                "project_id": row.project_id,
                "role_id": row.role_id,
                "chat_session_id": row.chat_session_id,
                "role_name": row.role_name
            }

        print(f"[Last Session] → None found")
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
        print(f"[Insert Audit Log] provider={provider}, action={action}, role={role_id}, project={project_id}, session={chat_session_id}")
        try:
            entry = AuditLog(
                project_id=str(project_id),
                role_id=role_id,
                chat_session_id=chat_session_id,
                provider=provider,
                action=action,
                query=safe_text(query) if query else None,
                model_version=model_version,
                timestamp=datetime.utcnow()
            )
            self.db.add(entry)
            self.db.commit()
            print(f"[Audit Log] → provider={provider}, action={action}, version={model_version}")
        except Exception as e:
            print(f"[Audit Log Error] → {e}")
