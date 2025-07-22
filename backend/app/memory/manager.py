from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
import json
import unicodedata
from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.memory.models import MemoryEntry, Role as MemoryRole, CanonItem

# --- Tokenizer (robust) ---
try:
    import tiktoken  # type: ignore
    try:
        _enc = tiktoken.get_encoding("o200k_base")
    except Exception:
        _enc = tiktoken.encoding_for_model("gpt-4o")  # close enough
except Exception:
    _enc = None  # fallback


def _count_tokens_fallback(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


# --- Late imports so optional deps/settings load cleanly ---
from app.providers.openai_provider import ask_openai  # noqa: E402
from app.config.settings import settings  # noqa: E402

# Tunables / clip sizes
TOKEN_LIMIT = 8192
SUMMARIZE_MODEL = getattr(settings, "OPENAI_SUMMARIZE_MODEL", "gpt-4o-mini")
MAX_RAW_TEXT_LEN = 10_000
MAX_SUMMARY_LEN = 2_000
MAX_CANON_BODY_LEN = 8_000


def safe_text(text: str) -> str:
    if not isinstance(text, str):
        text = str(text or "")
    try:
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if unicodedata.category(c) != "Cs")
        return text.encode("utf-8", "ignore").decode("utf-8")
    except Exception as e:
        print(f"[Safe Text Error] → {e}")
        return ""


def _to_int_or_none(s: Optional[str]) -> Optional[int]:
    try:
        if s is None:
            return None
        return int(str(s))
    except Exception:
        return None


