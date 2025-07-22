import sys, os
from sqlalchemy import text
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.memory.db import engine

def create_roles_table():
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS roles (
                    id INTEGER PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT
                );
            """))
            print("✅ Created 'roles' table.")
        except Exception as e:
            print(f"❌ Failed to create roles table: {e}")

if __name__ == "__main__":
    create_roles_table()
