# backend/scripts/update_project_tables.py

import sys
import os
from sqlalchemy import text

# ✅ Add backend/ to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(script_dir, ".."))
sys.path.append(backend_root)

from app.memory.db import engine  # now works regardless of run location

def update_project_schema():
    with engine.connect() as conn:
        try:
            # 1. Create `projects` table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    project_structure TEXT
                );
            """))

            # 2. Create `role_project_link` table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS role_project_link (
                    id INTEGER PRIMARY KEY,
                    role_id INTEGER NOT NULL,
                    project_id INTEGER NOT NULL,
                    FOREIGN KEY(role_id) REFERENCES roles(id),
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );
            """))

            print("✅ Tables 'projects' and 'role_project_link' created successfully.")

        except Exception as e:
            print(f"⚠️ Error updating schema: {e}")


if __name__ == "__main__":
    update_project_schema()
