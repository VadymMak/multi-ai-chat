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

        # Check required tables exist
        required_tables = ["roles", "projects", "role_project_link", "chat_sessions", "chat_messages"]
        for tbl in required_tables:
            if tbl not in tables:
                print(f"❌ Missing required table: {tbl}")
                exit()

        # Query all role→project links
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
            LEFT JOIN chat_sessions cs
                ON cs.role_id = r.id AND cs.project_id = p.id
            LEFT JOIN chat_messages cm
                ON cm.session_id = cs.id
            GROUP BY r.id, p.id
            ORDER BY r.id, p.id
        """)

        results = conn.execute(query).mappings().all()
        for row in results:
            status = f"✅ {row['message_count']} messages" if row["message_count"] > 0 else "❌ No messages"
            print(f"Role '{row['role_name']}' → Project '{row['project_name']}': {status}")

except Exception as e:
    print(f"❌ Error accessing database: {e}")
