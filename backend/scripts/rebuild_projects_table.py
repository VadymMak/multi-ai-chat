import sys, os
from sqlalchemy import text
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.memory.db import engine

def recreate_projects_table():
    with engine.connect() as conn:
        try:
            conn.execute(text("DROP TABLE IF EXISTS projects;"))
            conn.execute(text("""
                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    project_structure TEXT
                );
            """))
            print("✅ Recreated 'projects' table successfully.")
        except Exception as e:
            print(f"❌ Failed to create 'projects' table: {e}")

if __name__ == "__main__":
    recreate_projects_table()
