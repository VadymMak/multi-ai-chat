"""
Brain effectiveness tracking.

Compares Claude Code requests that used Brain context (via MCP tools) against
those that did not, on three axes: token usage, cost, and edit success / retry
count. Used to compute ROI for Smart Context.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def record_request(
    db: Session,
    *,
    project_id: Optional[int],
    usage_log_id: Optional[int],
    used_brain: bool,
    request_kind: Optional[str] = None,
    tokens_used: int = 0,
    cost_usd: float = 0.0,
    retries: int = 0,
    edit_successful: Optional[bool] = None,
    time_to_complete_ms: Optional[int] = None,
    brain_tokens_added: int = 0,
    brain_tools_called: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> int:
    """Insert a single brain_effectiveness row, return its id."""
    dialect = db.bind.dialect.name if db.bind else "postgresql"
    tools_param: Any = brain_tools_called or []
    if dialect != "postgresql":
        tools_param = json.dumps(tools_param)

    params = {
        "project_id": project_id,
        "usage_log_id": usage_log_id,
        "used_brain": used_brain if dialect == "postgresql" else (1 if used_brain else 0),
        "request_kind": request_kind,
        "tokens_used": tokens_used,
        "cost_usd": cost_usd,
        "retries": retries,
        "edit_successful": (
            edit_successful if dialect == "postgresql"
            else (None if edit_successful is None else (1 if edit_successful else 0))
        ),
        "time_to_complete_ms": time_to_complete_ms,
        "brain_tokens_added": brain_tokens_added,
        "brain_tools_called": tools_param,
        "notes": notes,
    }

    row = db.execute(
        text("""
            INSERT INTO brain_effectiveness (
                project_id, usage_log_id, used_brain, request_kind,
                tokens_used, cost_usd, retries, edit_successful,
                time_to_complete_ms, brain_tokens_added, brain_tools_called, notes
            ) VALUES (
                :project_id, :usage_log_id, :used_brain, :request_kind,
                :tokens_used, :cost_usd, :retries, :edit_successful,
                :time_to_complete_ms, :brain_tokens_added, :brain_tools_called, :notes
            )
            RETURNING id
        """) if dialect == "postgresql" else text("""
            INSERT INTO brain_effectiveness (
                project_id, usage_log_id, used_brain, request_kind,
                tokens_used, cost_usd, retries, edit_successful,
                time_to_complete_ms, brain_tokens_added, brain_tools_called, notes
            ) VALUES (
                :project_id, :usage_log_id, :used_brain, :request_kind,
                :tokens_used, :cost_usd, :retries, :edit_successful,
                :time_to_complete_ms, :brain_tokens_added, :brain_tools_called, :notes
            )
        """),
        params,
    )
    db.commit()
    if dialect == "postgresql":
        return int(row.scalar() or 0)
    last = db.execute(text("SELECT last_insert_rowid()")).scalar()
    return int(last or 0)


def backfill_from_usage_logs(db: Session, project_id: Optional[int] = None) -> int:
    """
    Incrementally sync brain_effectiveness rows from claude_usage_logs.
    Only inserts rows whose usage_log_id is not yet in brain_effectiveness.
    Safe to call repeatedly — never deletes existing rows.
    Returns the number of newly inserted rows.
    """
    project_filter = "AND c.project_id = :pid" if project_id is not None else ""
    params: Dict[str, Any] = {"pid": project_id} if project_id is not None else {}

    dialect = db.bind.dialect.name if db.bind else "postgresql"
    if dialect == "postgresql":
        result = db.execute(
            text(f"""
                INSERT INTO brain_effectiveness (
                    project_id, usage_log_id, used_brain,
                    tokens_used, cost_usd, retries,
                    brain_tools_called
                )
                SELECT
                    c.project_id, c.id, c.used_brain_context,
                    c.total_tokens, c.cost_usd,
                    CASE WHEN c.had_retry THEN 1 ELSE 0 END,
                    c.brain_tools_called
                FROM claude_usage_logs c
                WHERE NOT EXISTS (
                    SELECT 1 FROM brain_effectiveness b WHERE b.usage_log_id = c.id
                )
                {project_filter}
            """),
            params,
        )
        inserted = result.rowcount
    else:
        result = db.execute(
            text(f"""
                INSERT INTO brain_effectiveness (
                    project_id, usage_log_id, used_brain,
                    tokens_used, cost_usd, retries,
                    brain_tools_called
                )
                SELECT
                    c.project_id, c.id, c.used_brain_context,
                    c.total_tokens, c.cost_usd,
                    c.had_retry,
                    c.brain_tools_called
                FROM claude_usage_logs c
                WHERE NOT EXISTS (
                    SELECT 1 FROM brain_effectiveness b WHERE b.usage_log_id = c.id
                )
                {project_filter}
            """),
            params,
        )
        inserted = result.rowcount

    db.commit()
    return int(inserted or 0)


def compute_summary(
    db: Session,
    project_id: Optional[int] = None,
    days: Optional[int] = None,
) -> Dict[str, Any]:
    """Compare with-Brain vs without-Brain requests."""
    from datetime import datetime, timedelta

    conditions: List[str] = []
    params: Dict[str, Any] = {}

    if project_id is not None:
        conditions.append("b.project_id = :pid")
        params["pid"] = project_id
    if days and days > 0:
        since = datetime.utcnow() - timedelta(days=int(days))
        conditions.append("b.created_at >= :since")
        params["since"] = since

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    dialect = db.bind.dialect.name if db.bind else "postgresql"

    rows = db.execute(
        text(f"""
            SELECT
                b.used_brain AS used_brain,
                COUNT(*)                AS request_count,
                COALESCE(AVG(b.tokens_used), 0)  AS avg_tokens,
                COALESCE(AVG(b.cost_usd), 0)     AS avg_cost,
                COALESCE(SUM(b.cost_usd), 0)     AS total_cost,
                COALESCE(SUM(b.retries), 0)      AS total_retries
            FROM brain_effectiveness b
            {where}
            GROUP BY b.used_brain
        """),
        params,
    ).fetchall()

    with_brain = {"requests": 0, "avg_tokens": 0.0, "avg_cost": 0.0,
                  "total_cost": 0.0, "retries": 0}
    without_brain = dict(with_brain)

    for r in rows:
        bucket = with_brain if (r.used_brain in (True, 1)) else without_brain
        bucket["requests"] = int(r.request_count or 0)
        bucket["avg_tokens"] = float(r.avg_tokens or 0.0)
        bucket["avg_cost"] = float(r.avg_cost or 0.0)
        bucket["total_cost"] = float(r.total_cost or 0.0)
        bucket["retries"] = int(r.total_retries or 0)

    token_savings_pct: Optional[float] = None
    cost_savings_pct: Optional[float] = None
    if without_brain["avg_tokens"] > 0:
        token_savings_pct = round(
            (without_brain["avg_tokens"] - with_brain["avg_tokens"])
            / without_brain["avg_tokens"] * 100.0, 2
        )
    if without_brain["avg_cost"] > 0:
        cost_savings_pct = round(
            (without_brain["avg_cost"] - with_brain["avg_cost"])
            / without_brain["avg_cost"] * 100.0, 2
        )

    retry_rate_with = (with_brain["retries"] / with_brain["requests"]
                       if with_brain["requests"] else None)
    retry_rate_without = (without_brain["retries"] / without_brain["requests"]
                          if without_brain["requests"] else None)

    return {
        "project_id": project_id,
        "days": days,
        "with_brain": with_brain,
        "without_brain": without_brain,
        "token_savings_pct": token_savings_pct,
        "cost_savings_pct": cost_savings_pct,
        "retry_rate_with_brain": retry_rate_with,
        "retry_rate_without_brain": retry_rate_without,
    }
