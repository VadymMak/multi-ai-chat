import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app.memory.db import engine

def rebuild_memory_entries():
    with engine.connect() as conn:
        try:
            conn.execute(text("DROP TABLE IF EXISTS memory_entries;"))

            conn.execute(text("""
                CREATE TABLE memory_entries (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    role_id INTEGER,
                    chat_session_id TEXT,  -- ✅ NEW: session per project
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    tokens INTEGER,
                    summary TEXT,
                    raw_text TEXT,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(role_id) REFERENCES roles(id)
                );
            """))

            print("✅ Recreated 'memory_entries' table with chat_session_id.")
        except Exception as e:
            print(f"❌ Failed to rebuild: {e}")

if __name__ == "__main__":
    rebuild_memory_entries()
