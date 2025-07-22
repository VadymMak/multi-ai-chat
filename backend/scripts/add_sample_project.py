import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import Project

def insert_sample():
    db: Session = SessionLocal()
    
    # Check if already exists
    existing = db.query(Project).filter(Project.name == "Frontend UI").first()
    if existing:
        print(f"⚠️ Project already exists: ID = {existing.id}")
        return

    project = Project(
        name="Frontend UI",
        description="React + Zustand frontend structure",
        project_structure="""
📁 Project Structure
- components/
  - Header.tsx
  - ChatArea.tsx
  - InputBar.tsx
- store/
  - chatStore.ts
  - modelStore.ts
- services/
  - aiApi.ts

🧠 Description:
This project implements the chat interface, file upload, and Boost Mode logic using React + Tailwind + Zustand.
""".strip()
    )
    db.add(project)
    db.commit()
    print(f"✅ Inserted sample project: ID = {project.id}")

if __name__ == "__main__":
    insert_sample()
