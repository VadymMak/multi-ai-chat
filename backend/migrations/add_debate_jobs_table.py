#!/usr/bin/env python3
"""
Migration: Add debate_jobs table for async debate start/poll pattern.

debate_jobs stores one row per background debate job:
  debate_id (uuid), status (running|done|error|timeout), params (jsonb),
  result (jsonb, null until done), error, created_at, updated_at.

Crash-proof and idempotent: safe to run on every boot. Always exits 0.
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


def _index_exists(conn, name: str, pg: bool) -> bool:
    if pg:
        r = conn.execute(text(
            "SELECT EXISTS (SELECT FROM pg_indexes WHERE indexname=:n)"
        ), {"n": name})
    else:
        r = conn.execute(text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=:n"
        ), {"n": name})
    return bool(r.scalar())


def run_migration() -> None:
    print("Migration: add_debate_jobs_table")
    url = _db_url()
    pg = _is_pg(url)
    engine = create_engine(url)

    with engine.connect() as conn:
        if _table_exists(conn, "debate_jobs", pg):
            print("  debate_jobs already exists — skipping CREATE")
        else:
            print("  creating debate_jobs")
            if pg:
                conn.execute(text("""
                    CREATE TABLE debate_jobs (
                        id          SERIAL PRIMARY KEY,
                        debate_id   TEXT NOT NULL,
                        status      TEXT NOT NULL DEFAULT 'running',
                        params      JSONB,
                        result      JSONB,
                        error       TEXT,
                        created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE debate_jobs (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        debate_id   TEXT NOT NULL,
                        status      TEXT NOT NULL DEFAULT 'running',
                        params      TEXT,
                        result      TEXT,
                        error       TEXT,
                        created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            conn.commit()
            print("  debate_jobs created")

        indexes = [
            ("ix_debate_jobs_debate_id",  "debate_jobs(debate_id)", True),
            ("ix_debate_jobs_status",     "debate_jobs(status)", False),
            ("ix_debate_jobs_created_at", "debate_jobs(created_at)", False),
        ]
        for idx_name, idx_expr, unique in indexes:
            if not _index_exists(conn, idx_name, pg):
                try:
                    uniq = "UNIQUE " if unique else ""
                    conn.execute(text(f"CREATE {uniq}INDEX {idx_name} ON {idx_expr}"))
                    conn.commit()
                    print(f"  index {idx_name} created")
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    print(f"  index {idx_name} skipped: {e}")
            else:
                print(f"  index {idx_name} already exists")

    print("Migration add_debate_jobs_table: done")


if __name__ == "__main__":
    try:
        run_migration()
    except Exception as e:
        print(f"Migration add_debate_jobs_table failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()
    sys.exit(0)
