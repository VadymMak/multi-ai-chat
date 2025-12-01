"""Projects management with user ownership and assistant linking"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import json
import logging

from app.memory.db import get_db
from app.memory.models import Project, Role, User
from app.deps import get_current_active_user
from app.services.git_service import (
    normalize_git_url,
    validate_repo_exists,
    read_github_structure
)

router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)

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

# === Git Integration Schemas ===

class GitLinkRequest(BaseModel):
    git_url: str

class GitLinkResponse(BaseModel):
    success: bool
    git_url: str
    normalized: bool
    message: Optional[str] = None

class GitSyncResponse(BaseModel):
    success: bool
    files_count: int
    synced_at: datetime
    files_preview: Optional[List[dict]] = None
    message: Optional[str] = None

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


# ====================================================================
# 🆕 GIT INTEGRATION ENDPOINTS (Phase 3)
# ====================================================================

@router.patch("/{project_id}/git", response_model=GitLinkResponse)
async def link_git_repository(
    project_id: int,
    request: GitLinkRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Link Git repository to project
    
    Accepts any Git URL format:
    - https://github.com/user/repo.git
    - git@github.com:user/repo.git
    - github.com/user/repo
    """
    # Get project (must be owned by user)
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        # Step 1: Normalize URL
        normalized_url = normalize_git_url(request.git_url)
        logger.info(f"Normalized Git URL: {request.git_url} → {normalized_url}")

        # Step 2: Validate repository exists
        success, error = validate_repo_exists(normalized_url)
        
        if not success:
            logger.warning(f"Repository validation failed: {error}")
            raise HTTPException(
                status_code=400,
                detail=f"Repository validation failed: {error}"
            )

        # Step 3: Save to database
        project.git_url = normalized_url
        project.git_sync_status = None  # Reset status (not synced yet)
        project.git_updated_at = None
        
        db.commit()
        db.refresh(project)

        logger.info(f"✅ Git repository linked: {normalized_url} to project {project_id}")

        return GitLinkResponse(
            success=True,
            git_url=normalized_url,
            normalized=True,
            message="Repository linked successfully"
        )

    except ValueError as e:
        # Invalid URL format
        logger.error(f"Invalid Git URL format: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error linking Git repository: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.post("/{project_id}/sync-git", response_model=GitSyncResponse)
async def sync_git_structure(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Sync project structure from Git repository
    
    Reads file tree via GitHub API and stores in project_structure
    """
    # Get project (must be owned by user)
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.git_url:
        raise HTTPException(
            status_code=400,
            detail="No Git repository linked. Please link a repository first."
        )

    try:
        # Update status to syncing
        project.git_sync_status = "syncing"
        db.commit()

        logger.info(f"🔄 Syncing Git structure for project {project_id}: {project.git_url}")

        # Read repository structure via GitHub API
        files = read_github_structure(project.git_url)

        if not files:
            # Empty repository
            logger.warning(f"⚠️ Repository is empty: {project.git_url}")
            
            project.git_sync_status = "synced"
            project.git_updated_at = datetime.utcnow()
            db.commit()

            return GitSyncResponse(
                success=True,
                files_count=0,
                synced_at=project.git_updated_at,
                message="Repository is empty. Sync again after adding files."
            )

        # Build project_structure JSON
        structure = {
            "source": "git",
            "git_url": project.git_url,
            "synced_at": datetime.utcnow().isoformat(),
            "branch": "main",
            "files_count": len(files),
            "files": files
        }

        # Save to database
        project.project_structure = json.dumps(structure)
        project.git_updated_at = datetime.utcnow()
        project.git_sync_status = "synced"
        
        db.commit()
        db.refresh(project)

        logger.info(f"✅ Successfully synced {len(files)} files from {project.git_url}")

        # Return preview of first 10 files
        files_preview = [{"path": f["path"]} for f in files[:10]]

        return GitSyncResponse(
            success=True,
            files_count=len(files),
            synced_at=project.git_updated_at,
            files_preview=files_preview,
            message=f"Successfully synced {len(files)} files"
        )

    except Exception as e:
        # Update status to error
        project.git_sync_status = "error"
        db.commit()

        logger.exception(f"❌ Error syncing Git structure: {str(e)}")
        
        # Check for specific error types
        error_message = str(e)
        if "rate limit" in error_message.lower():
            status_code = 429
            detail = "GitHub API rate limit exceeded. Please try again later."
        elif "not found" in error_message.lower():
            status_code = 404
            detail = "Repository or branch not found"
        elif "private" in error_message.lower():
            status_code = 403
            detail = "Repository is private. Public repositories only."
        else:
            status_code = 500
            detail = f"Error reading repository: {error_message}"

        raise HTTPException(status_code=status_code, detail=detail)


@router.delete("/{project_id}/git")
async def unlink_git_repository(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Unlink Git repository from project
    
    Clears git_url, git_updated_at, git_sync_status but keeps project_structure
    """
    # Get project (must be owned by user)
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.git_url:
        raise HTTPException(status_code=400, detail="No Git repository linked")

    old_url = project.git_url

    # Clear Git fields
    project.git_url = None
    project.git_updated_at = None
    project.git_sync_status = None
    # Note: We keep project_structure - it may still be useful

    db.commit()

    logger.info(f"🔗 Git repository unlinked: {old_url} from project {project_id}")

    return {
        "success": True,
        "message": "Git repository unlinked",
        "previous_url": old_url
    }