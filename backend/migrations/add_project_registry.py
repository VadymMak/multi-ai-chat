#!/usr/bin/env python3
"""
Migration: Add project_registry table.

Per-user registry of all projects with links (git, vercel, neon, railway,
demo, prod) and metadata (category, priority, status, tags, notes, vault_ref).
Includes idempotent seed from projects + claude_usage_logs.

Safe to run multiple times.
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


def _clean_name(raw: str) -> str:
    """Strip folder-identifier prefix, return bare project name."""
    if not raw:
        return raw
    marker = "-projects-"
    idx = raw.find(marker)
    if idx != -1:
        return raw[idx + len(marker):]
    return raw.rstrip("/").split("/")[-1]


def run_migration() -> None:
    print("Migration: add_project_registry")
    url = _db_url()
    pg = _is_pg(url)
    engine = create_engine(url)

    with engine.connect() as conn:
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

        # ── Seed from projects + claude_usage_logs ──────────────────────
        # Resolve primary user (first superuser, or first user)
        if pg:
            user_row = conn.execute(text(
                "SELECT id FROM users WHERE is_superuser = true ORDER BY id LIMIT 1"
            )).fetchone()
        else:
            user_row = conn.execute(text(
                "SELECT id FROM users WHERE is_superuser = 1 ORDER BY id LIMIT 1"
            )).fetchone()
        if not user_row:
            user_row = conn.execute(text("SELECT id FROM users ORDER BY id LIMIT 1")).fetchone()

        if not user_row:
            print("  no users found — skipping seed")
            conn.commit()
            return

        uid = int(user_row[0])

        # Collect candidate names from both sources
        names: set[str] = set()

        for row in conn.execute(text(
            "SELECT DISTINCT name FROM projects WHERE name IS NOT NULL AND name != ''"
        )).fetchall():
            n = _clean_name(str(row[0]).strip())
            if n:
                names.add(n)

        for row in conn.execute(text(
            "SELECT DISTINCT project_name FROM claude_usage_logs "
            "WHERE project_name IS NOT NULL AND project_name != ''"
        )).fetchall():
            n = _clean_name(str(row[0]).strip())
            if n:
                names.add(n)

        inserted = 0
        for name in sorted(names):
            if pg:
                result = conn.execute(text("""
                    INSERT INTO project_registry (user_id, name, status)
                    VALUES (:uid, :name, 'idea')
                    ON CONFLICT (user_id, name) DO NOTHING
                    RETURNING id
                """), {"uid": uid, "name": name})
                if result.fetchone():
                    inserted += 1
            else:
                existing = conn.execute(text(
                    "SELECT id FROM project_registry WHERE user_id=:uid AND name=:name"
                ), {"uid": uid, "name": name}).fetchone()
                if not existing:
                    conn.execute(text("""
                        INSERT INTO project_registry (user_id, name, status)
                        VALUES (:uid, :name, 'idea')
                    """), {"uid": uid, "name": name})
                    inserted += 1

        conn.commit()
        print(f"  seeded {inserted} new rows for user_id={uid} ({len(names)} candidates)")

    print("Migration completed.")


if __name__ == "__main__":
    try:
        run_migration()
    except Exception as e:
        print(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
