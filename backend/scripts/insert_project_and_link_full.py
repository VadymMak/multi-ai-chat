# File: backend/scripts/link_all_roles_to_all_projects.py

import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import Role, Project, RoleProjectLink

def link_all_roles_to_all_projects():
    db: Session = SessionLocal()

    roles = db.query(Role).all()
    projects = db.query(Project).all()

    if not roles:
        print("❌ No roles found in database.")
        return
    if not projects:
        print("❌ No projects found in database.")
        return

    print(f"📋 Found {len(roles)} roles and {len(projects)} projects.")
    created_links = 0

    for role in roles:
        for project in projects:
            link = db.query(RoleProjectLink).filter_by(role_id=role.id, project_id=project.id).first()
            if not link:
                new_link = RoleProjectLink(role_id=role.id, project_id=project.id)
                db.add(new_link)
                created_links += 1
                print(f"✅ Linked role '{role.name}' (id={role.id}) → project '{project.name}' (id={project.id})")
            else:
                print(f"⚠️ Link already exists for role '{role.name}' → project '{project.name}'")

    db.commit()
    db.close()

    print(f"🏁 Done. Created {created_links} new links.")

if __name__ == "__main__":
    link_all_roles_to_all_projects()
