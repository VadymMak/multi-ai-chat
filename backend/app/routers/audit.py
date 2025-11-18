# app/routers/audit.py
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.memory.db import get_db
from app.memory.models import AuditLog

router = APIRouter(
    prefix="/audit",
    tags=["Audit"],
)

# ✅ Response model for audit logs
class AuditLogSchema(BaseModel):
    id: int
    timestamp: datetime
    project_id: str
    role_id: int
    chat_session_id: Optional[str]
    provider: str
    action: str
    query: Optional[str] = None
    model_version: Optional[str] = None

    class Config:
        orm_mode = True


def _parse_since(since: Optional[str]) -> Optional[datetime]:
    if not since:
        return None
    try:
        # ISO 8601 or "YYYY-MM-DD" are both fine
        return datetime.fromisoformat(since)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid 'since' datetime format. Use ISO 8601 (e.g. 2025-02-01T00:00:00).")


# ✅ GET /audit/logs
@router.get("/logs", response_model=List[AuditLogSchema])
def get_audit_logs(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    role_id: Optional[int] = Query(None, description="Filter by role ID"),
    chat_session_id: Optional[str] = Query(None, description="Filter by chat session ID"),
    provider: Optional[str] = Query(None, description="Filter by provider (e.g., 'openai', 'anthropic', 'internal')"),
    action: Optional[str] = Query(None, description="Filter by action (e.g., 'ask', 'reply', 'summary')"),
    since: Optional[str] = Query(None, description="Only logs at/after this ISO timestamp"),
    limit: int = Query(50, ge=1, le=500, description="Max number of logs to return"),
    db: Session = Depends(get_db),
):
    try:
        q = db.query(AuditLog)

        if project_id:
            q = q.filter(AuditLog.project_id == str(project_id).strip())
        if role_id is not None:
            q = q.filter(AuditLog.role_id == int(role_id))
        if chat_session_id:
            q = q.filter(AuditLog.chat_session_id == chat_session_id.strip())
        if provider:
            q = q.filter(AuditLog.provider == provider.strip())
        if action:
            q = q.filter(AuditLog.action == action.strip())

        dt_since = _parse_since(since)
        if dt_since:
            q = q.filter(AuditLog.timestamp >= dt_since)

        logs = q.order_by(AuditLog.timestamp.desc()).limit(int(limit)).all()
        return logs

    except HTTPException:
        # bubble up the validation error from _parse_since
        raise
    except Exception as e:
        print(f"❌ Error fetching audit logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve audit logs")
