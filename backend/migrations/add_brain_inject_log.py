#!/usr/bin/env python3
"""
Migration: Create brain_inject_log table.

Logs every call to GET /api/brain/inject so false-positive injections
are visible and the score threshold can be tuned.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
            url = os.environ.get("DATABASE_URL")
        except ImportError:
            pass
    if not url:
        default = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "memory.db"))
        url = f"sqlite:///{default}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def run(url: str | None = None) -> None:
    url = url or get_database_url()
    engine = create_engine(url)
    is_pg = url.startswith("postgresql")

    with engine.begin() as conn:
        if is_pg:
            exists = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = 'brain_inject_log'
            """)).scalar()
            if exists:
                print("  brain_inject_log already exists — skip")
                return

            conn.execute(text("""
                CREATE TABLE brain_inject_log (
                    id             SERIAL PRIMARY KEY,
                    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    query          TEXT,
                    project_folder VARCHAR(255),
                    source         VARCHAR(50)  NOT NULL DEFAULT 'empty',
                    score          FLOAT        NOT NULL DEFAULT 0,
                    injection_text TEXT,
                    error_id       INTEGER REFERENCES learned_errors(id) ON DELETE SET NULL,
                    skill_id       INTEGER REFERENCES brain_skills(id)   ON DELETE SET NULL
                )
            """))
            conn.execute(text(
                "CREATE INDEX idx_brain_inject_log_created ON brain_inject_log (created_at DESC)"
            ))
            conn.execute(text(
                "CREATE INDEX idx_brain_inject_log_source  ON brain_inject_log (source)"
            ))
            print("  ✅ brain_inject_log created")
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS brain_inject_log (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    query          TEXT,
                    project_folder VARCHAR(255),
                    source         VARCHAR(50) NOT NULL DEFAULT 'empty',
                    score          REAL NOT NULL DEFAULT 0,
                    injection_text TEXT,
                    error_id       INTEGER,
                    skill_id       INTEGER
                )
            """))
            print("  ✅ brain_inject_log created (SQLite)")

    print("✅ Migration: add_brain_inject_log complete")


if __name__ == "__main__":
    run()
