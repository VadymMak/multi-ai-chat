from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.memory.db import get_db
from app.memory.models import Project
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    project_structure: Optional[str] = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_structure: Optional[str] = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    project_structure: Optional[str]
    
    class Config:
        from_attributes = True


@router.get("/", response_model=List[ProjectResponse])
async def list_projects(db: Session = Depends(get_db)):
    """List all projects"""
    projects = db.query(Project).order_by(Project.id.desc()).all()
    return projects


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int, db: Session = Depends(get_db)):
    """Get specific project"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/", response_model=ProjectResponse)
async def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    """Create new project"""
    # Check if project with same name exists
    existing = db.query(Project).filter(Project.name == project.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Project with this name already exists")
    
    db_project = Project(
        name=project.name,
        description=project.description,
        project_structure=project.project_structure
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int, 
    project: ProjectUpdate, 
    db: Session = Depends(get_db)
):
    """Update existing project"""
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check if new name conflicts with another project
    if project.name is not None and project.name != db_project.name:
        existing = db.query(Project).filter(Project.name == project.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Project with this name already exists")
        db_project.name = project.name
    
    if project.description is not None:
        db_project.description = project.description
    if project.project_structure is not None:
        db_project.project_structure = project.project_structure
    
    db.commit()
    db.refresh(db_project)
    return db_project


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: Session = Depends(get_db)):
    """Delete project"""
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Note: Related memory entries and canon items will be handled by cascade delete
    # as defined in the models
    
    db.delete(db_project)
    db.commit()
    return {"status": "deleted", "project_id": project_id}
