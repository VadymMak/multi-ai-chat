"""
API Endpoints for File Versions (our own Git)
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.deps import get_db, get_current_user
from app.services.version_service import VersionService
from app.memory.models import User

router = APIRouter(prefix="/versions", tags=["versions"])


# ==================== Pydantic Models ====================

class VersionResponse(BaseModel):
    id: int
    file_id: int
    version_number: int
    change_type: str
    change_source: str
    change_message: Optional[str]
    user_id: Optional[int]
    ai_model: Optional[str]
    plan_id: Optional[str]
    step_num: Optional[int]
    created_at: Optional[str]
    has_diff: bool

class VersionContentResponse(VersionResponse):
    content: str
    diff_from_previous: Optional[str]

class RollbackRequest(BaseModel):
    to_version: int

class DiffResponse(BaseModel):
    file_id: int
    from_version: int
    to_version: int
    diff: str


# ==================== Endpoints ====================

@router.get("/file/{file_id}", response_model=List[VersionResponse])
async def get_file_versions(
    file_id: int,
    limit: int = Query(default=50, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get version history for a file"""
    
    service = VersionService(db)
    versions = service.get_versions(file_id, limit=limit)
    
    return versions  # Already List[Dict]


@router.get("/file/{file_id}/version/{version_number}", response_model=VersionContentResponse)
async def get_version(
    file_id: int,
    version_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get specific version with content"""
    
    service = VersionService(db)
    version = service.get_version(file_id, version_number)
    
    if not version:
        raise HTTPException(404, f"Version {version_number} not found")
    
    return version  # Already Dict with content


@router.get("/file/{file_id}/latest", response_model=VersionContentResponse)
async def get_latest_version(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get latest version of a file"""
    
    service = VersionService(db)
    version = service.get_latest_version(file_id)
    
    if not version:
        raise HTTPException(404, "No versions found for this file")
    
    return version  # Already Dict with content


@router.post("/file/{file_id}/rollback", response_model=VersionResponse)
async def rollback_file(
    file_id: int,
    request: RollbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Rollback file to a previous version"""
    
    service = VersionService(db)
    
    try:
        version = service.rollback(
            file_id=file_id,
            to_version=request.to_version,
            user_id=current_user.id
        )
        return version  # Already Dict
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/file/{file_id}/diff", response_model=DiffResponse)
async def get_diff(
    file_id: int,
    from_version: int = Query(...),
    to_version: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get diff between two versions"""
    
    service = VersionService(db)
    
    try:
        diff = service.get_diff_between(file_id, from_version, to_version)
        return {
            "file_id": file_id,
            "from_version": from_version,
            "to_version": to_version,
            "diff": diff
        }
    except ValueError as e:
        raise HTTPException(404, str(e))