from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.memory.db import get_db
from app.memory.models import Project, Role

router = APIRouter()

@router.get("/init")
async def initialize_defaults(db: Session = Depends(get_db)):
    """
    Auto-initialize database with defaults if empty.
    Creates default project and default role.
    """
    # Check if any projects exist
    projects_count = db.query(Project).count()
    
    # Check if any roles exist
    roles_count = db.query(Role).count()
    
    default_project_id = None
    default_role_id = None
    
    # Create default project if none exist
    if projects_count == 0:
        default_project = Project(
            name="My Workspace",
            description="Default workspace for AI conversations",
            project_structure=""
        )
        db.add(default_project)
        db.commit()
        db.refresh(default_project)
        default_project_id = default_project.id
    else:
        # Get first project
        default_project = db.query(Project).first()
        default_project_id = default_project.id
    
    # Create default role if none exist
    if roles_count == 0:
        default_role = Role(
            name="AI Assistant",
            description="You are a helpful AI assistant. You assist users with various tasks, answer questions, and provide information."
        )
        db.add(default_role)
        db.commit()
        db.refresh(default_role)
        default_role_id = default_role.id
    else:
        # Get first role
        default_role = db.query(Role).first()
        default_role_id = default_role.id
    
    return {
        "status": "initialized",
        "default_project_id": default_project_id,
        "default_role_id": default_role_id,
        "projects_count": db.query(Project).count(),
        "roles_count": db.query(Role).count()
    }
