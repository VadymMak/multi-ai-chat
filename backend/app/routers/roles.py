# File: app/api/roles.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List

from app.memory.db import get_db
from app.memory.models import Role, Project, RoleProjectLink

router = APIRouter(prefix="/roles", tags=["Roles"])


# ====== Schemas ======
class RoleBase(BaseModel):
    name: str


class RoleCreate(RoleBase):
    pass


class RoleUpdate(RoleBase):
    pass


class RoleOut(RoleBase):
    id: int

    class Config:
        orm_mode = True


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str | None = None

    class Config:
        orm_mode = True


# ====== Endpoints ======
@router.get("/", response_model=List[RoleOut])
def get_roles(db: Session = Depends(get_db)):
    """Return all roles sorted by ID."""
    roles = db.query(Role).order_by(Role.id).all()
    print(f"📋 Returning {len(roles)} roles")
    return roles


@router.post("/", response_model=RoleOut)
def create_role(role: RoleCreate, db: Session = Depends(get_db)):
    """Create a new role."""
    new_role = Role(name=role.name)
    db.add(new_role)
    db.commit()
    db.refresh(new_role)
    print(f"✅ Created role '{new_role.name}' (id={new_role.id})")
    return new_role


@router.put("/{role_id}", response_model=RoleOut)
def update_role(role_id: int, role: RoleUpdate, db: Session = Depends(get_db)):
    """Update an existing role."""
    db_role = db.query(Role).filter(Role.id == role_id).first()
    if not db_role:
        raise HTTPException(status_code=404, detail="Role not found")
    db_role.name = role.name
    db.commit()
    db.refresh(db_role)
    print(f"✏️ Updated role id={role_id} → '{role.name}'")
    return db_role


@router.delete("/{role_id}")
def delete_role(role_id: int, db: Session = Depends(get_db)):
    """Delete a role by ID."""
    db_role = db.query(Role).filter(Role.id == role_id).first()
    if not db_role:
        raise HTTPException(status_code=404, detail="Role not found")
    db.delete(db_role)
    db.commit()
    print(f"🗑️ Deleted role id={role_id}")
    return {"status": "deleted"}


# ====== NEW: Get projects linked to a role ======
@router.get("/{role_id}/projects", response_model=List[ProjectOut])
def get_projects_for_role(role_id: int, db: Session = Depends(get_db)):
    """
    Return only the projects linked to the given role_id
    using role_project_link table.
    """
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    projects = (
        db.query(Project)
        .join(RoleProjectLink, RoleProjectLink.project_id == Project.id)
        .filter(RoleProjectLink.role_id == role_id)
        .order_by(Project.id)
        .all()
    )

    print(f"🔗 Role '{role.name}' (id={role_id}) → {len(projects)} linked projects")
    return projects
