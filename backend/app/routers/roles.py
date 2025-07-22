# File: app/routers/roles.py  (Pydantic v2)
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator, ConfigDict
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.memory.db import get_db
from app.memory.models import Role, Project, RoleProjectLink

router = APIRouter(prefix="/roles", tags=["Roles"])


# ====== Schemas ======
class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name cannot be empty")
        if len(v) > 50:
            raise ValueError("name must be ≤ 50 characters")
        return v

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = str(v).strip()
        if not v:
            return None
        return v[:255]  # match DB column length


class RoleCreate(RoleBase):
    pass


class RoleUpdate(RoleBase):
    pass


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None


# ====== Endpoints ======
@router.get("/", response_model=List[RoleOut])
def get_roles(db: Session = Depends(get_db)):
    roles = db.query(Role).order_by(Role.id).all()
    print(f"📋 Returning {len(roles)} roles")
    return roles


@router.post("/", response_model=RoleOut, status_code=201)
def create_role(role: RoleCreate, db: Session = Depends(get_db)):
    existing = db.query(Role).filter(Role.name == role.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Role with this name already exists")

    new_role = Role(name=role.name, description=role.description)
    db.add(new_role)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Role with this name already exists")
    db.refresh(new_role)
    print(f"✅ Created role '{new_role.name}' (id={new_role.id})")
    return new_role


@router.put("/{role_id}", response_model=RoleOut)
def update_role(role_id: int, role: RoleUpdate, db: Session = Depends(get_db)):
    db_role = db.query(Role).filter(Role.id == role_id).first()
    if not db_role:
        raise HTTPException(status_code=404, detail="Role not found")

    if role.name != db_role.name:
        exists = db.query(Role).filter(Role.name == role.name).first()
        if exists and exists.id != role_id:
            raise HTTPException(status_code=409, detail="Another role already has this name")

    db_role.name = role.name
    db_role.description = role.description
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Another role already has this name")
    db.refresh(db_role)
    print(f"✏️ Updated role id={role_id} → '{role.name}'")
    return db_role


@router.delete("/{role_id}")
def delete_role(role_id: int, db: Session = Depends(get_db)):
    db_role = db.query(Role).filter(Role.id == role_id).first()
    if not db_role:
        raise HTTPException(status_code=404, detail="Role not found")
    db.delete(db_role)
    db.commit()
    print(f"🗑️ Deleted role id={role_id}")
    return {"status": "deleted", "id": role_id}


@router.get("/{role_id}/projects", response_model=List[ProjectOut])
def get_projects_for_role(role_id: int, db: Session = Depends(get_db)):
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
