"""
Skill Distiller Service

Automatically generates reusable brain_skills from:
  1. Resolved learned_errors (grouped by error_type)
  2. Recent SESSION_SUMMARY canon_items

Usage:
    from app.services.skill_distiller import distill
    result = distill(project_id=20, since_days=30, dry_run=True)

Auto-distilled skills are marked with "[auto]" at the start of their description.
Manual skills (no "[auto]" prefix) are never overwritten by this service.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.memory.db import SessionLocal

logger = logging.getLogger(__name__)

_client: Optional[OpenAI] = None

_VALID_CATEGORIES = {"workflow", "coding", "deploy", "debug", "review"}
_AUTO_MARKER = "[auto]"
_MAX_NEW_SKILLS = 5


# ── OpenAI client ─────────────────────────────────────────────────────────────

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        from app.config.settings import settings
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        _client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            http_client=httpx.Client(
                timeout=httpx.Timeout(60.0, connect=10.0),
                trust_env=False,
            ),
        )
    return _client


def _open_db() -> Session:
    return SessionLocal()


# ── Prompts ───────────────────────────────────────────────────────────────────

_ERROR_PROMPT = """\
You are distilling developer lessons into reusable AI skills.
Below are {count} resolved code errors of type "{error_type}" with their solutions.
Create ONE reusable skill a future AI assistant can follow to fix this class of error.

Errors and resolutions:
{errors_text}

Return JSON only:
{{
  "name": "<slug ≤40 chars, lowercase hyphens only, e.g. fix-import-resolution>",
  "category": "<one of: workflow, coding, deploy, debug, review>",
  "description": "<one-line ≤100 chars>",
  "content": "<markdown ≤1400 chars starting with 'When to use:' then numbered steps>"
}}"""

_SUMMARY_PROMPT = """\
You are distilling developer lessons into reusable AI skills.
Below are {count} recent session summaries from a developer's AI brain system.
Extract ONE skill capturing the most valuable recurring pattern or workflow.

Session summaries:
{summaries_text}

