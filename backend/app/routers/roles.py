from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.memory.db import get_db
from app.memory.models import Role
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/roles", tags=["roles"])


class RoleCreate(BaseModel):
    name: str
    description: str


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class RoleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    
    class Config:
        from_attributes = True


@router.get("", response_model=List[RoleResponse])
async def list_roles(db: Session = Depends(get_db)):
    """List all roles/assistants"""
    roles = db.query(Role).order_by(Role.id.desc()).all()
    return roles


@router.get("/{role_id}", response_model=RoleResponse)
async def get_role(role_id: int, db: Session = Depends(get_db)):
    """Get specific role"""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


@router.post("", response_model=RoleResponse)
async def create_role(role: RoleCreate, db: Session = Depends(get_db)):
    """Create new role/assistant"""
    # Check if role with same name exists
    existing = db.query(Role).filter(Role.name == role.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Role with this name already exists")
    
    db_role = Role(
        name=role.name,
        description=role.description
    )
    db.add(db_role)
    db.commit()
    db.refresh(db_role)
    return db_role


@router.put("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: int, 
    role: RoleUpdate, 
    db: Session = Depends(get_db)
):
    """Update existing role"""
    db_role = db.query(Role).filter(Role.id == role_id).first()
    if not db_role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    # Check if new name conflicts with another role
    if role.name is not None and role.name != db_role.name:
        existing = db.query(Role).filter(Role.name == role.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Role with this name already exists")
        db_role.name = role.name
    
    if role.description is not None:
        db_role.description = role.description
    
    db.commit()
    db.refresh(db_role)
    return db_role


@router.delete("/{role_id}")
async def delete_role(role_id: int, db: Session = Depends(get_db)):
    """Delete role"""
    db_role = db.query(Role).filter(Role.id == role_id).first()
    if not db_role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    # Note: Related memory entries will have role_id set to NULL (ondelete="SET NULL")
    # RoleProjectLinks and PromptTemplates will be cascade deleted
    
    db.delete(db_role)
    db.commit()
    return {"status": "deleted", "role_id": role_id}
