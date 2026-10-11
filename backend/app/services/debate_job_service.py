"""
Debate Job Service — async start/poll pattern (Phase 4).

debate_start() inserts a job row, spawns a background asyncio task, and returns
immediately.  The background task runs run_debate() under a hard asyncio.wait_for
cap and writes result/status to the DB row when done.

debate_result() reads the row and handles stale "running" rows left by a process
restart.

Module-level hooks (_debate_run_fn, _job_store) allow evals to stub both the
debate engine and the DB layer without requiring the debate_jobs table.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import text

from app.memory.db import SessionLocal

logger = logging.getLogger(__name__)

# ── Analysis-gate: deterministic, no model call ──────────────────────────────
# Patterns that indicate a review/summary/audit task (answer directly, don't debate)
_ANALYSIS_RE = re.compile(
    r"\b(review|preview|audit|summarize|summarise|explain|overview|"
    r"prioritize|prioritise|recommend|"
    r"what\s+should\s+(we|i)\s+(improve|fix|change|do)|"
    r"how\s+do\s+(i|we)\s+use|"
    r"look\s+at\s+\S|"
    r"give\s+(me|us)\s+(a\s+)?(summary|list|overview|review|recommendation)|"
    r"tell\s+me\s+(about|what))\b",
    re.IGNORECASE,
)
# Patterns that signal a genuine high-stakes decision — gate lets these through
_DECISION_RE = re.compile(
    r"\b(vs\.?|versus|tradeoff|trade.off|migrat|irreversible|"
    r"optimistic|pessimistic|"
    r"(should\s+we|should\s+i)\s+(use|choose|adopt|switch|replace|rewrite|refactor|"
    r"drop|deploy|implement|introduce|build|design|architect))\b",
    re.IGNORECASE,
)


def _debate_analysis_gate(question: str, force: bool) -> Optional[dict]:
    """
    Cheap deterministic pre-check. Returns a skip-dict when the question looks
    like an analysis/review task (not a high-stakes decision), or None when the
    debate should proceed.

    force=True bypasses the gate entirely — for genuine edge cases.
    """
    if force:
        return None
    analysis_match = _ANALYSIS_RE.search(question)
    if not analysis_match:
        return None
    decision_match = _DECISION_RE.search(question)
    if decision_match:
        return None  # contains a decision signal — let it through
    return {
        "skipped": True,
        "reason": (
            "This looks like an analysis/review task, not a high-stakes decision. "
            "Answer directly. Pass force=true to override."
        ),
        "matched": [analysis_match.group(0)],
    }


# ── Runtime cap (seconds) — overridable via DEBATE_JOB_MAX_S env var ─────────
_JOB_MAX_S: float = float(os.environ.get("DEBATE_JOB_MAX_S", "180"))

# ── Live task references (prevents GC of running tasks) ──────────────────────
_BACKGROUND_TASKS: set = set()

# ── Module-level alias: evals replace this to stub run_debate ────────────────
try:
    from app.services.debate_engine import run_debate as _debate_run_fn_default
except Exception:  # pragma: no cover
    _debate_run_fn_default = None  # type: ignore

_debate_run_fn = _debate_run_fn_default  # type: ignore

# ── In-memory job store for evals (None = use real DB) ───────────────────────
_job_store: Optional[Dict[str, dict]] = None


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _is_pg() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    return url.startswith("postgresql") or url.startswith("postgres:")


def _db_write_job(
    debate_id: str,
    status: str,
    params: Optional[dict] = None,
    result: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    """Write or update a debate job row. Called synchronously (via to_thread)."""
    db = SessionLocal()
    ts_fn = "NOW()" if _is_pg() else "CURRENT_TIMESTAMP"
    try:
        exists = db.execute(
            text("SELECT 1 FROM debate_jobs WHERE debate_id = :did"),
            {"did": debate_id},
        ).fetchone()
        result_json = json.dumps(result, ensure_ascii=False) if result is not None else None
        params_json = json.dumps(params or {}, ensure_ascii=False)
        if exists:
            db.execute(
                text(
                    f"UPDATE debate_jobs SET status=:status, result=:result, "
                    f"error=:error, updated_at={ts_fn} WHERE debate_id=:did"
                ),
                {"did": debate_id, "status": status, "result": result_json, "error": error},
            )
        else:
            db.execute(
                text(
                    "INSERT INTO debate_jobs (debate_id, status, params, result, error) "
                    "VALUES (:did, :status, :params, :result, :error)"
                ),
                {
                    "did": debate_id, "status": status, "params": params_json,
                    "result": result_json, "error": error,
                },
            )
        db.commit()
    except Exception as exc:
        logger.warning("debate_job db_write error (%s): %s", debate_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _db_read_job(debate_id: str) -> Optional[dict]:
    """Read one debate job row. Returns None if not found."""
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                "SELECT debate_id, status, params, result, error, "
                "created_at, updated_at FROM debate_jobs WHERE debate_id = :did"
            ),
            {"did": debate_id},
        ).fetchone()
        if not row:
            return None
        result_raw = row[3]
        # result may be a string (SQLite TEXT) or already parsed (PG JSONB)
        if isinstance(result_raw, str):
            try:
                result_raw = json.loads(result_raw)
            except Exception:
                pass
        return {
            "debate_id":  row[0],
            "status":     row[1],
            "params":     json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {}),
            "result":     result_raw,
            "error":      row[4],
            "created_at": str(row[5]),
            "updated_at": str(row[6]),
        }
    except Exception as exc:
        logger.warning("debate_job db_read error (%s): %s", debate_id, exc)
        return None
    finally:
        db.close()


def _db_mark_timeout(debate_id: str) -> None:
    db = SessionLocal()
    ts_fn = "NOW()" if _is_pg() else "CURRENT_TIMESTAMP"
    try:
        db.execute(
            text(
                f"UPDATE debate_jobs SET status='timeout', "
                f"error='stale job — process restarted', updated_at={ts_fn} "
                f"WHERE debate_id=:did"
            ),
            {"did": debate_id},
        )
        db.commit()
    except Exception:
        pass
    finally:
        db.close()


# ── Job store indirection (patchable by evals) ────────────────────────────────

def _write_job(
    debate_id: str, status: str, params=None, result=None, error=None
) -> None:
    if _job_store is not None:
        _job_store[debate_id] = {
            "debate_id":  debate_id,
            "status":     status,
            "params":     params or {},
            "result":     result,
            "error":      error,
            "created_at": "",
            "updated_at": "",
        }
        return
    _db_write_job(debate_id, status, params=params, result=result, error=error)


def _read_job(debate_id: str) -> Optional[dict]:
    if _job_store is not None:
        return _job_store.get(debate_id)
    return _db_read_job(debate_id)


# ─── Background job runner ────────────────────────────────────────────────────

async def _job_runner(
    debate_id: str,
    question: str,
    project_id: Optional[int],
    folder_identifier: Optional[str],
    rounds: int,
    verify: bool,
) -> None:
    """Background coroutine. Runs debate under a hard timeout. Never raises."""
    try:
        _fn = _debate_run_fn
        if _fn is None:
            raise RuntimeError("run_debate not available")
        use_ctx = project_id is not None or bool(folder_identifier)
        result: dict = await asyncio.wait_for(
            _fn(
                question=question,
                rounds=rounds,
                verify=verify,
                project_id=project_id,
                folder_identifier=folder_identifier,
                use_context=use_ctx,
            ),
            timeout=_JOB_MAX_S,
        )
        await asyncio.to_thread(_write_job, debate_id, "done", result=result)
    except asyncio.TimeoutError:
        err = f"debate timed out after {_JOB_MAX_S}s"
        logger.warning("debate_job timeout: %s", debate_id)
        await asyncio.to_thread(_write_job, debate_id, "timeout", error=err)
    except Exception as exc:
        logger.error("debate_job error (%s): %s", debate_id, exc, exc_info=True)
        await asyncio.to_thread(_write_job, debate_id, "error", error=str(exc))


# ─── Public API ───────────────────────────────────────────────────────────────

async def start_job(
    question: str,
    project_id: Optional[int] = None,
    folder_identifier: Optional[str] = None,
    rounds: int = 1,
    verify: bool = True,
) -> str:
    """
    Insert a running job row, spawn the background task, return debate_id.
    Returns immediately — the caller should poll get_job(debate_id).
    """
    debate_id = str(uuid.uuid4())
    params = {
        "question":          question,
        "project_id":        project_id,
        "folder_identifier": folder_identifier,
        "rounds":            rounds,
        "verify":            verify,
    }
    await asyncio.to_thread(_write_job, debate_id, "running", params=params)

    task = asyncio.create_task(
        _job_runner(debate_id, question, project_id, folder_identifier, rounds, verify)
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return debate_id


async def get_job(debate_id: str) -> dict:
    """
    Read a debate job. Handles stale 'running' rows (process restart detection).
    Returns a dict with at least {debate_id, status}.
    """
    row = await asyncio.to_thread(_read_job, debate_id)
    if row is None:
        return {"debate_id": debate_id, "status": "not_found"}

    # Stale-job detection: if still "running" but older than cap + buffer, mark timeout.
    if row["status"] == "running":
        try:
            updated_raw = row.get("updated_at", "")
            if updated_raw and str(updated_raw).strip():
                dt = None
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                    try:
                        dt = datetime.strptime(str(updated_raw).strip(), fmt)
                        break
                    except ValueError:
                        continue
                if dt is not None:
                    age_s = (datetime.utcnow() - dt).total_seconds()
                    if age_s > _JOB_MAX_S + 30:
                        await asyncio.to_thread(_db_mark_timeout, debate_id)
                        row["status"] = "timeout"
                        row["error"] = "stale job — process restarted"
        except Exception:
            pass  # best-effort; don't fail a poll on timestamp parse error

    return row
