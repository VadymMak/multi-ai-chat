"""Admin/superuser endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta

from app.memory.db import get_db
from app.memory.models import User
from app.deps import get_superuser

router = APIRouter(prefix="/admin", tags=["admin"])

# === Schemas ===

class UserListResponse(BaseModel):
    id: int
    email: str
    username: str
    status: str
    is_superuser: bool
    trial_ends_at: Optional[datetime]
    subscription_ends_at: Optional[datetime]
    created_at: datetime
    last_login: Optional[datetime]
    
    class Config:
        from_attributes = True

class UpdateUserStatusRequest(BaseModel):
    status: str  # trial/active/suspended/inactive

class ExtendTrialRequest(BaseModel):
    days: int

# === Endpoints ===

@router.get("/users", response_model=List[UserListResponse])
async def list_all_users(
    skip: int = 0,
    limit: int = 100,
    superuser: User = Depends(get_superuser),
    db: Session = Depends(get_db)
):
    """List all users (superuser only)"""
    users = db.query(User).offset(skip).limit(limit).all()
    return users

@router.put("/users/{user_id}/status")
async def update_user_status(
    user_id: int,
    status_data: UpdateUserStatusRequest,
    superuser: User = Depends(get_superuser),
    db: Session = Depends(get_db)
):
    """Update user status (superuser only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if status_data.status not in ["trial", "active", "suspended", "inactive"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    user.status = status_data.status
    db.commit()
    
    return {"message": f"User status updated to {status_data.status}"}

@router.put("/users/{user_id}/extend-trial")
async def extend_trial(
    user_id: int,
    extend_data: ExtendTrialRequest,
    superuser: User = Depends(get_superuser),
    db: Session = Depends(get_db)
):
    """Extend user's trial period (superuser only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Extend from now or from current trial_ends_at
    base_date = user.trial_ends_at if user.trial_ends_at and user.trial_ends_at > datetime.utcnow() else datetime.utcnow()
    user.trial_ends_at = base_date + timedelta(days=extend_data.days)
    user.status = "trial"
    db.commit()
    
    return {
        "message": f"Trial extended by {extend_data.days} days",
        "new_trial_ends_at": user.trial_ends_at
    }

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    superuser: User = Depends(get_superuser),
    db: Session = Depends(get_db)
):
    """Delete user (superuser only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.is_superuser:
        raise HTTPException(status_code=400, detail="Cannot delete superuser")
    
    db.delete(user)
    db.commit()
    
    return {"message": "User deleted successfully"}
