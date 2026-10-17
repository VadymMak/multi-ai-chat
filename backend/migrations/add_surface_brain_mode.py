#!/usr/bin/env python3
"""
Migration: Add surface, brain_mode, session_retry_count columns.

- claude_usage_logs.surface        TEXT DEFAULT 'code'     (code|cowork|api)
- claude_usage_logs.brain_mode     TEXT DEFAULT 'enabled'  (enabled|holdout)
- claude_usage_logs.session_retry_count INTEGER DEFAULT 0

- usage_daily_stats.surface        TEXT DEFAULT 'code'

Idempotent — safe to run multiple times.
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


def _is_pg(url: str) -> bool:
    return url.startswith("postgresql")


def _col_exists(conn, table: str, col: str, is_postgres: bool) -> bool:
    if is_postgres:
        row = conn.execute(
            text("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name = :t AND column_name = :c
            """),
            {"t": table, "c": col},
        ).scalar()
        return bool(row)
    else:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(r[1] == col for r in rows)


def _add_col(conn, table: str, col: str, typedef: str, is_postgres: bool) -> None:
    if _col_exists(conn, table, col, is_postgres):
        print(f"  column {table}.{col} already exists — skip")
        return
    if is_postgres:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typedef}"))
    else:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"))
    conn.commit()
    print(f"  added {table}.{col}")


def run_migration() -> bool:
    print("Migration: add_surface_brain_mode")
    url = get_database_url()
    pg = _is_pg(url)
    engine = create_engine(url)

    with engine.connect() as conn:
        # claude_usage_logs
        _add_col(conn, "claude_usage_logs", "surface", "TEXT DEFAULT 'code'", pg)
        _add_col(conn, "claude_usage_logs", "brain_mode", "TEXT DEFAULT 'enabled'", pg)
        _add_col(conn, "claude_usage_logs", "session_retry_count", "INTEGER DEFAULT 0", pg)

        # usage_daily_stats
        _add_col(conn, "usage_daily_stats", "surface", "TEXT DEFAULT 'code'", pg)

        # indexes
        for idx, tbl_col in [
            ("idx_usage_logs_surface", "claude_usage_logs(surface)"),
            ("idx_usage_logs_brain_mode", "claude_usage_logs(brain_mode)"),
        ]:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx} ON {tbl_col}"))
                conn.commit()
            except Exception as e:
                print(f"  index {idx}: {e}")

    print("Migration add_surface_brain_mode completed.")
    return True


if __name__ == "__main__":
    try:
        run_migration()
    except Exception as e:
        print(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
