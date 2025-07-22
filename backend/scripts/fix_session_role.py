# File: scripts/fix_all_roles.py

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import ChatMessage, MemoryEntry
from sqlalchemy import text

# ✅ Our known roles from frontend
known_roles = {
    1: "LLM Engineer",
    2: "Vessel Engineer",
    3: "ML Engineer",
    4: "Data Scientist",
    5: "Frontend Developer",
    6: "Python Developer",
    7: "Esoteric Knowledge",
}

def fix_roles():
    db: Session = SessionLocal()
    try:
        # 1️⃣ Get distinct sessions from chat_messages
        rows = db.execute(text("""
            SELECT DISTINCT chat_session_id, role_id, project_id
            FROM chat_messages
            WHERE chat_session_id IS NOT NULL
            ORDER BY chat_session_id
        """)).mappings().all()

        if not rows:
            print("❌ No chat sessions found in chat_messages.")
            return

        print("\n📋 Existing chat sessions:")
        for i, row in enumerate(rows, start=1):
            role_name = known_roles.get(row["role_id"], "UNKNOWN")
            print(f"{i}. Session: {row['chat_session_id']} | role_id={row['role_id']} ({role_name}) | project_id={row['project_id']}")

        # 2️⃣ Ask which session to fix
        choice = int(input("\nEnter the number of the session to update: ").strip())
        if choice < 1 or choice > len(rows):
            print("❌ Invalid choice.")
            return

        selected = rows[choice - 1]
        print(f"🔍 Selected session: {selected['chat_session_id']} (Current role_id={selected['role_id']})")

        # 3️⃣ Show role options
        print("\nAvailable roles:")
        for rid, rname in known_roles.items():
            print(f"{rid} → {rname}")

        new_role_id = int(input("\nEnter the NEW role_id: ").strip())
        if new_role_id not in known_roles:
            print("❌ Invalid role_id.")
            return

        # 4️⃣ Confirm
        confirm = input(f"⚠️ Update session {selected['chat_session_id']} to role_id={new_role_id} ({known_roles[new_role_id]})? Type 'YES' to confirm: ")
        if confirm != "YES":
            print("❌ Update cancelled.")
            return

        # 5️⃣ Update both chat_messages & memory_entries
        updated_msgs = (
            db.query(ChatMessage)
            .filter(ChatMessage.chat_session_id == selected['chat_session_id'])
            .update({ChatMessage.role_id: new_role_id}, synchronize_session=False)
        )

        updated_mem = (
            db.query(MemoryEntry)
            .filter(MemoryEntry.chat_session_id == selected['chat_session_id'])
            .update({MemoryEntry.role_id: new_role_id}, synchronize_session=False)
        )

        db.commit()
        print(f"✅ Updated {updated_msgs} chat_messages and {updated_mem} memory_entries.")

    except Exception as e:
        db.rollback()
        print(f"❌ Failed to update: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    fix_roles()
