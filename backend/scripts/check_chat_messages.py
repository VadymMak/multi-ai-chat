# File: backend/scripts/check_chat_messages.py

import os
import sys
from pathlib import Path
from collections import defaultdict
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ✅ Add backend root to Python path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_ROOT))

# ✅ Import models after path is adjusted
from app.memory.models import MemoryEntry, MemoryRole, Project
from app.memory.db import Base

# ✅ SQLite database location
DB_PATH = BACKEND_ROOT / "memory.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

def main():
    print(f"📂 Using database: {DB_PATH}")
    print(f"\n📋 Checking all stored chat messages...\n")

    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # ✅ Preload role names and project names (FIXED here)
        role_names = {r.id: r.name for r in session.query(MemoryRole).all()}
        project_titles = {p.id: p.name for p in session.query(Project).all()}

        # ✅ Fetch all chat messages
        entries = session.query(MemoryEntry).order_by(MemoryEntry.timestamp).all()

        if not entries:
            print("⚠️ No chat messages found.")
            return

        grouped = defaultdict(list)
        for entry in entries:
            key = (entry.role_id, entry.project_id, entry.chat_session_id)
            grouped[key].append(entry)

        for (role_id, project_id, chat_session_id), messages in grouped.items():
            role = role_names.get(role_id, f"Role {role_id}")
            project = project_titles.get(project_id, f"Project {project_id}")
            print(f"\n🔹 {role} → {project} | session={chat_session_id}")
            for msg in messages:
                sender = (msg.raw_text or "").split(":", 1)[0]
                print(f"   🗨️ [{msg.timestamp}] ({sender.strip()}) | {msg.raw_text[:100]}")

        print(f"\n✅ Done. Total groups: {len(grouped)}")

    except Exception as e:
        print(f"❌ Error while scanning messages: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    main()
