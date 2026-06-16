#!/usr/bin/env python3
"""
Migration: Add access tracking columns to canon_items and memory_entries.

Adds:
  - last_accessed_at TIMESTAMP NULL    — when the row was last returned to a user
  - access_count     INTEGER DEFAULT 0 — how many times it was retrieved

Used by the weekly archival job (scripts/archive_stale_memory.py):
  rows with access_count = 0 AND last_accessed_at IS NULL that are also old
  and idle are archived (is_active=False / deleted=True) — reversibly.

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


def _col_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name   = :table
              AND column_name  = :column
        )
    """), {"table": table, "column": column}).scalar())


def _idx_exists(conn, index: str) -> bool:
    return bool(conn.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_indexes WHERE indexname = :idx
        )
    """), {"idx": index}).scalar())


def run_migration() -> bool:
    print("🚀 Starting migration: add_memory_access_tracking")
    engine = create_engine(get_database_url())

    with engine.connect() as conn:

        # ── canon_items ────────────────────────────────────────────
        for col, ddl in [
            ("last_accessed_at", "TIMESTAMP NULL"),
            ("access_count",     "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if _col_exists(conn, "canon_items", col):
                print(f"  ℹ️  canon_items.{col} already exists")
            else:
                print(f"  📝 Adding canon_items.{col} ...")
                conn.execute(text(
                    f"ALTER TABLE canon_items ADD COLUMN {col} {ddl}"
                ))
                conn.commit()
                print(f"  ✅ canon_items.{col} added")

        # Index for archival query: (is_active, last_accessed_at)
        if _idx_exists(conn, "ix_canon_items_active_accessed"):
            print("  ℹ️  Index ix_canon_items_active_accessed already exists")
        else:
            print("  📊 Creating index ix_canon_items_active_accessed ...")
            conn.execute(text("""
                CREATE INDEX ix_canon_items_active_accessed
                    ON canon_items(is_active, last_accessed_at)
            """))
            conn.commit()
            print("  ✅ Index created")

        # ── memory_entries ─────────────────────────────────────────
        for col, ddl in [
            ("last_accessed_at", "TIMESTAMP NULL"),
            ("access_count",     "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if _col_exists(conn, "memory_entries", col):
                print(f"  ℹ️  memory_entries.{col} already exists")
            else:
                print(f"  📝 Adding memory_entries.{col} ...")
                conn.execute(text(
                    f"ALTER TABLE memory_entries ADD COLUMN {col} {ddl}"
                ))
                conn.commit()
                print(f"  ✅ memory_entries.{col} added")

        # Index for archival query: (deleted, last_accessed_at)
        if _idx_exists(conn, "ix_memory_entries_deleted_accessed"):
            print("  ℹ️  Index ix_memory_entries_deleted_accessed already exists")
        else:
            print("  📊 Creating index ix_memory_entries_deleted_accessed ...")
            conn.execute(text("""
                CREATE INDEX ix_memory_entries_deleted_accessed
                    ON memory_entries(deleted, last_accessed_at)
            """))
            conn.commit()
            print("  ✅ Index created")

    print("🎉 Migration add_memory_access_tracking completed")
    return True


def verify_migration() -> bool:
    print("\n🔍 Verifying migration...")
    engine = create_engine(get_database_url())
    ok = True
    with engine.connect() as conn:
        for table, col in [
            ("canon_items",    "last_accessed_at"),
            ("canon_items",    "access_count"),
            ("memory_entries", "last_accessed_at"),
            ("memory_entries", "access_count"),
        ]:
            exists = _col_exists(conn, table, col)
            status = "✅" if exists else "❌"
            print(f"  {status} {table}.{col}")
            if not exists:
                ok = False
    return ok


if __name__ == "__main__":
    try:
        if run_migration():
            verify_migration()
    except Exception as exc:
        import traceback
        print(f"\n❌ Migration failed: {exc}")
        traceback.print_exc()
        sys.exit(1)
