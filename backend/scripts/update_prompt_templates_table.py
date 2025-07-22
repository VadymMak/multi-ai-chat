# backend/scripts/update_prompt_templates_table.py

import sys
import os
from sqlalchemy import text

# ✅ Add backend/ to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(script_dir, ".."))
sys.path.append(backend_root)

from app.memory.db import engine  # use your existing db.py connection

def update_prompt_templates_schema():
    with engine.connect() as conn:
        try:
            # 🔧 Create prompt_templates table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS prompt_templates (
                    id INTEGER PRIMARY KEY,
                    role_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    is_default BOOLEAN DEFAULT 0,
                    FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE CASCADE
                );
            """))

            print("✅ Table 'prompt_templates' created successfully.")

        except Exception as e:
            print(f"⚠️ Error creating prompt_templates table: {e}")


if __name__ == "__main__":
    update_prompt_templates_schema()
