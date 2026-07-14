#!/usr/bin/env python3
"""
Migration: Add pinned column to lessons table

Purpose: Allow users to pin/favorite lessons so they appear at the top of the list.
Date: 2026-07-14
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))


def run_migration():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    print("🔧 Starting migration: add_lesson_pinned")
    print(f"📊 Database: {database_url.split('@')[1] if '@' in database_url else 'localhost'}")

    try:
        engine = create_engine(database_url)
        with engine.connect() as conn:
            # Check if column already exists
            col_exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name   = 'lessons'
                      AND column_name  = 'pinned'
                );
            """)).scalar()

            if not col_exists:
                print("📝 Adding column 'pinned' to 'lessons'...")
                conn.execute(text("""
                    ALTER TABLE lessons
                    ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT FALSE;
                """))
                conn.commit()
                print("✅ Column 'pinned' added")

                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS ix_lessons_user_pinned_created
                    ON lessons(user_id, pinned DESC, created_at DESC);
                """))
                conn.commit()
                print("  ✅ Index 'ix_lessons_user_pinned_created' created")
            else:
                print("✅ Column 'pinned' already exists. Skipping.")

            print("\n🎉 Migration add_lesson_pinned completed successfully!")

    except ProgrammingError as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()
