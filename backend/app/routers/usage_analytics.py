"""
Usage analytics API.

Endpoints surface the data populated by `claude_usage_parser.py` into
`claude_usage_logs` / `usage_daily_stats` / `brain_effectiveness`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_current_active_user, get_db
from app.memory.models import User
from app.services.brain_effectiveness import compute_summary

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
    files_scanned: int
    records_parsed: int
    inserted: int
    skipped: int
    daily_stat_rows: int
    root: str


# ─── helpers ─────────────────────────────────────────────────────
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return compute_summary(db, project_id=project_id)


@router.post("/sync", response_model=SyncResponse)
def sync_usage_logs(
    since: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Trigger JSONL parsing of ~/.claude/projects/*."""
    since_d: Optional[date] = None
    if since:
        try:
            since_d = date.fromisoformat(since)
        except ValueError:
            raise HTTPException(400, "since must be YYYY-MM-DD")

    import importlib.util
    import os
    path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "scripts", "claude_usage_parser.py"
    ))
    spec = importlib.util.spec_from_file_location("claude_usage_parser", path)
    if spec is None or spec.loader is None:
        raise HTTPException(500, "parser module not found")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = mod.sync_usage(db, since=since_d)

    return SyncResponse(**result)
