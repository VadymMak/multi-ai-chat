from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import MemoryEntry


def delete_old_messages():
    db: Session = SessionLocal()
    try:
        # Fetch entries where project_id is stored as an int (malformed)
        entries = db.query(MemoryEntry).filter(MemoryEntry.project_id != None).all()
        deleted = 0

        for entry in entries:
            if isinstance(entry.project_id, int):
                print(f"🗑️ Deleting malformed entry → id={entry.id}, project_id={entry.project_id}")
                db.delete(entry)
                deleted += 1

        db.commit()
        print(f"✅ Deleted {deleted} old malformed messages.")
    except Exception as e:
        print(f"❌ Failed to clean up messages: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    delete_old_messages()
