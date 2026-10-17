#!/usr/bin/env python3
"""
Migration: Add UNIQUE constraint on brain_effectiveness.usage_log_id.

Required so ON CONFLICT (usage_log_id) DO UPDATE works in the
backfill_from_usage_logs() UPSERT.  Safe to run multiple times.
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


def run(url: str | None = None) -> None:
    url = url or get_database_url()
    engine = create_engine(url)
    is_postgres = _is_pg(url)

    with engine.begin() as conn:
        if is_postgres:
            # Check if unique index already exists
            exists = conn.execute(
                text("""
                    SELECT COUNT(*) FROM pg_indexes
                    WHERE tablename = 'brain_effectiveness'
                      AND indexname = 'uq_brain_eff_usage_log_id'
                """)
            ).scalar()
            if exists:
                print("  brain_effectiveness.usage_log_id unique index already exists — skip")
            else:
                try:
                    # Deduplicate first: keep lowest id per usage_log_id
                    conn.execute(text("""
                        DELETE FROM brain_effectiveness
                        WHERE id NOT IN (
                            SELECT MIN(id)
                            FROM brain_effectiveness
                            WHERE usage_log_id IS NOT NULL
                            GROUP BY usage_log_id
                        ) AND usage_log_id IS NOT NULL
                    """))
                    conn.execute(text("""
                        CREATE UNIQUE INDEX uq_brain_eff_usage_log_id
                        ON brain_effectiveness (usage_log_id)
                        WHERE usage_log_id IS NOT NULL
                    """))
                    print("  added unique index brain_effectiveness.usage_log_id ✅")
                except Exception as e:
                    print(f"  ⚠️  could not create unique index: {e}")
        else:
            # SQLite: CREATE UNIQUE INDEX IF NOT EXISTS
            try:
                conn.execute(text("""
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_brain_eff_usage_log_id
                    ON brain_effectiveness (usage_log_id)
                """))
                print("  SQLite: unique index brain_effectiveness.usage_log_id ✅")
            except Exception as e:
                print(f"  SQLite: {e}")

    print("✅ Migration: add_brain_effectiveness_unique_usage_log complete")


if __name__ == "__main__":
    run()
