# File: backend/scripts/insert_project_and_link.py

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import RoleProjectLink, Project, Role

def insert_link():
    db: Session = SessionLocal()

    # Configurable IDs
    role_id = 1  # Or whatever role you're using
    project_name = "Prompt Generator"

    # Find project by name
    project = db.query(Project).filter(Project.name == project_name).first()
    if not project:
        print(f"❌ Project '{project_name}' not found. Please insert it first.")
        return

    # Check role exists
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        print(f"❌ Role ID {role_id} not found.")
        return

    # Check for existing link
    link_exists = db.query(RoleProjectLink).filter_by(role_id=role_id, project_id=project.id).first()
    if link_exists:
        print(f"⚠️ Link already exists (role_id={role_id}, project_id={project.id})")
        return

    # Insert new link
    link = RoleProjectLink(role_id=role_id, project_id=project.id)
    db.add(link)
    db.commit()
    print(f"✅ Linked project '{project_name}' (id={project.id}) to role_id={role_id}")

if __name__ == "__main__":
    insert_link()
