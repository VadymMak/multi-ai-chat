#!/usr/bin/env python3
"""
Migration: Add vscode_activity table

Stores the latest file the user has open in VS Code (one row per user).
Used by the Telegram bot's /now command and by build_context_for_query.

Safe to run multiple times (idempotent).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).parent.parent / ".env")
            url = os.environ.get("DATABASE_URL", "")
        except ImportError:
            pass
    if not url:
        print("❌ DATABASE_URL not found")
        sys.exit(1)
    return url.replace("postgres://", "postgresql://", 1)


def run_migration() -> bool:
    print("🚀 Starting migration: add_vscode_activity_table")
    engine = create_engine(get_database_url())

    with engine.connect() as conn:
        # ── Table ────────────────────────────────────────────────
        exists = conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'vscode_activity'
            )
        """)).scalar()

        if exists:
            print("  ℹ️ Table vscode_activity already exists — skipping CREATE")
        else:
            print("  📝 Creating vscode_activity table...")
            conn.execute(text("""
                CREATE TABLE vscode_activity (
                    id               SERIAL PRIMARY KEY,
                    user_id          INTEGER NOT NULL
                                         REFERENCES users(id) ON DELETE CASCADE,
                    project_id       INTEGER
                                         REFERENCES projects(id) ON DELETE SET NULL,
                    folder_identifier VARCHAR(64),
                    file_path        TEXT NOT NULL,
                    language         VARCHAR(50),
                    updated_at       TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
            conn.commit()
            print("  ✅ Table vscode_activity created")

        # ── Unique index on user_id (enables upsert) ─────────────
        idx_exists = conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'vscode_activity'
                  AND indexname  = 'ux_vscode_activity_user'
            )
        """)).scalar()

        if idx_exists:
            print("  ℹ️ Index ux_vscode_activity_user already exists")
        else:
            print("  📊 Creating unique index on user_id...")
            conn.execute(text("""
                CREATE UNIQUE INDEX ux_vscode_activity_user
                    ON vscode_activity(user_id)
            """))
            conn.commit()
            print("  ✅ Index created")

    print("🎉 Migration add_vscode_activity_table completed")
    return True


def verify_migration() -> bool:
    print("\n🔍 Verifying migration...")
    engine = create_engine(get_database_url())
    with engine.connect() as conn:
        ok = conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'vscode_activity'
            )
        """)).scalar()
        if ok:
            print("  ✅ Table vscode_activity exists")
        else:
            print("  ❌ Table vscode_activity missing!")
        return bool(ok)


if __name__ == "__main__":
    try:
        if run_migration():
            verify_migration()
    except Exception as exc:
        import traceback
        print(f"\n❌ Migration failed: {exc}")
        traceback.print_exc()
        sys.exit(1)
