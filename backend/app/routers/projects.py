from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.memory.db import get_db
from app.memory.models import Project, RoleProjectLink

router = APIRouter(
    prefix="/projects",
    tags=["Projects"]
)

# ✅ Request model
class ProjectCreateRequest(BaseModel):
    name: str
    description: str
    role_id: int

# ✅ Response model
class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str

# 🔹 GET: List all projects linked to a role
@router.get("/by-role", response_model=list[ProjectResponse])
def get_projects_by_role(
    role_id: int = Query(..., description="The role_id to filter projects for"),
    db: Session = Depends(get_db)
):
    links = db.query(RoleProjectLink).filter_by(role_id=role_id).all()
    project_ids = [link.project_id for link in links]

    if not project_ids:
        return []

    projects = db.query(Project).filter(Project.id.in_(project_ids)).all()
    return [
        ProjectResponse(
            id=p.id,
            name=p.name,
            description=p.description or ""
        ) for p in projects
    ]

# 🔹 POST: Create a new project and link it to a role
@router.post("/create-and-link", response_model=ProjectResponse)
def create_and_link_project(
    request: ProjectCreateRequest,
    db: Session = Depends(get_db)
):
    # Check if project with the same name already exists
    existing_project = db.query(Project).filter_by(name=request.name).first()
    if existing_project:
        # Ensure it's linked to this role
        existing_link = db.query(RoleProjectLink).filter_by(
            role_id=request.role_id,
            project_id=existing_project.id
        ).first()

        if not existing_link:
            db.add(RoleProjectLink(role_id=request.role_id, project_id=existing_project.id))
            db.commit()

        return ProjectResponse(
            id=existing_project.id,
            name=existing_project.name,
            description=existing_project.description or ""
        )

    # Create new project
    new_project = Project(name=request.name, description=request.description)
    db.add(new_project)
    db.commit()
    db.refresh(new_project)

    # Link to role
    db.add(RoleProjectLink(role_id=request.role_id, project_id=new_project.id))
    db.commit()

    return ProjectResponse(
        id=new_project.id,
        name=new_project.name,
        description=new_project.description or ""
    )
