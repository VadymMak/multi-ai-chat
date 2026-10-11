"""
Evals router.

POST /api/evals/run   — run eval suite, return report with denominators
GET  /api/evals/history — recent run rows from brain_evals (paginated)
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.memory.db import get_db
from app.deps import get_current_active_user
from app.memory.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evals", tags=["Evals"])


# ── Request schema ────────────────────────────────────────────────────────────

class RunEvalsRequest(BaseModel):
    suite: str = "all"
    model_key: Optional[str] = None


# ── POST /api/evals/run ───────────────────────────────────────────────────────

@router.post("/run")
async def run_evals_endpoint(
    body: RunEvalsRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Run the eval harness and return a report with denominators."""
    try:
        from app.services.eval_runner import run_suite
        report = await run_suite(suite=body.suite, model_key=body.model_key)
        return report
    except Exception as exc:
        logger.error("run_evals_endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/evals/history ────────────────────────────────────────────────────

@router.get("/history")
async def eval_history(
    limit: int = Query(20, ge=1, le=100),
    suite: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return recent eval rows from brain_evals, newest first."""
    try:
        params: dict = {"limit": limit}
        where_clause = "WHERE 1=1"
        if suite:
            where_clause += " AND suite = :suite"
            params["suite"] = suite

        rows = db.execute(text(f"""
            SELECT run_id, suite, eval_name, passed, score,
                   model_key, details, created_at
            FROM brain_evals
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit
        """), params).fetchall()

        return [
            {
                "run_id":    r.run_id,
                "suite":     r.suite,
                "eval_name": r.eval_name,
                "passed":    bool(r.passed),
                "score":     r.score,
                "model_key": r.model_key,
                "details": (
                    json.loads(r.details)
                    if isinstance(r.details, str)
                    else (r.details or {})
                ),
                "created_at": str(r.created_at),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.error("eval_history error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
