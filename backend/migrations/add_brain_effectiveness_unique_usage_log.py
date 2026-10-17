#!/usr/bin/env python3
"""
Migration: Add full UNIQUE CONSTRAINT on brain_effectiveness.usage_log_id.

Required for ON CONFLICT (usage_log_id) DO UPDATE in backfill_from_usage_logs().
A partial index (WHERE ...) does NOT work as an ON CONFLICT arbiter without a
matching WHERE clause — use ALTER TABLE ADD CONSTRAINT for unconditional arbiter.

Idempotent. Verification is done via pg_constraint, not via INFO log.
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
            # ── Step 0: drop old partial index if it exists ──────────────
            old_idx = conn.execute(
                text("""
                    SELECT COUNT(*) FROM pg_indexes
                    WHERE tablename = 'brain_effectiveness'
                      AND indexname = 'uq_brain_eff_usage_log_id'
                """)
            ).scalar()
            if old_idx:
                conn.execute(text("DROP INDEX IF EXISTS uq_brain_eff_usage_log_id"))
                print("  dropped old partial index uq_brain_eff_usage_log_id")

            # ── Step 1: check if full constraint already exists ───────────
            exists = conn.execute(
                text("""
                    SELECT COUNT(*) FROM pg_constraint
                    WHERE conrelid = 'brain_effectiveness'::regclass
                      AND conname = 'uq_brain_eff_usage_log'
                      AND contype = 'u'
                """)
            ).scalar()

            if exists:
                print("  UNIQUE constraint uq_brain_eff_usage_log already exists — skip")
            else:
                # ── Step 2: deduplicate (keep MIN id per usage_log_id) ─────
                dupes = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM brain_effectiveness be1
                        WHERE usage_log_id IS NOT NULL
                          AND EXISTS (
                            SELECT 1 FROM brain_effectiveness be2
                            WHERE be2.usage_log_id = be1.usage_log_id
                              AND be2.id < be1.id
                          )
                    """)
                ).scalar()
                if dupes:
                    print(f"  deduplicating {dupes} duplicate usage_log_id rows...")
                    conn.execute(text("""
                        DELETE FROM brain_effectiveness
                        WHERE usage_log_id IS NOT NULL
                          AND id NOT IN (
                            SELECT MIN(id)
                            FROM brain_effectiveness
                            WHERE usage_log_id IS NOT NULL
                            GROUP BY usage_log_id
                          )
                    """))
                    print(f"  deleted {dupes} duplicates")

                # ── Step 3: add full UNIQUE constraint (no partial) ────────
                # Raises on failure — no silent swallow
                conn.execute(text("""
                    ALTER TABLE brain_effectiveness
                    ADD CONSTRAINT uq_brain_eff_usage_log UNIQUE (usage_log_id)
                """))
                print("  ALTER TABLE ADD CONSTRAINT uq_brain_eff_usage_log UNIQUE (usage_log_id) ✅")

            # ── Step 4: verify via pg_constraint ──────────────────────────
            rows = conn.execute(
                text("""
                    SELECT conname, contype
                    FROM pg_constraint
                    WHERE conrelid = 'brain_effectiveness'::regclass
                    ORDER BY conname
                """)
            ).fetchall()
            print("  pg_constraint brain_effectiveness:")
            for r in rows:
                print(f"    {r.conname}  type={r.contype}")

            idx_rows = conn.execute(
                text("""
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE tablename = 'brain_effectiveness'
                    ORDER BY indexname
                """)
            ).fetchall()
            print("  pg_indexes brain_effectiveness:")
            for r in idx_rows:
                print(f"    {r.indexname}: {r.indexdef}")

        else:
            # SQLite: CREATE UNIQUE INDEX IF NOT EXISTS (no partial)
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_brain_eff_usage_log
                ON brain_effectiveness (usage_log_id)
            """))
            print("  SQLite: unique index brain_effectiveness.usage_log_id ✅")

    print("✅ Migration: add_brain_effectiveness_unique_usage_log complete")


if __name__ == "__main__":
    run()
