"""
Traces read API.

GET /api/traces         — recent traces, filterable by kind/status, paginated
GET /api/traces/{trace_id} — span timeline for one trace, ordered by seq
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_current_active_user
from app.memory.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/traces")
def list_traces(
    kind: Optional[str] = Query(None, description="Filter by kind: query|verify|eval|tool"),
    status: Optional[str] = Query(None, description="Filter by status: ok|error"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user=Depends(get_current_active_user),
):
    """Return recent traces, newest first."""
    params: dict = {"limit": limit, "offset": offset}
    filters = ""
    if kind:
        filters += " AND kind = :kind"
        params["kind"] = kind
    if status:
        filters += " AND status = :status"
        params["status"] = status

    rows = db.execute(text(f"""
        SELECT trace_id, kind, summary, status,
               total_cost_usd, total_ms, created_at
        FROM brain_traces
        WHERE 1=1 {filters}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM brain_traces WHERE 1=1 {filters}
    """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar() or 0

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "traces": [
            {
                "trace_id":      r.trace_id,
                "kind":          r.kind,
                "summary":       r.summary,
                "status":        r.status,
                "total_cost_usd": r.total_cost_usd,
                "total_ms":      r.total_ms,
                "created_at":    str(r.created_at),
            }
            for r in rows
        ],
    }


@router.get("/traces/{trace_id}")
def get_trace(
    trace_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_active_user),
):
    """Return the span timeline for one trace, ordered by seq."""
    trace_row = db.execute(text("""
        SELECT trace_id, kind, summary, status,
               total_cost_usd, total_ms, created_at
        FROM brain_traces
        WHERE trace_id = :trace_id
        LIMIT 1
    """), {"trace_id": trace_id}).fetchone()

    if trace_row is None:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    spans = db.execute(text("""
        SELECT seq, layer, name, status,
               input_summary, output_summary, error,
               model_key, cost_usd, duration_ms, created_at
        FROM brain_trace_spans
        WHERE trace_id = :trace_id
        ORDER BY seq ASC
    """), {"trace_id": trace_id}).fetchall()

    return {
        "trace_id":      trace_row.trace_id,
        "kind":          trace_row.kind,
        "summary":       trace_row.summary,
        "status":        trace_row.status,
        "total_cost_usd": trace_row.total_cost_usd,
        "total_ms":      trace_row.total_ms,
        "created_at":    str(trace_row.created_at),
        "spans": [
            {
                "seq":            s.seq,
                "layer":          s.layer,
                "name":           s.name,
                "status":         s.status,
                "input_summary":  s.input_summary,
                "output_summary": s.output_summary,
                "error":          s.error,
                "model_key":      s.model_key,
                "cost_usd":       s.cost_usd,
                "duration_ms":    s.duration_ms,
                "created_at":     str(s.created_at),
            }
            for s in spans
        ],
    }
