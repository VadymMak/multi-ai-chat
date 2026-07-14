#!/usr/bin/env python3
"""
Migration: Add lessons table

Purpose: Store AI answers saved by users from the mobile app.
         Each lesson is private per user (user_id FK, scoped queries).
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

    print("🔧 Starting migration: add_lessons_table")
    print(f"📊 Database: {database_url.split('@')[1] if '@' in database_url else 'localhost'}")

    try:
        engine = create_engine(database_url)
        with engine.connect() as conn:
            check_table = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'lessons'
                );
            """)
            table_exists = conn.execute(check_table).scalar()

            if not table_exists:
                print("📝 Creating table 'lessons'...")
                conn.execute(text("""
                    CREATE TABLE lessons (
                        id          SERIAL PRIMARY KEY,
                        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        title       VARCHAR(255) NOT NULL,
                        content     TEXT NOT NULL,
                        tags        VARCHAR(500),
                        source      VARCHAR(100),
                        created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
                    );
                """))
                conn.commit()
                print("✅ Table 'lessons' created")

                for index_name, definition in [
                    ("ix_lessons_user_id",      "lessons(user_id)"),
                    ("ix_lessons_user_created", "lessons(user_id, created_at DESC)"),
                ]:
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} ON {definition};"
                    ))
                    print(f"  ✅ Index '{index_name}' created")
                conn.commit()

                conn.execute(text(
                    "COMMENT ON TABLE lessons IS "
                    "'AI answers saved as lessons by users via mobile app — private per user'"
                ))
                conn.commit()
            else:
                print("✅ Table 'lessons' already exists. Skipping create.")

            # Verify table columns
            cols = conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'lessons'
                ORDER BY ordinal_position;
            """)).fetchall()
            col_names = [r[0] for r in cols]
            print(f"✅ Verified columns: {col_names}")

            print("\n🎉 Migration add_lessons_table completed successfully!")

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
