"""
Usage analytics API.

Endpoints surface the data populated by `claude_usage_parser.py` into
`claude_usage_logs` / `usage_daily_stats` / `brain_effectiveness`.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import psycopg2
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.deps import get_current_active_user, get_db
from app.memory.models import User
from app.services.brain_effectiveness import backfill_from_usage_logs, compute_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usage", tags=["usage-analytics"])


# ─── response models ─────────────────────────────────────────────
class ProjectStats(BaseModel):
    project_id: Optional[int]
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int
    total_tokens: int
    total_cost_usd: float
    cache_savings_usd: float
    brain_assisted_requests: int
    by_model: List[Dict[str, Any]]
    period_start: Optional[str]
    period_end: Optional[str]


class DailyEntry(BaseModel):
    date: str
    project_id: Optional[int]
    project_name: Optional[str]
    model: str
    request_count: int
    total_tokens: int
    cost_usd: float
    cache_savings_usd: float


class ModelBreakdownEntry(BaseModel):
    model: str
    request_count: int
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_tokens: int
    cost_usd: float


class CostSummary(BaseModel):
    total_cost_usd: float
    total_cache_savings_usd: float
    total_requests: int
    total_tokens: int
    period_days: int
    by_model: List[ModelBreakdownEntry]


class SyncResponse(BaseModel):
    files_scanned: int = 0
    records_parsed: int = 0
    inserted: int = 0
    skipped: int = 0
    daily_stat_rows: int = 0
    root: Optional[str] = None
    total_cost_usd: float = 0.0


class UsageRecordIn(BaseModel):
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    request_id: Optional[str] = None
    timestamp: str
    model: str
    project_path: Optional[str] = None
    project_name: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: Optional[int] = None
    cost_usd: float = 0.0
    cost_without_cache_usd: float = 0.0
    cache_savings_usd: float = 0.0
    used_brain_context: bool = False
    brain_tools_called: List[str] = Field(default_factory=list)
    had_retry: bool = False
    raw_jsonl_path: Optional[str] = None
    surface: str = "code"
    brain_mode: str = "enabled"
    session_retry_count: int = 0


class SyncRequest(BaseModel):
    records: Optional[List[UsageRecordIn]] = None
    daily_stats: Optional[List[Dict[str, Any]]] = None


# ─── helpers ─────────────────────────────────────────────────────
def _extract_project_slug(raw: Optional[str]) -> Optional[str]:
    """Extract real project name from a Claude Code folder identifier.

    Claude Code encodes the project path as a dash-joined string, e.g.:
      "-Users-vadymmak-Documents-projects-mamalog" → "mamalog"
      "f--projects-multi-ai-chat"                  → "multi-ai-chat"
    We split on the literal "-projects-" marker and take everything after it.
    """
    if not raw:
        return None
    marker = "-projects-"
    idx = raw.find(marker)
    if idx != -1:
        return raw[idx + len(marker):]
    return raw.rstrip("/").split("/")[-1]


def _since_clause(days: Optional[int]) -> tuple[str, Dict[str, Any]]:
    if days is None or days <= 0:
        return "", {}
    since = datetime.utcnow() - timedelta(days=days)
    return " AND timestamp >= :since ", {"since": since}


# ─── endpoints ───────────────────────────────────────────────────
@router.get("/stats/{project_id}", response_model=ProjectStats)
def get_project_stats(
    project_id: int,
    days: int = Query(30, ge=1, le=3650),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    since_sql, since_params = _since_clause(days)
    params: Dict[str, Any] = {"project_id": project_id, **since_params}

    totals = db.execute(
        text(f"""
            SELECT
                COUNT(*) AS req,
                COALESCE(SUM(input_tokens), 0)         AS in_t,
                COALESCE(SUM(output_tokens), 0)        AS out_t,
                COALESCE(SUM(cache_creation_tokens),0) AS cc_t,
                COALESCE(SUM(cache_read_tokens), 0)    AS cr_t,
                COALESCE(SUM(total_tokens), 0)         AS tot_t,
                COALESCE(SUM(cost_usd), 0)             AS cost,
                COALESCE(SUM(cache_savings_usd), 0)    AS savings,
                COALESCE(SUM(CASE WHEN used_brain_context THEN 1 ELSE 0 END), 0) AS brain_req,
                MIN(timestamp) AS first_ts,
                MAX(timestamp) AS last_ts
            FROM claude_usage_logs
            WHERE project_id = :project_id {since_sql}
        """),
        params,
    ).fetchone()

    by_model_rows = db.execute(
        text(f"""
            SELECT model,
                   COUNT(*) AS req,
                   COALESCE(SUM(total_tokens), 0) AS tokens,
                   COALESCE(SUM(cost_usd), 0)    AS cost
            FROM claude_usage_logs
            WHERE project_id = :project_id {since_sql}
            GROUP BY model
            ORDER BY cost DESC
        """),
        params,
    ).fetchall()

    by_model = [
        {
            "model": r.model,
            "request_count": int(r.req or 0),
            "tokens": int(r.tokens or 0),
            "cost_usd": float(r.cost or 0.0),
        }
        for r in by_model_rows
    ]

    return ProjectStats(
        project_id=project_id,
        total_requests=int(totals.req or 0),
        total_input_tokens=int(totals.in_t or 0),
        total_output_tokens=int(totals.out_t or 0),
        total_cache_creation_tokens=int(totals.cc_t or 0),
        total_cache_read_tokens=int(totals.cr_t or 0),
        total_tokens=int(totals.tot_t or 0),
        total_cost_usd=float(totals.cost or 0.0),
        cache_savings_usd=float(totals.savings or 0.0),
        brain_assisted_requests=int(totals.brain_req or 0),
        by_model=by_model,
        period_start=totals.first_ts.isoformat() if totals.first_ts else None,
        period_end=totals.last_ts.isoformat() if totals.last_ts else None,
    )


@router.get("/daily", response_model=List[DailyEntry])
def get_daily_breakdown(
    days: int = Query(30, ge=1, le=3650),
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    since_date = (datetime.utcnow().date() - timedelta(days=days)).isoformat()
    where = "WHERE date >= :since"
    params: Dict[str, Any] = {"since": since_date}
    if project_id is not None:
        where += " AND project_id = :project_id"
        params["project_id"] = project_id

    rows = db.execute(
        text(f"""
            SELECT date, project_id, project_name, model,
                   request_count, total_tokens, cost_usd, cache_savings_usd
            FROM usage_daily_stats
            {where}
            ORDER BY date DESC, cost_usd DESC
        """),
        params,
    ).fetchall()

    return [
        DailyEntry(
            date=str(r.date),
            project_id=r.project_id,
            project_name=r.project_name,
            model=r.model,
            request_count=int(r.request_count or 0),
            total_tokens=int(r.total_tokens or 0),
            cost_usd=float(r.cost_usd or 0.0),
            cache_savings_usd=float(r.cache_savings_usd or 0.0),
        )
        for r in rows
    ]


@router.get("/models", response_model=List[ModelBreakdownEntry])
def get_model_breakdown(
    days: int = Query(30, ge=1, le=3650),
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    since_sql, params = _since_clause(days)
    where = "WHERE 1=1" + since_sql
    if project_id is not None:
        where += " AND project_id = :project_id"
        params["project_id"] = project_id

    rows = db.execute(
        text(f"""
            SELECT model,
                   COUNT(*) AS req,
                   COALESCE(SUM(input_tokens), 0)        AS in_t,
                   COALESCE(SUM(output_tokens), 0)       AS out_t,
                   COALESCE(SUM(cache_creation_tokens),0) AS cc_t,
                   COALESCE(SUM(cache_read_tokens), 0)   AS cr_t,
                   COALESCE(SUM(total_tokens), 0)        AS tot_t,
                   COALESCE(SUM(cost_usd), 0)            AS cost
            FROM claude_usage_logs
            {where}
            GROUP BY model
            ORDER BY cost DESC
        """),
        params,
    ).fetchall()

    return [
        ModelBreakdownEntry(
            model=r.model,
            request_count=int(r.req or 0),
            input_tokens=int(r.in_t or 0),
            output_tokens=int(r.out_t or 0),
            cache_creation_tokens=int(r.cc_t or 0),
            cache_read_tokens=int(r.cr_t or 0),
            total_tokens=int(r.tot_t or 0),
            cost_usd=float(r.cost or 0.0),
        )
        for r in rows
    ]


@router.get("/cost", response_model=CostSummary)
def get_cost_summary(
    days: int = Query(30, ge=1, le=3650),
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    since_sql, params = _since_clause(days)
    where = "WHERE 1=1" + since_sql
    if project_id is not None:
        where += " AND project_id = :project_id"
        params["project_id"] = project_id

    totals = db.execute(
        text(f"""
            SELECT
                COUNT(*) AS req,
                COALESCE(SUM(total_tokens), 0)      AS tot_t,
                COALESCE(SUM(cost_usd), 0)          AS cost,
                COALESCE(SUM(cache_savings_usd), 0) AS savings
            FROM claude_usage_logs
            {where}
        """),
        params,
    ).fetchone()

    by_model = get_model_breakdown(days=days, project_id=project_id,
                                   db=db, current_user=current_user)

    return CostSummary(
        total_cost_usd=float(totals.cost or 0.0),
        total_cache_savings_usd=float(totals.savings or 0.0),
        total_requests=int(totals.req or 0),
        total_tokens=int(totals.tot_t or 0),
        period_days=days,
        by_model=by_model,
    )


@router.get("/brain-effectiveness")
def get_brain_effectiveness(
    project_id: Optional[int] = None,
    days: int = Query(30, ge=1, le=3650),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return compute_summary(db, project_id=project_id, days=days)


@router.post("/brain-effectiveness/backfill")
def run_brain_effectiveness_backfill(
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Idempotent UPSERT backfill: updates retries/tokens from session_retry_count."""
    inserted = backfill_from_usage_logs(db, project_id=project_id)
    return {"inserted": inserted, "project_id": project_id}


