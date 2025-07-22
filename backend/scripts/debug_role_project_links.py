# File: scripts/debug_role_project_links.py
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import Role, Project, RoleProjectLink

def debug_links():
    db: Session = SessionLocal()

    print("\n🔍 Roles in DB:")
    for role in db.query(Role).all():
        print(f"  ID {role.id} - {role.name}")

    print("\n📁 Projects in DB:")
    for project in db.query(Project).all():
        print(f"  ID {project.id} - {project.name}")

    print("\n🔗 Role → Project Links:")
    links = db.query(RoleProjectLink).all()
    if not links:
        print("  ❌ No links found!")
    for link in links:
        role = db.query(Role).get(link.role_id)
        project = db.query(Project).get(link.project_id)
        print(f"  ✅ Role '{role.name}' → Project '{project.name}'")

    db.close()

if __name__ == "__main__":
    debug_links()
