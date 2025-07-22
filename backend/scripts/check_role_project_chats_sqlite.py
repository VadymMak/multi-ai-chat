from sqlalchemy import create_engine, inspect, text
import os

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
    with engine.connect() as conn:
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        print("\n📋 Tables in DB:")
        for table in tables:
            print(" -", table)

        required_tables = ["roles", "projects", "role_project_link", "chat_messages", "memory_entries"]
        for tbl in required_tables:
            if tbl not in tables:
                print(f"❌ Missing required table: {tbl}")
                exit()

        # ✅ Check schema for new columns
        print("\n🔎 Checking for 'is_ai_to_ai' column:")
        for tbl in ["chat_messages", "memory_entries"]:
            columns = [col["name"] for col in inspector.get_columns(tbl)]
            if "is_ai_to_ai" in columns:
                print(f"✅ {tbl}: has 'is_ai_to_ai'")
            else:
                print(f"❌ {tbl}: missing 'is_ai_to_ai'")

        # 📊 Message count breakdown
        print("\n📊 Chat messages count per role → project:")
        query = text("""
            SELECT r.id AS role_id,
                   r.name AS role_name,
                   p.id AS project_id,
                   p.name AS project_name,
                   COUNT(cm.id) AS message_count
            FROM role_project_link rpl
            JOIN roles r ON rpl.role_id = r.id
            JOIN projects p ON rpl.project_id = p.id
            LEFT JOIN chat_messages cm
                ON cm.role_id = r.id
               AND cm.project_id = p.id
            GROUP BY r.id, p.id
            ORDER BY r.id, p.id
        """)
        results = conn.execute(query).mappings().all()

        for row in results:
            status = f"✅ {row['message_count']} messages" if row["message_count"] > 0 else "❌ No messages"
            print(f"\nRole '{row['role_name']}' → Project '{row['project_name']}': {status}")

            # Show latest 3 messages if available
            if row["message_count"] > 0:
                latest_query = text("""
                    SELECT sender, text, timestamp, is_ai_to_ai
                    FROM chat_messages
                    WHERE role_id = :role_id
                      AND project_id = :project_id
                    ORDER BY timestamp DESC
                    LIMIT 3
                """)
                latest_msgs = conn.execute(latest_query, {
                    "role_id": row["role_id"],
                    "project_id": row["project_id"]
                }).mappings().all()

                for msg in latest_msgs:
                    tag = "🤖 Boost" if msg.get("is_ai_to_ai") else "💬 Normal"
                    print(f"   {tag} | {msg['timestamp']} | {msg['sender']}: {msg['text'][:80]}")

except Exception as e:
    print(f"❌ Error accessing database: {e}")