@router.get("/diag-retry")
def diag_retry(
    session_id: str = "861dc7f6-98f0-41a4-ac32-60cd535c50f5",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Diagnostic: verify retry pipeline for a session. Shows DB state for both layers."""
    results: Dict[str, Any] = {}

    # Layer 1: claude_usage_logs
    row1 = db.execute(text("""
        SELECT session_id,
               MAX(session_retry_count) AS session_retry_count,
               COUNT(*) AS msg_count
        FROM claude_usage_logs
        WHERE session_id = :sid
        GROUP BY session_id
    """), {"sid": session_id}).fetchone()
    results["layer1_claude_usage_logs"] = (
        {"session_id": session_id,
         "session_retry_count": row1.session_retry_count if row1 else None,
         "msg_count": row1.msg_count if row1 else 0,
         "ok": (row1.session_retry_count or 0) > 0 if row1 else False}
    )

    # Layer 2: brain_effectiveness
    rows2 = db.execute(text("""
        SELECT be.retries
        FROM brain_effectiveness be
        JOIN claude_usage_logs c ON be.usage_log_id = c.id
        WHERE c.session_id = :sid
        LIMIT 3
    """), {"sid": session_id}).fetchall()
    results["layer2_brain_effectiveness"] = {
        "retries_sample": [r.retries for r in rows2],
        "ok": any((r.retries or 0) > 0 for r in rows2),
    }

    # pg_constraint check
    try:
        constraints = db.execute(text("""
            SELECT conname, contype FROM pg_constraint
            WHERE conrelid = 'brain_effectiveness'::regclass
            ORDER BY conname
        """)).fetchall()
        results["pg_constraint_brain_effectiveness"] = [
            {"name": r.conname, "type": r.contype} for r in constraints
        ]
        results["uq_constraint_present"] = any(
            r.conname == "uq_brain_eff_usage_log" for r in constraints
        )
    except Exception as e:
        results["pg_constraint_error"] = str(e)

    # Top retries in claude_usage_logs
    top = db.execute(text("""
        SELECT session_id, MAX(session_retry_count) AS retries
        FROM claude_usage_logs
        GROUP BY session_id
        ORDER BY retries DESC NULLS LAST
        LIMIT 5
    """)).fetchall()
    results["top_retry_sessions"] = [
        {"session_id": r.session_id, "retries": r.retries} for r in top
    ]

    # Sample raw rows for the target session — check exact column values
    sample_rows = db.execute(text("""
        SELECT id, message_id, session_retry_count, had_retry, surface, brain_mode, timestamp
        FROM claude_usage_logs
        WHERE session_id = :sid
        ORDER BY timestamp DESC
        LIMIT 3
    """), {"sid": session_id}).fetchall()
    results["sample_rows_from_target_session"] = [
        {
            "id": r.id,
            "message_id": r.message_id,
            "session_retry_count": r.session_retry_count,
            "had_retry": r.had_retry,
            "surface": r.surface,
            "brain_mode": r.brain_mode,
        }
        for r in sample_rows
    ]

    # Check what session_retry_count distribution looks like globally
    dist = db.execute(text("""
        SELECT session_retry_count, COUNT(*) AS cnt
        FROM claude_usage_logs
        GROUP BY session_retry_count
        ORDER BY session_retry_count DESC
        LIMIT 10
    """)).fetchall()
    results["global_retry_count_distribution"] = [
        {"session_retry_count": r.session_retry_count, "rows": r.cnt} for r in dist
    ]

    # Direct UPDATE test: can we actually write session_retry_count?
    try:
        test_row = db.execute(text("""
            SELECT id, message_id FROM claude_usage_logs
            WHERE session_id = :sid AND message_id IS NOT NULL
            LIMIT 1
        """), {"sid": session_id}).fetchone()
        if test_row:
            db.execute(text("""
                UPDATE claude_usage_logs
                SET session_retry_count = 99
                WHERE id = :rid
            """), {"rid": test_row.id})
            db.commit()
            after = db.execute(text("""
                SELECT session_retry_count FROM claude_usage_logs WHERE id = :rid
            """), {"rid": test_row.id}).scalar()
            results["direct_update_test"] = {
                "row_id": test_row.id,
                "message_id": test_row.message_id,
                "set_to": 99,
                "read_back": after,
                "ok": after == 99,
            }
            # Restore to 0
            db.execute(text("""
                UPDATE claude_usage_logs SET session_retry_count = 0 WHERE id = :rid
            """), {"rid": test_row.id})
            db.commit()
    except Exception as e:
        results["direct_update_test"] = {"error": str(e)}

    return results


def _load_usage_parser():
    """Load backend/scripts/claude_usage_parser.py. Registers in sys.modules
    before exec so module-level @dataclass resolves correctly."""
    import importlib.util
    import os
    import sys
    path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "scripts", "claude_usage_parser.py"
    ))
    spec = importlib.util.spec_from_file_location("claude_usage_parser", path)
    if spec is None or spec.loader is None:
        raise HTTPException(500, "parser module not found")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod.__name__] = mod
    spec.loader.exec_module(mod)
    return mod


@router.post("/sync", response_model=SyncResponse)
def sync_usage_logs(
    payload: Optional[SyncRequest] = Body(None),
    since: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Sync Claude Code usage logs.

    With a JSON body containing `records`, insert those records directly
    (deduped by message_id via the parser's insert path).
    Without a body, parse `~/.claude/projects/*` on the server filesystem.
    """
    if settings.DISABLE_USAGE_SYNC:
        ignored = len(payload.records) if payload and payload.records else 0
        logger.debug("[usage/sync] kill-switch active — ignored %d records", ignored)
        return {"status": "disabled", "ignored": ignored}

    since_d: Optional[date] = None
    if since:
        try:
            since_d = date.fromisoformat(since)
        except ValueError:
            raise HTTPException(400, "since must be YYYY-MM-DD")

    mod = _load_usage_parser()

    if payload and payload.records:
        records = []
        for r in payload.records:
            try:
                ts = datetime.fromisoformat(r.timestamp.replace("Z", "+00:00"))
            except Exception:
                ts = datetime.utcnow()
            records.append(mod.UsageRecord(
                session_id=r.session_id,
                message_id=r.message_id,
                request_id=r.request_id,
                timestamp=ts,
                model=r.model,
                project_path=r.project_path,
                project_name=r.project_name,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                cache_creation_tokens=r.cache_creation_tokens,
                cache_read_tokens=r.cache_read_tokens,
                cost_usd=r.cost_usd,
                cost_without_cache_usd=r.cost_without_cache_usd,
                cache_savings_usd=r.cache_savings_usd,
                used_brain_context=r.used_brain_context,
                brain_tools_called=r.brain_tools_called or [],
                had_retry=r.had_retry,
                session_retry_count=r.session_retry_count,
                raw_jsonl_path=r.raw_jsonl_path or "",
            ))

        # ── Permanently block the retired Windows "eto" machine ──────────────
        # Its Claude Code logs carry Windows-style paths (backslashes / "C:\"),
        # while the active Mac uses POSIX "/Users/..." paths. Drop any
        # Windows-path records so that machine can never pollute usage stats
        # again — independent of the DISABLE_USAGE_SYNC kill-switch.
        def _is_windows_path(*paths: str) -> bool:
            for p in paths:
                if not p:
                    continue
                if "\\" in p or (len(p) >= 2 and p[1] == ":"):
                    return True
            return False

        _before = len(records)
        records = [
            rec for rec in records
            if not _is_windows_path(rec.raw_jsonl_path, rec.project_path)
        ]
        _blocked = _before - len(records)
        if _blocked:
            logger.info(
                "[usage/sync] blocked %d record(s) from retired Windows machine",
                _blocked,
            )

        logger.info(
            "POST /usage/sync received %d records (first model=%s, ts=%s)",
            len(records),
            records[0].model if records else None,
            records[0].timestamp.isoformat() if records else None,
        )
        if payload.records:
            logger.info(
                "first record payload: %s",
                payload.records[0].model_dump_json(),
            )

        # Bypass the SQLAlchemy session entirely — open a raw psycopg2
        # connection in autocommit mode so each INSERT runs in its own
        # transaction. A bad row fails on its own without poisoning the
        # connection, so no manual rollback is needed inside the loop.
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            raise HTTPException(500, "DATABASE_URL not configured")
        # psycopg2 doesn't accept SQLAlchemy dialect prefixes like postgresql+psycopg2://
        if db_url.startswith("postgresql+"):
            db_url = "postgresql://" + db_url.split("://", 1)[1]

        inserted = 0
        skipped = 0
        first_error_logged = False
        conn = None
        try:
            conn = psycopg2.connect(db_url)
            conn.autocommit = True  # each INSERT is independent
            cur = conn.cursor()
            insert_sql = """
                INSERT INTO claude_usage_logs (
                    session_id, message_id, request_id, timestamp, model,
                    project_id, project_path, project_name,
                    input_tokens, output_tokens, cache_creation_tokens,
                    cache_read_tokens, total_tokens,
                    cost_usd, cost_without_cache_usd, cache_savings_usd,
                    used_brain_context, brain_tools_called,
                    had_retry, raw_jsonl_path,
                    surface, brain_mode, session_retry_count
                ) VALUES (
                    %(session_id)s, %(message_id)s, %(request_id)s, %(timestamp)s, %(model)s,
                    (SELECT id FROM projects
                       WHERE name = %(project_name_lookup)s
                          OR folder_identifier = %(project_name_lookup)s
                       LIMIT 1),
                    %(project_path)s, %(project_name)s,
                    %(input_tokens)s, %(output_tokens)s, %(cache_creation_tokens)s,
                    %(cache_read_tokens)s, %(total_tokens)s,
                    %(cost_usd)s, %(cost_without_cache_usd)s, %(cache_savings_usd)s,
                    %(used_brain_context)s, %(brain_tools_called)s,
                    %(had_retry)s, %(raw_jsonl_path)s,
                    %(surface)s, %(brain_mode)s, %(session_retry_count)s
                )
                ON CONFLICT (message_id) DO UPDATE SET
                    session_retry_count = EXCLUDED.session_retry_count,
                    surface             = EXCLUDED.surface,
                    brain_mode          = EXCLUDED.brain_mode,
                    had_retry           = EXCLUDED.had_retry
                RETURNING id
            """
            for rec in records:
                params = {
                    "session_id": rec.session_id,
                    "message_id": rec.message_id,
                    "request_id": rec.request_id,
                    "timestamp": rec.timestamp,
                    "model": rec.model,
                    "project_path": rec.project_path,
                    "project_name": rec.project_name,
                    "project_name_lookup": _extract_project_slug(
                        rec.project_name or rec.project_path
                    ),
                    "input_tokens": rec.input_tokens,
                    "output_tokens": rec.output_tokens,
                    "cache_creation_tokens": rec.cache_creation_tokens,
                    "cache_read_tokens": rec.cache_read_tokens,
                    "total_tokens": rec.total_tokens,
                    "cost_usd": rec.cost_usd,
                    "cost_without_cache_usd": rec.cost_without_cache_usd,
                    "cache_savings_usd": rec.cache_savings_usd,
                    "used_brain_context": rec.used_brain_context,
                    "brain_tools_called": list(rec.brain_tools_called or []),
                    "had_retry": rec.had_retry,
                    "raw_jsonl_path": rec.raw_jsonl_path,
                    "surface": getattr(rec, "surface", "code") or "code",
                    "brain_mode": getattr(rec, "brain_mode", "enabled") or "enabled",
                    "session_retry_count": int(getattr(rec, "session_retry_count", 0) or 0),
                }
                try:
                    cur.execute(insert_sql, params)
                    if cur.fetchone():
                        inserted += 1
                    else:
                        skipped += 1
                except Exception:
                    # autocommit=True means the failed statement does NOT
                    # poison the connection — just count and move on.
                    skipped += 1
                    if not first_error_logged:
                        logger.exception(
                            "psycopg2 insert failed for message_id=%s",
                            rec.message_id,
                        )
                        first_error_logged = True
            # Bulk-stamp session_retry_count for ALL rows of each uploaded session,
            # not only the rows in this batch. This backfills older rows that were
            # inserted before session_retry_count was being sent correctly.
            session_counts: dict[str, int] = {}
            for rec in records:
                sid = rec.session_id
                cnt = int(getattr(rec, "session_retry_count", 0) or 0)
                if cnt > session_counts.get(sid, 0):
                    session_counts[sid] = cnt
            if session_counts:
                stamp_cur = conn.cursor()
                for sid, cnt in session_counts.items():
                    if cnt > 0:
                        stamp_cur.execute(
                            "UPDATE claude_usage_logs SET session_retry_count = %s WHERE session_id = %s AND session_retry_count != %s",
                            (cnt, sid, cnt),
                        )
                stamp_cur.close()

            cur.close()
        except Exception:
            logger.exception("psycopg2 upload path failed")
            raise HTTPException(500, "upload failed; see server logs")
        finally:
            if conn is not None:
                conn.close()

        insert_result = {"inserted": inserted, "skipped": skipped}
        daily_rows = mod.aggregate_daily(db)
        total_cost = sum(float(r.cost_usd or 0.0) for r in payload.records)

        if inserted > 0:
            try:
                backfill_from_usage_logs(db)
            except Exception:
                logger.exception("[usage/sync] brain_effectiveness backfill failed")

        return SyncResponse(
            files_scanned=0,
            records_parsed=len(records),
            inserted=insert_result["inserted"],
            skipped=insert_result["skipped"],
            daily_stat_rows=daily_rows,
            root="uploaded",
            total_cost_usd=total_cost,
        )

    result = mod.sync_usage(db, since=since_d)

    cost_sql = "SELECT COALESCE(SUM(cost_usd), 0) FROM claude_usage_logs"
    cost_params: Dict[str, Any] = {}
    if since_d:
        cost_sql += " WHERE timestamp >= :s"
        cost_params["s"] = since_d
    total_cost = float(db.execute(text(cost_sql), cost_params).scalar() or 0.0)

    if result.get("inserted", 0) > 0:
        try:
            backfill_from_usage_logs(db)
        except Exception:
            logger.exception("[usage/sync] brain_effectiveness backfill failed")

    return SyncResponse(**result, total_cost_usd=total_cost)
