# File: scripts/insert_clean_role_project_links.py

from app.memory.db import get_session
from app.memory.models import Role, Project, RoleProjectLink


# =========================
# Define intended mappings
# =========================
ROLE_PROJECT_MAP = {
    "LLM Engineer": ["Prompt Generator"],
    "Frontend Developer": ["UI Refactor"],
    "Data Scientist": ["Exploratory Analysis"],
    "Python Developer": ["FastAPI Backend"],
    # Add more specific mappings here as needed
}


def insert_clean_links():
    session = get_session()

    try:
        print("📋 Starting clean role→project link insertion...")

        for role_name, project_names in ROLE_PROJECT_MAP.items():
            # Ensure role exists
            role = session.query(Role).filter_by(name=role_name).first()
            if not role:
                print(f"⚠️ Role '{role_name}' not found in DB — skipping.")
                continue

            for project_name in project_names:
                # Ensure project exists
                project = session.query(Project).filter_by(name=project_name).first()
                if not project:
                    print(f"⚠️ Project '{project_name}' not found in DB — skipping.")
                    continue

                # Check if link exists
                link_exists = (
                    session.query(RoleProjectLink)
                    .filter_by(role_id=role.id, project_id=project.id)
                    .first()
                )
                if link_exists:
                    print(f"ℹ️ Link already exists: Role '{role_name}' → Project '{project_name}'")
                    continue

                # Create link
                link = RoleProjectLink(role_id=role.id, project_id=project.id)
                session.add(link)
                print(f"✅ Linked Role '{role_name}' (id={role.id}) → Project '{project_name}' (id={project.id})")

        session.commit()
        print("🏁 Done inserting clean role→project links.")

    except Exception as e:
        session.rollback()
        print(f"❌ Error inserting links: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    insert_clean_links()
