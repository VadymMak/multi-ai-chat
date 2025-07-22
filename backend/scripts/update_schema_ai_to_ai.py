# File: backend/scripts/update_schema_ai_to_ai.py

import os
import sys
from pathlib import Path
import sqlite3

# ✅ Add backend root to Python path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = BACKEND_ROOT / "memory.db"

def add_column_if_missing(cursor, table, column, column_def):
    cursor.execute(f"PRAGMA table_info({table});")
    columns = [row[1] for row in cursor.fetchall()]
    if column not in columns:
        print(f"➕ Adding column '{column}' to '{table}'...")
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def};")
    else:
        print(f"✅ Column '{column}' already exists in '{table}'.")

def main():
    print(f"📂 Using database: {DB_PATH}")

    if not DB_PATH.exists():
        print("❌ Database file not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # ✅ Update chat_messages (if used)
        add_column_if_missing(cursor, "chat_messages", "is_ai_to_ai", "BOOLEAN DEFAULT FALSE")

        # ✅ Update memory_entries
        add_column_if_missing(cursor, "memory_entries", "is_ai_to_ai", "BOOLEAN DEFAULT FALSE")
        add_column_if_missing(cursor, "memory_entries", "is_summary", "BOOLEAN DEFAULT FALSE")

        conn.commit()
        print("✅ Schema update complete.")

    except Exception as e:
        print(f"❌ Error updating schema: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
