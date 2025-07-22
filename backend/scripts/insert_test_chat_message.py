from sqlalchemy import create_engine, text
import os
from datetime import datetime

# Path to your SQLite database
DB_PATH = os.path.abspath("E:/projects/ai-assistant/backend/memory.db")
DB_URL = f"sqlite:///{DB_PATH}"

print(f"📂 Using database: {DB_PATH}")

if not os.path.exists(DB_PATH):
    print("❌ Database file does not exist!")
    exit()
else:
    print(f"✅ Database exists — size: {os.path.getsize(DB_PATH)} bytes")

try:
    engine = create_engine(DB_URL)
    with engine.begin() as conn:  # begin() → auto-commit at the end
        # Get all role→project links
        links_query = text("""
            SELECT r.id AS role_id,
                   r.name AS role_name,
                   p.id AS project_id,
                   p.name AS project_name
            FROM role_project_link rpl
            JOIN roles r ON rpl.role_id = r.id
            JOIN projects p ON rpl.project_id = p.id
        """)
        links = conn.execute(links_query).mappings().all()

        inserted_count = 0

        for link in links:
            # Check if this role→project already has messages
            count_query = text("""
                SELECT COUNT(*) AS cnt
                FROM chat_messages
                WHERE role_id = :role_id
                  AND project_id = :project_id
            """)
            count = conn.execute(count_query, {
                "role_id": link["role_id"],
                "project_id": link["project_id"]
            }).scalar()

            if count == 0:
                now = datetime.utcnow()
                print(f"🆕 Inserting dummy chat for Role '{link['role_name']}' → Project '{link['project_name']}'")

                # Insert user message
                conn.execute(text("""
                    INSERT INTO chat_messages (sender, text, chat_session_id, role_id, project_id, timestamp, is_summary)
                    VALUES (:sender, :text, :session_id, :role_id, :project_id, :timestamp, 0)
                """), {
                    "sender": "user",
                    "text": f"Hello from {link['role_name']} on {link['project_name']}",
                    "session_id": f"test-session-{link['role_id']}-{link['project_id']}",
                    "role_id": link["role_id"],
                    "project_id": link["project_id"],
                    "timestamp": now
                })

                # Insert assistant message
                conn.execute(text("""
                    INSERT INTO chat_messages (sender, text, chat_session_id, role_id, project_id, timestamp, is_summary)
                    VALUES (:sender, :text, :session_id, :role_id, :project_id, :timestamp, 0)
                """), {
                    "sender": "assistant",
                    "text": f"Hi! This is a dummy reply for {link['role_name']} / {link['project_name']}",
                    "session_id": f"test-session-{link['role_id']}-{link['project_id']}",
                    "role_id": link["role_id"],
                    "project_id": link["project_id"],
                    "timestamp": now
                })

                inserted_count += 1

        print(f"\n✅ Inserted dummy messages for {inserted_count} role→project pairs.")

except Exception as e:
    print(f"❌ Error accessing database: {e}")
