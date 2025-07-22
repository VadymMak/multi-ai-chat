# backend/scripts/test_project_structure.py
import os, sys, traceback
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal, ENGINE_URL  # add ENGINE_URL in db.py if missing
from app.memory.utils import get_project_structure

def test_structure(project_id: int):
    print(f"🔗 DB URL: {ENGINE_URL}")
    db: Session = SessionLocal()
    try:
        struct = get_project_structure(db, project_id)
        if struct and struct.strip():
            print("✅ Project structure loaded:\n")
            print(struct)
        else:
            print(f"⚠️ No structure found for project_id={project_id}")
    except Exception as e:
        print("❌ Exception while loading project structure:")
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    # Change to an existing project id in your DB
    test_structure(project_id=1)
