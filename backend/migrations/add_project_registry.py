#!/usr/bin/env python3
"""
Migration: Add project_registry table.

Per-user registry of all projects with links (git, vercel, neon, railway,
demo, prod) and metadata (category, priority, status, tags, notes, vault_ref).
Managed exclusively via registry_upsert — NOT auto-seeded.

Safe to run multiple times.

Fixes applied (2026-08-27):
  - priority column gets a DB-level DEFAULT 0 + backfill for any NULL rows

Fixes applied (2026-09-23):
  - created_at/updated_at get DB-level DEFAULT now() + NULL backfill
  - auto-seed removed; placeholder rows (status='idea', all links/notes null)
    are deleted on first run of this migration version
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy import create_engine, text


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
            url = os.environ.get("DATABASE_URL", "")
        except ImportError:
            pass
    if not url:
        url = f"sqlite:///{os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'memory.db'))}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def _is_pg(url: str) -> bool:
    return url.startswith("postgresql")


def _table_exists(conn, name: str, pg: bool) -> bool:
    if pg:
        r = conn.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:n)"
        ), {"n": name})
    else:
        r = conn.execute(text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:n"
        ), {"n": name})
    return bool(r.scalar())



def run_migration() -> None:
    print("Migration: add_project_registry")
    url = _db_url()
    pg = _is_pg(url)
    engine = create_engine(url)

    with engine.connect() as conn:
        # ── 1. Create table if absent ─────────────────────────────────────
        if _table_exists(conn, "project_registry", pg):
            print("  project_registry already exists — skipping CREATE")
        else:
            print("  creating project_registry")
            if pg:
                conn.execute(text("""
                    CREATE TABLE project_registry (
                        id          SERIAL PRIMARY KEY,
                        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        name        VARCHAR(200) NOT NULL,
                        category    VARCHAR(100),
                        priority    INTEGER NOT NULL DEFAULT 0,
                        status      VARCHAR(20) NOT NULL DEFAULT 'active',
                        git_url     VARCHAR(500),
                        vercel_url  VARCHAR(500),
                        neon_url    VARCHAR(500),
                        railway_url VARCHAR(500),
                        demo_url    VARCHAR(500),
                        prod_url    VARCHAR(500),
                        tags        VARCHAR(500),
                        notes       TEXT,
                        vault_ref   VARCHAR(500),
                        created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """))
                conn.execute(text(
                    "CREATE UNIQUE INDEX ix_registry_user_name "
                    "ON project_registry (user_id, name)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_registry_user_id ON project_registry (user_id)"
                ))
            else:
                conn.execute(text("""
                    CREATE TABLE project_registry (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        name        VARCHAR(200) NOT NULL,
                        category    VARCHAR(100),
                        priority    INTEGER NOT NULL DEFAULT 0,
                        status      VARCHAR(20) NOT NULL DEFAULT 'active',
                        git_url     VARCHAR(500),
                        vercel_url  VARCHAR(500),
                        neon_url    VARCHAR(500),
                        railway_url VARCHAR(500),
                        demo_url    VARCHAR(500),
                        prod_url    VARCHAR(500),
                        tags        VARCHAR(500),
                        notes       TEXT,
                        vault_ref   VARCHAR(500),
                        created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.execute(text(
                    "CREATE UNIQUE INDEX ix_registry_user_name "
                    "ON project_registry (user_id, name)"
                ))
            conn.commit()
            print("  project_registry created")

        # ── 2. Ensure DB-level DEFAULT and backfill NULL priority (idempotent) ──
        if pg:
            try:
                conn.execute(text(
                    "ALTER TABLE project_registry "
                    "ALTER COLUMN priority SET DEFAULT 0"
                ))
                conn.execute(text(
                    "UPDATE project_registry SET priority = 0 WHERE priority IS NULL"
                ))
                conn.commit()
                print("  priority column: DEFAULT 0 ensured + NULL rows backfilled")
            except Exception as e:
                conn.rollback()
                print(f"  priority ALTER skipped (non-fatal): {e}")

        # ── 2b. Ensure DB-level DEFAULT now() for created_at / updated_at ──
        #   This fixes the NotNullViolation on seed INSERTs that omit these
        #   columns.  Each ALTER is wrapped individually so a fresh DB
        #   (columns already have the default) doesn't break anything.
        if pg:
            for col in ("created_at", "updated_at"):
                try:
                    conn.execute(text(
                        f"ALTER TABLE project_registry "
                        f"ALTER COLUMN {col} SET DEFAULT now()"
                    ))
                    conn.commit()
                    print(f"  {col}: DEFAULT now() set")
                except Exception as e:
                    conn.rollback()
                    print(f"  {col} ALTER skipped (non-fatal): {e}")
            for col in ("created_at", "updated_at"):
                try:
                    conn.execute(text(
                        f"UPDATE project_registry "
                        f"SET {col} = now() WHERE {col} IS NULL"
                    ))
                    conn.commit()
                    print(f"  {col}: NULL rows backfilled")
                except Exception as e:
                    conn.rollback()
                    print(f"  {col} backfill skipped (non-fatal): {e}")

        # ── 3. Purge auto-seed placeholder rows (idempotent) ────────────
        # Deletes only status='idea' rows with all link/notes fields NULL —
        # i.e. the placeholder rows inserted by the old auto-seed logic.
        # Curated rows (status='active', with categories/links) are untouched.
        try:
            result = conn.execute(text("""
                DELETE FROM project_registry
                WHERE status = 'idea'
                  AND category IS NULL
                  AND git_url IS NULL AND vercel_url IS NULL AND neon_url IS NULL
                  AND railway_url IS NULL AND demo_url IS NULL AND prod_url IS NULL
                  AND notes IS NULL AND tags IS NULL
            """))
            conn.commit()
            deleted = result.rowcount if result.rowcount is not None else 0
            print(f"  purged {deleted} placeholder rows (status=idea, all links null)")
        except Exception as e:
            conn.rollback()
            print(f"  placeholder purge skipped (non-fatal): {e}")

    print("Migration completed.")


if __name__ == "__main__":
    try:
        run_migration()
    except Exception as e:
        print(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
