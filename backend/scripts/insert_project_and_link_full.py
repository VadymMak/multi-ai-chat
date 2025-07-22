# File: backend/scripts/insert_project_and_link_full.py

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import Role, Project, RoleProjectLink

def insert_all():
    db: Session = SessionLocal()

    role_id = 1
    role_name = "LLM Engineer"
    project_name = "Prompt Generator"
    project_desc = "Test project for prompt workflows"

    # Ensure role exists
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        role = Role(id=role_id, name=role_name)
        db.add(role)
        db.commit()
        print(f"✅ Inserted role '{role_name}' with id={role_id}")
    else:
        print(f"ℹ️ Role '{role.name}' already exists with id={role.id}")

    # Ensure project exists
    project = db.query(Project).filter(Project.name == project_name).first()
    if not project:
        project = Project(name=project_name, description=project_desc)
        db.add(project)
        db.commit()
        print(f"✅ Inserted project '{project_name}' with id={project.id}")
    else:
        print(f"ℹ️ Project '{project.name}' already exists with id={project.id}")

    # Link role and project
    link = db.query(RoleProjectLink).filter_by(role_id=role.id, project_id=project.id).first()
    if not link:
        link = RoleProjectLink(role_id=role.id, project_id=project.id)
        db.add(link)
        db.commit()
        print(f"✅ Linked role_id={role.id} to project_id={project.id}")
    else:
        print(f"⚠️ Link already exists (role_id={role.id}, project_id={project.id})")

if __name__ == "__main__":
    insert_all()
