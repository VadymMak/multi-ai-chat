# scripts/link_project_to_all_roles.py
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.memory.db import SessionLocal
from app.memory.models import Role, Project, RoleProjectLink

db = SessionLocal()

project_id = 2  # Or any valid project
project = db.query(Project).filter_by(id=project_id).first()
if not project:
    print("❌ Project not found")
    exit()

roles = db.query(Role).all()
for role in roles:
    existing = db.query(RoleProjectLink).filter_by(role_id=role.id, project_id=project.id).first()
    if not existing:
        link = RoleProjectLink(role_id=role.id, project_id=project.id)
        db.add(link)
        print(f"✅ Linked role_id={role.id} to project '{project.name}'")
    else:
        print(f"ℹ️ Already linked: role_id={role.id}")

db.commit()
print("🎉 Done linking!")
