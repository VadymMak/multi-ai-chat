"""Idempotent migration — add category column to lessons table."""
import os
import sys

sys.path.insert(0, "/app")

from sqlalchemy import text

from app.memory.db import engine


def run() -> None:
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE lessons ADD COLUMN category VARCHAR(100)"))
            conn.commit()
            print("✅ lessons.category column added")
        except Exception as exc:
            msg = str(exc).lower()
            if "already exists" in msg or "duplicate column" in msg:
                print("✅ lessons.category column already exists")
            else:
                raise


if __name__ == "__main__":
    run()