class MemoryManager:
    def __init__(self, db: Session):
        self.db = db
        print("🧠 MemoryManager initialized")

    # -------------------------
    # Session helpers
    # -------------------------
    def get_or_create_chat_session_id(self, role_id: int, project_id: str) -> str:
        """
        Return latest chat_session_id for (role, project) if it exists;
        otherwise mint a new UUID (no DB write here).
        """
        try:
            last = self.get_last_session(role_id=role_id, project_id=str(project_id))
            sid = (last or {}).get("chat_session_id")
            if sid and str(sid).strip():
                return str(sid).strip()
        except Exception as e:
            print(f"[get_or_create_chat_session_id] last-session lookup failed → {e}")
        return str(uuid4())

    def preflight_token_budget(
        self,
        texts: List[str],
        soft: Optional[int] = None,
        hard: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Lightweight token preflight for request building.
        Returns: { total_tokens, near_soft, over_hard, soft, hard }
        """
        soft = int(soft if soft is not None else getattr(settings, "SOFT_TOKEN_BUDGET", 6000))
        hard = int(hard if hard is not None else getattr(settings, "HARD_TOKEN_BUDGET", 7800))
        total = sum(self.count_tokens(t or "") for t in texts or [])
        near_soft = total >= int(soft * 0.80)   # 80% threshold to warn early
        over_hard = total >= hard
        print(f"[Token Preflight] total={total} soft={soft} hard={hard} near_soft={near_soft} over_hard={over_hard}")
        return {
            "total_tokens": total,
            "near_soft": bool(near_soft),
            "over_hard": bool(over_hard),
            "soft": soft,
            "hard": hard,
        }

    # -------------------------
    # Token helpers
    # -------------------------
    def count_tokens(self, text: str) -> int:
        text = text or ""
        try:
            tokens = len(_enc.encode(text)) if _enc is not None else _count_tokens_fallback(text)
            if getattr(settings, "LOG_TOKEN_COUNTS", True):
                print(f"[Token Count] → {tokens} tokens in: {text[:60]}...")
            return tokens
        except Exception as e:
            print(f"[Token Count Error] → {e}")
            return _count_tokens_fallback(text)

    # -------------------------
    # Summaries
    # -------------------------
    def summarize_messages(self, messages: List[str]) -> str:
        prompt = (
            "Summarize the following conversation in ~600 tokens, focusing on key decisions, "
            "requirements, code-related details, and next steps. Use tight, informative bullets.\n\n"
            + "\n".join(messages or [])
        )
        try:
            summary = ask_openai(
                messages=[{"role": "user", "content": prompt}],
                model=SUMMARIZE_MODEL,
            )
            summary = safe_text((summary or "").strip())
            print(f"[Summarized] → {summary[:100]}...")
            return summary or "Summary unavailable."
        except Exception as e:
            print(f"[Summary Error] → {e}")
            return f"Summary unavailable: {e}"

    def summarize_text(self, text: str) -> str:
        return self.summarize_messages([text])

    # -------------------------
    # Writes
    # -------------------------
    def store_memory(
        self,
        project_id: str,
        role_id: int,
        summary: str,
        raw_text: str,
        chat_session_id: Optional[str] = None,
        is_ai_to_ai: bool = False,
    ) -> MemoryEntry:
        print(f"[Store Memory] role={role_id}, project={project_id}, session={chat_session_id}")
        summary = safe_text(summary)[:MAX_SUMMARY_LEN]
        raw_text = safe_text(raw_text)[:MAX_RAW_TEXT_LEN]
        tokens = self.count_tokens(raw_text)
        pj_int = _to_int_or_none(project_id)

        entry = MemoryEntry(
            project_id=str(project_id),
            project_id_int=pj_int,
            role_id=role_id,
            chat_session_id=chat_session_id,
            tokens=tokens,
            summary=summary,
            raw_text=raw_text,
            is_ai_to_ai=is_ai_to_ai,
            is_summary=True,
            timestamp=datetime.utcnow(),
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
        # ✅ keep backward-compat: accept either `text=` or `content=`
        text: Optional[str] = None,
        content: Optional[str] = None,
        is_summary: bool = False,
        is_ai_to_ai: bool = False,
    ) -> MemoryEntry:
        """
        Persist a single chat turn. Prefer passing `text=...` (routers now do this).
        Old callers that pass `content=` still work.
        """
        msg_text = text if text is not None else (content or "")
        print(f"[Store Chat Message] sender={sender}, role={role_id}, project={project_id}, session={chat_session_id}")
        msg_text = safe_text(msg_text)[:MAX_RAW_TEXT_LEN]
        sender = safe_text(sender) or "assistant"
        tokens = self.count_tokens(msg_text)
        pj_int = _to_int_or_none(project_id)

        raw_text = f"{sender}: {msg_text}"
        preview = msg_text.strip()[:MAX_SUMMARY_LEN]

        entry = MemoryEntry(
            project_id=str(project_id),
            project_id_int=pj_int,
            role_id=role_id,
            chat_session_id=chat_session_id,
            tokens=tokens,
            summary=preview,
            raw_text=raw_text,
            is_summary=is_summary,
            is_ai_to_ai=is_ai_to_ai,
            timestamp=datetime.utcnow(),
        )

        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        print(f"[Chat Message Stored] → sender={sender}, tokens={tokens}, text={msg_text[:80]}...")
        return entry

    # -------------------------
    # Canon writes
    # -------------------------
    def store_canon_item(
        self,
        *,
        project_id: str,
        role_id: Optional[int],
        type: str,
        title: str,
        body: str,
        tags: Optional[List[str]] = None,
        terms: Optional[str] = None,
    ) -> Optional[int]:
        if not getattr(settings, "ENABLE_CANON", False):
            return None

        type = safe_text(type.upper()[:32] or "CHANGELOG")
        title = safe_text(title)[:256]
        body = safe_text(body)[:MAX_CANON_BODY_LEN]
        terms = safe_text(terms or "")[:1000]
        pj_int = _to_int_or_none(project_id)

        item = CanonItem(
            project_id=str(project_id),
            project_id_int=pj_int,
            role_id=role_id,
            type=type,
            title=title,
            body=body,
            tags=tags or None,
            terms=terms or None,
            created_at=datetime.utcnow(),
            is_active=True,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)

        print(f"[Canon Stored] → id={item.id}, type={type}, title={title[:80]}...")
        try:
            self.insert_audit_log(project_id, role_id or -1, None, "internal", "canon_insert", f"{type}: {title}"[:300])
        except Exception:
            pass
        return item.id

    def save_canon_items(self, items: List[Dict[str, Any]]) -> List[Optional[int]]:
        ids: List[Optional[int]] = []
        for d in items or []:
            ids.append(
                self.store_canon_item(
                    project_id=d.get("project_id"),
                    role_id=d.get("role_id"),
                    type=d.get("type", "CHANGELOG"),
                    title=d.get("title", "Update"),
                    body=d.get("body", ""),
                    tags=d.get("tags"),
                    terms=d.get("terms"),
                )
            )
        return ids

    # -------------------------
    # Canon reads & digest
    # -------------------------
    def search_canon_items(
        self,
        *,
        project_id: str,
        role_id: Optional[int] = None,
        query_terms: Optional[List[str]] = None,
        top_k: Optional[int] = None,
        types: Optional[List[str]] = None,
        include_global_roleless: bool = True,
    ) -> List[CanonItem]:
        if not getattr(settings, "ENABLE_CANON", False):
            return []

        q = self.db.query(CanonItem).filter(
            CanonItem.project_id == str(project_id),
            CanonItem.is_active == True,  # noqa: E712
        )

        if role_id is not None:
            if include_global_roleless:
                q = q.filter(or_(CanonItem.role_id == role_id, CanonItem.role_id.is_(None)))
            else:
                q = q.filter(CanonItem.role_id == role_id)

        if types:
            types_u = [safe_text(t).upper() for t in types if t]
            q = q.filter(CanonItem.type.in_(types_u))

        if query_terms:
            term_clauses = []
            for t in query_terms:
                t = safe_text(t)
                if not t:
                    continue
                like = f"%{t}%"
                term_clauses.append(or_(
                    CanonItem.title.ilike(like),
                    CanonItem.body.ilike(like),
                    CanonItem.terms.ilike(like),
                ))
            if term_clauses:
                q = q.filter(and_(*term_clauses))

        q = q.order_by(CanonItem.created_at.desc())

        k = top_k or int(getattr(settings, "CANON_TOPK", 6))
        rows = q.limit(max(1, k)).all()
        print(f"[Canon Search] project={project_id}, role={role_id}, terms={query_terms} → {len(rows)} hits")
        return rows

    def retrieve_context_digest(
        self,
        *,
        project_id: str,
        role_id: Optional[int] = None,
        query_terms: Optional[List[str]] = None,
        top_k: Optional[int] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        rows = self.search_canon_items(
            project_id=project_id,
            role_id=role_id,
            query_terms=query_terms,
            top_k=top_k,
        )
        if not rows:
            return "", []

        items: List[Dict[str, Any]] = []
        sections: List[str] = []

        for r in rows:
            body = safe_text(r.body or "")[:MAX_CANON_BODY_LEN]
            snippet = body if len(body) <= 600 else (body[:580] + " …")
            header = f"[{r.type}] {r.title}"
            sections.append(f"{header}\n{snippet}")
            items.append({
                "id": r.id,
                "type": r.type,
                "title": r.title,
                "body": body,
                "tags": r.tags or [],
                "terms": r.terms or "",
                "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
            })

        digest = "### Canonical Context (most relevant first)\n" + "\n\n".join(sections)
        print(f"[Canon Digest] → {len(items)} items, {len(digest)} chars")
        return digest, items

    # -------------------------
    # Canon extraction (LLM + heuristic fallback)
    # -------------------------
    def extract_canon_deltas(
        self,
        *,
        text: str,
        project_id: str,
        role_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not getattr(settings, "ENABLE_CANON", False):
            return []

        text = safe_text(text or "")[:MAX_RAW_TEXT_LEN]
        if not text.strip():
            return []

        # 1) Try LLM JSON extraction
        try:
            system = (
                "Extract durable project knowledge as JSON array. "
                "Each item must be one of types: ADR, CHANGELOG, BACKLOG, GLOSSARY, PMD. "
                "Schema per item: {\"type\":\"ADR|CHANGELOG|BACKLOG|GLOSSARY|PMD\",\"title\":\"str(≤200)\","
                "\"body\":\"str(≤1000)\",\"tags\":[\"str\"...],\"terms\":\"comma,separated,keywords\"}. "
                "Only output JSON. No commentary."
            )
            user = f"Source text:\n{text}"
            raw = ask_openai(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                model=getattr(settings, "CANON_EXTRACT_MODEL", "gpt-4o-mini"),
            )
            payload = (raw or "").strip()
            start = payload.find("["); end = payload.rfind("]")
            if start != -1 and end != -1 and end > start:
                payload = payload[start:end + 1]
            data = json.loads(payload)
            results: List[Dict[str, Any]] = []
            allowed = {"ADR", "CHANGELOG", "BACKLOG", "GLOSSARY", "PMD"}
            for item in data if isinstance(data, list) else []:
                t = safe_text(str(item.get("type", ""))).upper()
                if t not in allowed:
                    continue
                results.append({
                    "type": t,
                    "title": safe_text(item.get("title", ""))[:256],
                    "body": safe_text(item.get("body", ""))[:1000],
                    "tags": [safe_text(x) for x in (item.get("tags") or []) if safe_text(x)],
                    "terms": safe_text(item.get("terms", ""))[:500],
                })
            if results:
                print(f"[Canon Extract LLM] → {len(results)} items")
                return results
        except Exception as e:
            print(f"[Canon Extract LLM Error] → {e}")

        # 2) Heuristic fallback
        lines = [ln.strip(" •-\t") for ln in (text.splitlines() if text else []) if ln.strip()]
        results: List[Dict[str, Any]] = []
        for ln in lines:
            low = ln.lower()
            if low.startswith("decision") or "adr:" in low:
                results.append({"type": "ADR", "title": ln[:200], "body": ln, "tags": [], "terms": "decision"})
            elif low.startswith("change") or "updated" in low or "refactor" in low:
                results.append({"type": "CHANGELOG", "title": ln[:200], "body": ln, "tags": [], "terms": "change,update"})
            elif "todo" in low or "next:" in low or "backlog" in low:
                results.append({"type": "BACKLOG", "title": ln[:200], "body": ln, "tags": [], "terms": "todo,next"})
            elif low.startswith("term:") or "glossary" in low:
                title = ln.split(":", 1)[1].strip() if ":" in ln else ln
                results.append({"type": "GLOSSARY", "title": title[:200], "body": ln, "tags": [], "terms": title})
        print(f"[Canon Extract Heuristic] → {len(results)} items")
        return results

    # -------------------------
    # Reads
    # -------------------------
    def _split_sender_content(self, raw: str) -> Tuple[str, str]:
        raw = (raw or "").strip()
        if ":" in raw:
            parts = raw.split(":", 1)
            return parts[0].strip(), parts[1].strip()
        return "assistant", raw

    def retrieve_messages(
        self,
        project_id: str,
        role_id: int,
        limit: int = 6,
        chat_session_id: Optional[str] = None,
        include_summaries: bool = False,
    ) -> List[dict]:
        """
        Return recent chat messages (newest last). By default, **excludes summaries**
        so prompts don't ingest summary blobs as chat turns.
        """
        print(f"[Retrieve Messages] role={role_id}, project={project_id}, session={chat_session_id}, limit={limit}, include_summaries={include_summaries}")
        query = self.db.query(MemoryEntry).filter(
            MemoryEntry.project_id == str(project_id),
            MemoryEntry.role_id == role_id,
        )
        if chat_session_id:
            query = query.filter(MemoryEntry.chat_session_id == chat_session_id)
        if not include_summaries:
            query = query.filter(MemoryEntry.is_summary == False)  # noqa: E712

        rows = query.order_by(MemoryEntry.timestamp.desc()).limit(max(1, int(limit))).all()

        messages: List[dict] = []
        for row in reversed(rows):  # ASC order
            raw = safe_text(row.raw_text or "")
            if not raw:
                continue
            sender, content = self._split_sender_content(raw)
            cid = row.chat_session_id or chat_session_id
            messages.append({
                "sender": sender,
                "text": content,
                "role_id": row.role_id,
                "project_id": row.project_id,
                "chat_session_id": cid,
                "isTyping": False,
                "isSummary": bool(row.is_summary),
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
                "isSummary": False,
            })

        print(f"[Messages Retrieved] → count={len(messages)}")
        return messages

    def load_recent_summaries(self, project_id: str, role_id: int, limit: int = 5) -> List[str]:
        print(f"[Load Summaries] role={role_id}, project={project_id}, limit={limit}")
        rows = (
            self.db.query(MemoryEntry.summary)
            .filter(
                MemoryEntry.project_id == str(project_id),
                MemoryEntry.role_id == role_id,
                MemoryEntry.is_summary == True,  # noqa: E712
            )
            .order_by(MemoryEntry.timestamp.desc())
            .limit(max(1, int(limit)))
            .all()
        )
        print(f"[Summaries Loaded] → count={len(rows)}")
        return [safe_text(getattr(r, "summary", "")) for r in rows]

    # -------------------------
    # Cleanup / housekeeping
    # -------------------------
    def delete_chat_messages(
        self,
        project_id: str,
        role_id: int,
        chat_session_id: Optional[str] = None,
        keep_summaries: bool = True,
    ) -> None:
        print(f"[Delete Messages] project={project_id}, role={role_id}, session={chat_session_id}")
        try:
            query = self.db.query(MemoryEntry).filter(
                MemoryEntry.project_id == str(project_id),
                MemoryEntry.role_id == role_id,
            )
            if chat_session_id:
                query = query.filter(MemoryEntry.chat_session_id == chat_session_id)
            if keep_summaries:
                query = query.filter(MemoryEntry.is_summary == False)  # noqa: E712

            deleted_count = query.delete()
            self.db.commit()
            print(f"[Cleanup] Deleted {deleted_count} chat messages.")
        except Exception as e:
            print(f"[Cleanup Error] → {e}")

    # -------------------------
    # Discovery
    # -------------------------
    def get_last_session(
        self,
        role_id: Optional[int] = None,
        project_id: Optional[str] = None,
    ) -> Optional[dict]:
        print(f"[Get Last Session] role={role_id}, project={project_id}")
        query = (
            self.db.query(
                MemoryEntry.project_id,
                MemoryEntry.role_id,
                MemoryEntry.chat_session_id,
                MemoryRole.name.label("role_name"),
                MemoryEntry.is_summary,
                MemoryEntry.timestamp,
            )
            .join(MemoryRole, MemoryEntry.role_id == MemoryRole.id)
            .filter(MemoryEntry.chat_session_id.isnot(None))
            .order_by(MemoryEntry.timestamp.desc())
        )

        if role_id is not None:
            query = query.filter(MemoryEntry.role_id == role_id)
        if project_id is not None:
            query = query.filter(MemoryEntry.project_id == str(project_id))

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
                "role_name": row.role_name,
            }

        print("[Last Session] → None found")
        return None

    # -------------------------
    # Audit
    # -------------------------
    def insert_audit_log(
        self,
        project_id: str,
        role_id: int,
        chat_session_id: Optional[str],
        provider: str,
        action: str,
        query: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> None:
        """
        Local-import AuditLog to avoid NameError when hot-reload loads manager.py
        before models.AuditLog class is created.
        """
        print(
            f"[Insert Audit Log] provider={provider}, action={action}, role={role_id}, "
            f"project={project_id}, session={chat_session_id}"
        )
        try:
            from app.memory.models import AuditLog as _AuditLog  # type: ignore

            entry = _AuditLog(
                project_id=str(project_id),
                role_id=role_id,
                chat_session_id=chat_session_id,
                provider=safe_text(provider),
                action=safe_text(action),
                query=safe_text(query) if query else None,
                model_version=model_version,
                timestamp=datetime.utcnow(),
            )
            self.db.add(entry)
            self.db.commit()
            print(f"[Audit Log] → provider={provider}, action={action}, version={model_version}")
        except Exception as e:
            print(f"[Audit Log Error] → {e}")
