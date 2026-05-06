#!/usr/bin/env python3
"""
Migration: Add Claude Code usage analytics tables.

Creates tables:
- claude_usage_logs: parsed JSONL data (model, tokens, cost, project, timestamp)
- usage_daily_stats: aggregated daily stats per project/model
- brain_effectiveness: comparison of requests with vs without Brain context

Usage:
    python backend/migrations/add_usage_analytics.py

Safe to run multiple times (idempotent). Supports both PostgreSQL and SQLite.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text


def get_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        try:
            from dotenv import load_dotenv
            env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
            load_dotenv(env_path)
            database_url = os.environ.get("DATABASE_URL")
        except ImportError:
            pass

    if not database_url:
        # Fall back to default sqlite path
        default_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "memory.db")
        )
        database_url = f"sqlite:///{default_path}"

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    return database_url


def _is_postgres(url: str) -> bool:
    return url.startswith("postgresql")


def _table_exists(conn, name: str, is_pg: bool) -> bool:
    if is_pg:
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :name
            )
        """), {"name": name})
    else:
        result = conn.execute(text("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name=:name
        """), {"name": name})
    return bool(result.scalar())


def run_migration() -> bool:
    print("Migration: add_usage_analytics")

    database_url = get_database_url()
    is_pg = _is_postgres(database_url)
    engine = create_engine(database_url)

    with engine.connect() as conn:
        # ─── claude_usage_logs ───
        if not _table_exists(conn, "claude_usage_logs", is_pg):
            print("  creating claude_usage_logs")
            if is_pg:
                conn.execute(text("""
                    CREATE TABLE claude_usage_logs (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT,
                        message_id TEXT UNIQUE,
                        request_id TEXT,
                        timestamp TIMESTAMP NOT NULL,
                        model TEXT NOT NULL,
                        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                        project_path TEXT,
                        project_name TEXT,
                        input_tokens INTEGER DEFAULT 0,
                        output_tokens INTEGER DEFAULT 0,
                        cache_creation_tokens INTEGER DEFAULT 0,
                        cache_read_tokens INTEGER DEFAULT 0,
                        total_tokens INTEGER DEFAULT 0,
                        cost_usd NUMERIC(12, 6) DEFAULT 0,
                        cost_without_cache_usd NUMERIC(12, 6) DEFAULT 0,
                        cache_savings_usd NUMERIC(12, 6) DEFAULT 0,
                        used_brain_context BOOLEAN DEFAULT FALSE,
                        brain_tools_called TEXT[],
                        had_retry BOOLEAN DEFAULT FALSE,
                        edit_successful BOOLEAN,
                        raw_jsonl_path TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE claude_usage_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT,
                        message_id TEXT UNIQUE,
                        request_id TEXT,
                        timestamp TIMESTAMP NOT NULL,
                        model TEXT NOT NULL,
                        project_id INTEGER,
                        project_path TEXT,
                        project_name TEXT,
                        input_tokens INTEGER DEFAULT 0,
                        output_tokens INTEGER DEFAULT 0,
                        cache_creation_tokens INTEGER DEFAULT 0,
                        cache_read_tokens INTEGER DEFAULT 0,
                        total_tokens INTEGER DEFAULT 0,
                        cost_usd REAL DEFAULT 0,
                        cost_without_cache_usd REAL DEFAULT 0,
                        cache_savings_usd REAL DEFAULT 0,
                        used_brain_context INTEGER DEFAULT 0,
                        brain_tools_called TEXT,
                        had_retry INTEGER DEFAULT 0,
                        edit_successful INTEGER,
                        raw_jsonl_path TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            conn.commit()
        else:
            print("  claude_usage_logs already exists")

        # ─── usage_daily_stats ───
        if not _table_exists(conn, "usage_daily_stats", is_pg):
            print("  creating usage_daily_stats")
            if is_pg:
                conn.execute(text("""
                    CREATE TABLE usage_daily_stats (
                        id SERIAL PRIMARY KEY,
                        date DATE NOT NULL,
                        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                        project_name TEXT,
                        model TEXT NOT NULL,
                        request_count INTEGER DEFAULT 0,
                        input_tokens BIGINT DEFAULT 0,
                        output_tokens BIGINT DEFAULT 0,
                        cache_creation_tokens BIGINT DEFAULT 0,
                        cache_read_tokens BIGINT DEFAULT 0,
                        total_tokens BIGINT DEFAULT 0,
                        cost_usd NUMERIC(12, 6) DEFAULT 0,
                        cache_savings_usd NUMERIC(12, 6) DEFAULT 0,
                        brain_assisted_count INTEGER DEFAULT 0,
                        retry_count INTEGER DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE (date, project_id, model)
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE usage_daily_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL,
                        project_id INTEGER,
                        project_name TEXT,
                        model TEXT NOT NULL,
                        request_count INTEGER DEFAULT 0,
                        input_tokens INTEGER DEFAULT 0,
                        output_tokens INTEGER DEFAULT 0,
                        cache_creation_tokens INTEGER DEFAULT 0,
                        cache_read_tokens INTEGER DEFAULT 0,
                        total_tokens INTEGER DEFAULT 0,
                        cost_usd REAL DEFAULT 0,
                        cache_savings_usd REAL DEFAULT 0,
                        brain_assisted_count INTEGER DEFAULT 0,
                        retry_count INTEGER DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (date, project_id, model)
                    )
                """))
            conn.commit()
        else:
            print("  usage_daily_stats already exists")

        # ─── brain_effectiveness ───
        if not _table_exists(conn, "brain_effectiveness", is_pg):
            print("  creating brain_effectiveness")
            if is_pg:
                conn.execute(text("""
                    CREATE TABLE brain_effectiveness (
                        id SERIAL PRIMARY KEY,
                        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                        usage_log_id INTEGER REFERENCES claude_usage_logs(id) ON DELETE CASCADE,
                        used_brain BOOLEAN NOT NULL,
                        request_kind TEXT,
                        tokens_used INTEGER DEFAULT 0,
                        cost_usd NUMERIC(12, 6) DEFAULT 0,
                        retries INTEGER DEFAULT 0,
                        edit_successful BOOLEAN,
                        time_to_complete_ms INTEGER,
                        brain_tokens_added INTEGER DEFAULT 0,
                        brain_tools_called TEXT[],
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE brain_effectiveness (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_id INTEGER,
                        usage_log_id INTEGER,
                        used_brain INTEGER NOT NULL,
                        request_kind TEXT,
                        tokens_used INTEGER DEFAULT 0,
                        cost_usd REAL DEFAULT 0,
                        retries INTEGER DEFAULT 0,
                        edit_successful INTEGER,
                        time_to_complete_ms INTEGER,
                        brain_tokens_added INTEGER DEFAULT 0,
                        brain_tools_called TEXT,
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            conn.commit()
        else:
            print("  brain_effectiveness already exists")

        # ─── indexes ───
        indexes = [
            ("idx_usage_logs_timestamp", "claude_usage_logs(timestamp DESC)"),
            ("idx_usage_logs_project", "claude_usage_logs(project_id)"),
            ("idx_usage_logs_model", "claude_usage_logs(model)"),
            ("idx_usage_logs_session", "claude_usage_logs(session_id)"),
            ("idx_daily_stats_date", "usage_daily_stats(date DESC)"),
            ("idx_daily_stats_project", "usage_daily_stats(project_id)"),
            ("idx_brain_eff_project", "brain_effectiveness(project_id)"),
            ("idx_brain_eff_used", "brain_effectiveness(used_brain)"),
        ]
        for idx_name, idx_def in indexes:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}"))
                conn.commit()
            except Exception as e:
                print(f"  index {idx_name}: {e}")

        print("Migration completed.")
        return True


def verify_migration() -> bool:
    database_url = get_database_url()
    is_pg = _is_postgres(database_url)
    engine = create_engine(database_url)
    with engine.connect() as conn:
        for table in ("claude_usage_logs", "usage_daily_stats", "brain_effectiveness"):
            if not _table_exists(conn, table, is_pg):
                print(f"  MISSING: {table}")
                return False
            print(f"  ok: {table}")
    return True


if __name__ == "__main__":
    try:
        if run_migration():
            verify_migration()
    except Exception as e:
        print(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
