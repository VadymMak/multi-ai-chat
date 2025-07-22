# File: scripts/full_clean_reset.py

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import (
    ChatMessage,
    MemoryEntry,
    PromptTemplate,
    AuditLog,
    Project,
    RoleProjectLink,
    MemoryRole
)

def full_cleanup():
    db: Session = SessionLocal()
    try:
        confirm = input("⚠️ This will DELETE ALL chat, memory, prompts, logs, and projects. Type 'YES' to continue: ")
        if confirm != "YES":
            print("❌ Cleanup cancelled.")
            return

        print("🗑 Starting full chat/memory cleanup...")

        deleted_messages = db.query(ChatMessage).delete()
        deleted_memory = db.query(MemoryEntry).delete()
        deleted_prompts = db.query(PromptTemplate).delete()
        deleted_logs = db.query(AuditLog).delete()
        deleted_links = db.query(RoleProjectLink).delete()
        deleted_projects = db.query(Project).delete()
        deleted_roles = db.query(MemoryRole).delete()

        db.commit()

        print(f"✅ Deleted:")
        print(f"   • Chat messages:     {deleted_messages}")
        print(f"   • Memory entries:    {deleted_memory}")
        print(f"   • Prompt templates:  {deleted_prompts}")
        print(f"   • Audit logs:        {deleted_logs}")
        print(f"   • Role-Project links:{deleted_links}")
        print(f"   • Projects:          {deleted_projects}")
        print(f"   • Roles:             {deleted_roles}")

    except Exception as e:
        db.rollback()
        print(f"❌ Failed to perform full cleanup: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    full_cleanup()