Return JSON only (or null if no clear recurring pattern):
{{
  "name": "<slug ≤40 chars, lowercase hyphens only>",
  "category": "<one of: workflow, coding, deploy, debug, review>",
  "description": "<one-line ≤100 chars>",
  "content": "<markdown ≤1400 chars starting with 'When to use:' then numbered steps>"
}}"""


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_error_clusters(
    db: Session, project_id: Optional[int], since: datetime
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"since": since}
    pid_clause = ""
    if project_id is not None:
        params["project_id"] = project_id
        pid_clause = "AND le.project_id = :project_id"

    rows = db.execute(text(f"""
        SELECT le.error_type, le.error_pattern, le.solution_pattern, le.solution_example
        FROM learned_errors le
        WHERE le.resolved_count > 0
          AND le.last_seen >= :since
          {pid_clause}
        ORDER BY le.error_type, le.resolved_count DESC
        LIMIT 100
    """), params).fetchall()

    clusters: Dict[str, List[Dict]] = {}
    for row in rows:
        etype = (row.error_type or "unknown").strip()
        clusters.setdefault(etype, []).append({
            "pattern": row.error_pattern or "",
            "solution": row.solution_pattern or "",
            "example": (row.solution_example or "")[:300],
        })

    return [{"error_type": k, "errors": v} for k, v in clusters.items()]


def _load_session_summaries(
    db: Session, project_id: Optional[int], since: datetime
) -> List[str]:
    params: Dict[str, Any] = {"since": since}
    pid_clause = ""
    if project_id is not None:
        params["project_id"] = str(project_id)
        pid_clause = "AND project_id = :project_id"

    rows = db.execute(text(f"""
        SELECT body FROM canon_items
        WHERE type = 'SESSION_SUMMARY'
          AND is_active = TRUE
          AND created_at >= :since
          {pid_clause}
        ORDER BY created_at DESC
        LIMIT 10
    """), params).fetchall()

    return [row.body for row in rows if row.body]


def _load_existing_skills(db: Session) -> Dict[str, Dict[str, str]]:
    rows = db.execute(text(
        "SELECT name, description, category FROM brain_skills"
    )).fetchall()
    return {
        row.name: {"description": row.description or "", "category": row.category}
        for row in rows
    }


def _upsert_skill(
    db: Session, name: str, description: str, category: str, content: str
) -> None:
    now = datetime.now(timezone.utc)
    db.execute(text("""
        INSERT INTO brain_skills (name, description, content, category, created_at, updated_at)
        VALUES (:name, :description, :content, :category, :now, :now)
        ON CONFLICT (name) DO UPDATE SET
            description = EXCLUDED.description,
            content     = EXCLUDED.content,
            category    = EXCLUDED.category,
            updated_at  = EXCLUDED.updated_at
    """), {
        "name": name,
        "description": description,
        "content": content,
        "category": category,
        "now": now,
    })


# ── LLM distillation ──────────────────────────────────────────────────────────

def _call_llm(prompt: str) -> Optional[Dict[str, Any]]:
    try:
        resp = _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "null"
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as exc:
        logger.warning("skill_distiller._call_llm: %s", exc)
        return None


def _distill_error_cluster(cluster: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    errors = cluster["errors"][:8]
    errors_text = "\n---\n".join(
        f"Pattern: {e['pattern']}\nSolution: {e['solution']}\nExample: {e['example']}"
        for e in errors
    )
    return _call_llm(_ERROR_PROMPT.format(
        count=len(errors),
        error_type=cluster["error_type"],
        errors_text=errors_text,
    ))


def _distill_session_summaries(summaries: List[str]) -> Optional[Dict[str, Any]]:
    texts = summaries[:6]
    summaries_text = "\n---\n".join(t[:600] for t in texts)
    return _call_llm(_SUMMARY_PROMPT.format(
        count=len(texts),
        summaries_text=summaries_text,
    ))


# ── Slug validation ───────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,38}[a-z0-9]$")


def _valid_slug(name: str) -> bool:
    return bool(_SLUG_RE.match(name))


# ── Public API ────────────────────────────────────────────────────────────────

def distill(
    project_id: Optional[int] = None,
    since_days: int = 30,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Distill brain_skills from resolved errors + recent session summaries.

    Args:
        project_id: Limit sources to one project (None = cross-project).
        since_days: Look back this many days for source material.
        dry_run:    If True, return proposals without saving to DB.

    Returns:
        {"proposed": [...], "saved": [...], "skipped": [...], "dry_run": bool}
    """
    db = _open_db()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        error_clusters = _load_error_clusters(db, project_id, since)
        summaries = _load_session_summaries(db, project_id, since)
        existing = _load_existing_skills(db)
    finally:
        db.close()

    proposals: List[Dict[str, Any]] = []

    for cluster in error_clusters:
        skill = _distill_error_cluster(cluster)
        if skill:
            proposals.append({**skill, "source": f"error:{cluster['error_type']}"})

    if summaries:
        skill = _distill_session_summaries(summaries)
        if skill:
            proposals.append({**skill, "source": "session_summaries"})

    proposed_out: List[Dict] = []
    saved_out: List[Dict] = []
    skipped_out: List[Dict] = []
    new_count = 0

    db2 = _open_db()
    try:
        for proposal in proposals:
            name = (proposal.get("name") or "").strip().lower()
            if not name or not _valid_slug(name):
                skipped_out.append({"name": name or "(empty)", "reason": "invalid slug"})
                continue

            cat = proposal.get("category", "")
            if cat not in _VALID_CATEGORIES:
                cat = "debug" if "error" in proposal.get("source", "") else "workflow"

            existing_entry = existing.get(name)
            is_update = False
            if existing_entry:
                if not existing_entry["description"].startswith(_AUTO_MARKER):
                    skipped_out.append({"name": name, "reason": "manual skill — will not overwrite"})
                    continue
                is_update = True
            elif new_count >= _MAX_NEW_SKILLS:
                skipped_out.append({"name": name, "reason": f"cap reached (max {_MAX_NEW_SKILLS} new per run)"})
                continue

            description = f"{_AUTO_MARKER} {(proposal.get('description') or '')}"[:120]
            content = (proposal.get("content") or "")[:1500]

            entry: Dict[str, Any] = {
                "name": name,
                "category": cat,
                "description": description,
                "content": content,
                "action": "update" if is_update else "insert",
                "source": proposal.get("source"),
            }
            proposed_out.append(entry)

            if not dry_run:
                _upsert_skill(db2, name, description, cat, content)
                saved_out.append(entry)

            if not is_update:
                new_count += 1

        if not dry_run:
            db2.commit()
    except Exception:
        if not dry_run:
            db2.rollback()
        raise
    finally:
        db2.close()

    logger.info(
        "skill_distiller: proposed=%d saved=%d skipped=%d dry_run=%s",
        len(proposed_out), len(saved_out), len(skipped_out), dry_run,
    )
    return {
        "proposed": proposed_out,
        "saved": saved_out,
        "skipped": skipped_out,
        "dry_run": dry_run,
    }
