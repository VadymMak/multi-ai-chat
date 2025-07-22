# app/routers/projects.py
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.memory.db import get_db
from app.memory.models import Project, RoleProjectLink, Role
from app.memory.manager import MemoryManager
from app.config.settings import settings

router = APIRouter(prefix="/projects", tags=["Projects"])


# ✅ Request model
class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""
    role_id: int
    project_structure: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name must be non-empty")
        return v


# ✅ Response model
class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str
    project_structure: str | None = None


def _persist_pmd_canon(db: Session, project: Project, role_id: int) -> None:
    """Best-effort PMD canon insert on project create (behind flag)."""
    if not getattr(settings, "ENABLE_CANON", False):
        return
    try:
        mm = MemoryManager(db)
        body_lines = [f"Name: {project.name}"]
        if project.description:
            body_lines.append(f"Description: {project.description}")
        if getattr(project, "project_structure", None):
            body_lines.append("Structure:\n" + project.project_structure)
        body = "\n".join(body_lines).strip()
        if body:
            mm.store_canon_item(
                project_id=str(project.id),
                role_id=role_id,
                type="PMD",
                title="Project Metadata",
                body=body,
                tags=["project", "meta"],
                terms="project,metadata,structure",
            )
    except Exception as e:
        print(f"[PMD canon insert skipped] {e}")


# 🔹 GET: List all projects linked to a role
@router.get("/by-role", response_model=list[ProjectResponse])
def get_projects_by_role(
    role_id: int = Query(..., description="The role_id to filter projects for"),
    db: Session = Depends(get_db),
):
    # Validate role exists (clearer 404 vs empty list)
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    links = db.query(RoleProjectLink).filter_by(role_id=role_id).all()
    project_ids = [link.project_id for link in links]
    if not project_ids:
        return []

    projects = db.query(Project).filter(Project.id.in_(project_ids)).all()
    return [
        ProjectResponse(
            id=p.id,
            name=p.name,
            description=p.description or "",
            project_structure=getattr(p, "project_structure", None),
        )
        for p in projects
    ]


# 🔹 POST: Create a new project and link it to a role
@router.post("/create-and-link", response_model=ProjectResponse)
def create_and_link_project(
    request: ProjectCreateRequest,
    db: Session = Depends(get_db),
):
    # Validate role (clear feedback vs silent FK failure)
    role = db.get(Role, request.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Check if project with the same name already exists
    existing_project = db.query(Project).filter_by(name=request.name).first()
    if existing_project:
        # If caller provided structure/description and existing is missing, lightly update
        updated = False
        if request.description and not (existing_project.description or "").strip():
            existing_project.description = request.description
            updated = True
        if request.project_structure and not (existing_project.project_structure or "").strip():
            existing_project.project_structure = request.project_structure
            updated = True
        if updated:
            db.add(existing_project)
            db.commit()
            db.refresh(existing_project)

        # Ensure it's linked to this role
        try:
            link = db.query(RoleProjectLink).filter_by(
                role_id=request.role_id,
                project_id=existing_project.id,
            ).first()
            if not link:
                db.add(RoleProjectLink(role_id=request.role_id, project_id=existing_project.id))
                db.commit()
        except IntegrityError:
            db.rollback()  # link already exists under race

        return ProjectResponse(
            id=existing_project.id,
            name=existing_project.name,
            description=existing_project.description or "",
            project_structure=getattr(existing_project, "project_structure", None),
        )

    # Create new project
    new_project = Project(
        name=request.name,
        description=request.description or "",
        project_structure=request.project_structure or None,
    )
    db.add(new_project)
    db.commit()
    db.refresh(new_project)

    # Link to role (unique index protects against dupes)
    try:
        db.add(RoleProjectLink(role_id=request.role_id, project_id=new_project.id))
        db.commit()
    except IntegrityError:
        db.rollback()  # duplicate link under race

    # Best-effort PMD canon insert
    _persist_pmd_canon(db, new_project, request.role_id)

    return ProjectResponse(
        id=new_project.id,
        name=new_project.name,
        description=new_project.description or "",
        project_structure=getattr(new_project, "project_structure", None),
    )
