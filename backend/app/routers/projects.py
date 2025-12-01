"""Projects management with user ownership and assistant linking"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.memory.db import get_db
from app.memory.models import Project, Role, User
from app.deps import get_current_active_user

router = APIRouter(prefix="/projects", tags=["projects"])

# === Schemas ===

class AssistantInfo(BaseModel):
    id: int
    name: str
    description: Optional[str]

    class Config:
        from_attributes = True

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    project_structure: Optional[str] = ""
    assistant_id: Optional[int] = None  # Link to assistant/role

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_structure: Optional[str] = None
    # Note: assistant_id cannot be changed after creation (per design)

class ProjectResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    project_structure: Optional[str]
    assistant: Optional[AssistantInfo]
    
    # ✅ Git Integration fields (Phase 1)
    git_url: Optional[str] = None
    git_updated_at: Optional[datetime] = None
    git_sync_status: Optional[str] = None

    class Config:
        from_attributes = True

# === Endpoints ===

@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """List current user's projects"""
    projects = db.query(Project).filter(
        Project.user_id == current_user.id
    ).order_by(Project.id.desc()).all()

    # Manually build response to include assistant info
    result = []
    for project in projects:
        assistant_info = None
        if project.assistant_id:
            assistant = db.query(Role).filter(Role.id == project.assistant_id).first()
            if assistant:
                assistant_info = AssistantInfo.from_orm(assistant)

        result.append(ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            project_structure=project.project_structure,
            assistant=assistant_info,
            git_url=project.git_url,
            git_updated_at=project.git_updated_at,
            git_sync_status=project.git_sync_status
        ))

    return result

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get specific project (user must own it)"""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get assistant info
    assistant_info = None
    if project.assistant_id:
        assistant = db.query(Role).filter(Role.id == project.assistant_id).first()
        if assistant:
            assistant_info = AssistantInfo.from_orm(assistant)

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        project_structure=project.project_structure,
        assistant=assistant_info,
        git_url=project.git_url,
        git_updated_at=project.git_updated_at,
        git_sync_status=project.git_sync_status
    )

@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    project: ProjectCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create new project (linked to current user)"""
    # Check if project with same name exists for this user
    existing = db.query(Project).filter(
        Project.name == project.name,
        Project.user_id == current_user.id
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Project with this name already exists")

    # Verify assistant exists if provided
    if project.assistant_id:
        assistant = db.query(Role).filter(Role.id == project.assistant_id).first()
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")

    # Create project
    db_project = Project(
        name=project.name,
        description=project.description,
        project_structure=project.project_structure,
        user_id=current_user.id,
        assistant_id=project.assistant_id
    )

    db.add(db_project)
    db.commit()
    db.refresh(db_project)

    # Get assistant info for response
    assistant_info = None
    if db_project.assistant_id:
        assistant = db.query(Role).filter(Role.id == db_project.assistant_id).first()
        if assistant:
            assistant_info = AssistantInfo.from_orm(assistant)

    return ProjectResponse(
        id=db_project.id,
        name=db_project.name,
        description=db_project.description,
        project_structure=db_project.project_structure,
        assistant=assistant_info,
        git_url=db_project.git_url,
        git_updated_at=db_project.git_updated_at,
        git_sync_status=db_project.git_sync_status
    )

@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    project: ProjectUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update project (user must own it)"""
    db_project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()

    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check name conflict with other user's projects
    if project.name is not None and project.name != db_project.name:
        existing = db.query(Project).filter(
            Project.name == project.name,
            Project.user_id == current_user.id,
            Project.id != project_id
        ).first()

        if existing:
            raise HTTPException(status_code=400, detail="Project with this name already exists")

        db_project.name = project.name

    if project.description is not None:
        db_project.description = project.description

    if project.project_structure is not None:
        db_project.project_structure = project.project_structure

    # Note: assistant_id not changeable after creation (by design)

    db.commit()
    db.refresh(db_project)

    # Get assistant info
    assistant_info = None
    if db_project.assistant_id:
        assistant = db.query(Role).filter(Role.id == db_project.assistant_id).first()
        if assistant:
            assistant_info = AssistantInfo.from_orm(assistant)

    return ProjectResponse(
        id=db_project.id,
        name=db_project.name,
        description=db_project.description,
        project_structure=db_project.project_structure,
        assistant=assistant_info,
        git_url=db_project.git_url,
        git_updated_at=db_project.git_updated_at,
        git_sync_status=db_project.git_sync_status
    )

@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete project (user must own it)"""
    db_project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()

    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")

    db.delete(db_project)
    db.commit()

    return {"status": "deleted", "project_id": project_id}