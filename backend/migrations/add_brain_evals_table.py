#!/usr/bin/env python3
"""
Migration: add brain_evals table.
Stores per-case results of eval harness runs for regression tracking.
Safe to re-run (idempotent). Always exits 0 — never breaks boot.
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
    print("Migration: add_brain_evals_table")
    url = _db_url()
    pg = _is_pg(url)
    engine = create_engine(url)

    with engine.connect() as conn:
        if _table_exists(conn, "brain_evals", pg):
            print("  brain_evals already exists — skipping CREATE")
        else:
            print("  creating brain_evals")
            if pg:
                conn.execute(text("""
                    CREATE TABLE brain_evals (
                        id         SERIAL PRIMARY KEY,
                        run_id     TEXT NOT NULL,
                        suite      TEXT NOT NULL,
                        eval_name  TEXT NOT NULL,
                        passed     BOOLEAN NOT NULL DEFAULT FALSE,
                        score      FLOAT,
                        model_key  TEXT,
                        details    JSONB,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_brain_evals_run_id ON brain_evals (run_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_brain_evals_suite ON brain_evals (suite)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_brain_evals_created_at ON brain_evals (created_at)"
                ))
            else:
                conn.execute(text("""
                    CREATE TABLE brain_evals (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id     TEXT NOT NULL,
                        suite      TEXT NOT NULL,
                        eval_name  TEXT NOT NULL,
                        passed     INTEGER NOT NULL DEFAULT 0,
                        score      REAL,
                        model_key  TEXT,
                        details    TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_brain_evals_run_id ON brain_evals (run_id)"
                ))
            conn.commit()
            print("  brain_evals created")

    print("Migration completed.")


if __name__ == "__main__":
    try:
        run_migration()
    except Exception as e:
        print(f"Migration failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()
    sys.exit(0)
