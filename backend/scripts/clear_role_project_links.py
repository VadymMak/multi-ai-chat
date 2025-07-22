# File: scripts/clear_role_project_links.py

import sys
import os

# Add backend path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.memory.db import SessionLocal
from app.memory.models import RoleProjectLink

def clear_links():
    db = SessionLocal()
    try:
        count = db.query(RoleProjectLink).delete()
        db.commit()
        print(f"🗑️ Deleted {count} links from role_project_link table.")
    except Exception as e:
        db.rollback()
        print(f"❌ Failed to clear links: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    clear_links()
