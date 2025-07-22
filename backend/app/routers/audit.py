from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, List
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime

from app.memory.db import get_db
from app.memory.models import AuditLog

router = APIRouter(
    prefix="/audit",
    tags=["Audit"]
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
    query: str

    class Config:
        orm_mode = True


# ✅ GET /audit/logs
@router.get("/logs", response_model=List[AuditLogSchema])
def get_audit_logs(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    role_id: Optional[int] = Query(None, description="Filter by role ID"),
    chat_session_id: Optional[str] = Query(None, description="Filter by chat session ID"),
    limit: int = Query(50, ge=1, le=500, description="Max number of logs to return"),
    db: Session = Depends(get_db),
):
    try:
        query = db.query(AuditLog)

        if project_id:
            query = query.filter(AuditLog.project_id == project_id)
        if role_id:
            query = query.filter(AuditLog.role_id == role_id)
        if chat_session_id:
            query = query.filter(AuditLog.chat_session_id == chat_session_id)

        logs = query.order_by(AuditLog.timestamp.desc()).limit(limit).all()
        return logs

    except Exception as e:
        print(f"❌ Error fetching audit logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve audit logs")
