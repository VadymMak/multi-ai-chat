# backend/scripts/test_project_structure.py

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.utils import get_project_structure


def test_structure(project_id: int):
    db: Session = SessionLocal()
    structure = get_project_structure(db, project_id)
    if structure:
        print("✅ Project structure loaded:")
        print(structure)
    else:
        print("⚠️ No structure found for project_id:", project_id)


if __name__ == "__main__":
    test_structure(project_id=1)  # Change to real project ID
