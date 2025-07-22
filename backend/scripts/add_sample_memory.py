import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import MemoryEntry, Role

def insert_test_memory():
    db: Session = SessionLocal()

    # Create dummy role if not exists
    role = db.query(Role).filter(Role.id == 1).first()
    if not role:
        role = Role(id=1, name="Frontend Developer", description="Web UI dev")
        db.add(role)
        db.commit()
        print("✅ Inserted test role")

    # Add memory
    entry = MemoryEntry(
        role_id=1,
        project_id=1,
        summary="🧠 User refactored ChatArea.tsx and added typing animation.",
        raw_text="Added typing animation logic using streamText()."
    )
    db.add(entry)
    db.commit()
    print("✅ Inserted memory entry for project_id=1 and role_id=1")

if __name__ == "__main__":
    insert_test_memory()
