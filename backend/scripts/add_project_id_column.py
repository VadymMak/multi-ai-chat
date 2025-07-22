# backend/scripts/add_project_id_column.py

from sqlalchemy import text
from app.memory.db import engine

def add_project_id_column():
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                ALTER TABLE memory_entries
                ADD COLUMN project_id TEXT NOT NULL DEFAULT 'default';
            """))
            print("✅ project_id column added successfully.")
        except Exception as e:
            print(f"⚠️ Error adding column: {e}")

if __name__ == "__main__":
    add_project_id_column()
