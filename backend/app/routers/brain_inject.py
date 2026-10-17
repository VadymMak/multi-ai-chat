"""
GET /api/brain/inject — B-Lite inline injection for UserPromptSubmit hook.

Searches pitfalls (learned_errors) and skills (brain_skills) for the
top-1 match above BRAIN_INJECT_MIN_SCORE threshold. Returns a short
system-reminder string (≤400 tokens ≈ 1600 chars) or empty string
if no relevant match found.

Kill-switch: BRAIN_INJECT_ENABLED=false → empty response immediately.
Hard timeout guard is on the caller side (hook uses urllib with 0.5s timeout).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_active_user
from app.memory.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/brain", tags=["brain-inject"])

_MIN_SCORE: float = float(os.environ.get("BRAIN_INJECT_MIN_SCORE", "0.60"))
_MIN_MATCHES: int = int(os.environ.get("BRAIN_INJECT_MIN_MATCHES", "2"))
_ENABLED: bool = os.environ.get("BRAIN_INJECT_ENABLED", "true").lower() not in ("false", "0", "no")
_MAX_CHARS: int = 1600  # ≈400 tokens


class InjectResponse(BaseModel):
    injection: str = ""
    score: float = 0.0
    source: str = ""  # "pitfall", "skill", "empty"


def _keyword_score(text_blob: str, query: str) -> tuple[float, int]:
    """Return (fraction, num_matches) for query words (len>3) in text_blob."""
    words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 3]
    if not words:
        return 0.0, 0
    blob = text_blob.lower()
    matched = [w for w in words if w in blob]
    return len(matched) / len(words), len(matched)


@router.get("/inject", response_model=InjectResponse)
def brain_inject(
    q: str = Query(..., max_length=500),
    project: Optional[str] = Query(None, max_length=255),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> InjectResponse:
    """Return top-1 relevant lesson/pitfall injected as a system-reminder."""
    if not _ENABLED:
        return InjectResponse()

    best_injection = ""
    best_score = 0.0
    best_source = "empty"
    best_error_id: Optional[int] = None
    best_skill_id: Optional[int] = None

    best_matches = 0

    # ── Search pitfalls (learned_errors) ─────────────────────────────
    try:
        rows = db.execute(text("""
            SELECT id, error_pattern, solution_pattern, error_type
            FROM learned_errors
            WHERE solution_pattern IS NOT NULL
              AND occurrence_count >= 1
            ORDER BY occurrence_count DESC
            LIMIT 200
        """)).fetchall()
        for row in rows:
            blob = f"{row.error_pattern or ''} {row.solution_pattern or ''}"
            score, n_matches = _keyword_score(blob, q)
            if score > best_score:
                best_score = score
                best_matches = n_matches
                best_source = "pitfall"
                best_error_id = row.id
                best_skill_id = None
                best_injection = (
                    f"⚠️ KNOWN PITFALL ({row.error_type}): {row.error_pattern}. "
                    f"Fix: {row.solution_pattern}"
                )
    except Exception:
        logger.exception("[brain-inject] pitfall search failed")

    # ── Search skills (brain_skills) — skip huge meta-skills ─────────
    try:
        skill_rows = db.execute(text("""
            SELECT id, name, description, content, category
            FROM brain_skills
            WHERE length(content) <= 2000
            ORDER BY updated_at DESC
            LIMIT 50
        """)).fetchall()
        for row in skill_rows:
            blob = f"{row.name or ''} {row.description or ''} {row.content or ''}"
            score, n_matches = _keyword_score(blob, q)
            if score > best_score:
                best_score = score
                best_matches = n_matches
                best_source = "skill"
                best_skill_id = row.id
                best_error_id = None
                best_injection = f"📚 SKILL [{row.name}]: {row.content}"
    except Exception:
        logger.exception("[brain-inject] skill search failed")

    # ── Threshold gate: fraction >= MIN_SCORE AND matched words >= MIN_MATCHES
    if best_score < _MIN_SCORE or best_matches < _MIN_MATCHES or not best_injection:
        _log_inject(db, q, project, "empty", 0.0, "", None, None)
        return InjectResponse()

    # Truncate to ≤400 tokens (≈1600 chars)
    if len(best_injection) > _MAX_CHARS:
        best_injection = best_injection[:_MAX_CHARS].rsplit(" ", 1)[0] + "…"

    injection_text = (
        f"<system-reminder>\n{best_injection}\n</system-reminder>"
    )

    _log_inject(db, q, project, best_source, best_score, injection_text, best_error_id, best_skill_id)
    logger.info(
        "[brain-inject] injected score=%.2f source=%s project=%s",
        best_score, best_source, project or "?",
    )
    return InjectResponse(injection=injection_text, score=best_score, source=best_source)


def _log_inject(
    db: Session,
    query: str,
    project_folder: Optional[str],
    source: str,
    score: float,
    injection_text: str,
    error_id: Optional[int],
    skill_id: Optional[int],
) -> None:
    try:
        db.execute(text("""
            INSERT INTO brain_inject_log
                (query, project_folder, source, score, injection_text, error_id, skill_id)
            VALUES
                (:q, :pf, :src, :score, :txt, :eid, :sid)
        """), {
            "q": query[:500],
            "pf": project_folder,
            "src": source,
            "score": score,
            "txt": injection_text[:2000],
            "eid": error_id,
            "sid": skill_id,
        })
        db.commit()
    except Exception:
        logger.debug("[brain-inject] log write failed (table may not exist yet)")
