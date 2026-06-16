#!/usr/bin/env python3
"""
Weekly archival job: archive old, idle, never-accessed Brain notes.

Archives (REVERSIBLE — sets flags only, never hard-deletes):
  canon_items   → is_active = False
  memory_entries → deleted  = True

A row is archived when ALL of these are true:
  1. created_at   < NOW() - ARCHIVE_AGE_DAYS  (default 90 days)
  2. COALESCE(last_accessed_at, created_at) < NOW() - ARCHIVE_IDLE_DAYS  (default 60 days)
  3. access_count = 0  (never retrieved since the columns were added)
  4. type NOT IN PROTECTED_TYPES  (default: SESSION_SUMMARY, ADR, GLOSSARY)

Environment variables:
  DATABASE_URL         — required
  ARCHIVE_AGE_DAYS     — default 90
  ARCHIVE_IDLE_DAYS    — default 60
  PROTECTED_TYPES      — comma-separated, default "SESSION_SUMMARY,ADR,GLOSSARY"
  ARCHIVE_DRY_RUN      — set to "true" to preview without writing

Restore archived items:
  canon_items:
    UPDATE canon_items SET is_active = TRUE
    WHERE id IN (<ids>);

  memory_entries:
    UPDATE memory_entries SET deleted = FALSE
    WHERE id IN (<ids>);

Railway cron expression (weekly Sunday 03:00 UTC):
  0 3 * * 0
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


def _getenv_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _getenv_csv(name: str, default: str) -> list:
    raw = os.environ.get(name, default)
    return [t.strip() for t in raw.split(",") if t.strip()]


def run_archival() -> None:
    age_days   = _getenv_int("ARCHIVE_AGE_DAYS",  90)
    idle_days  = _getenv_int("ARCHIVE_IDLE_DAYS", 60)
    protected  = _getenv_csv("PROTECTED_TYPES",  "SESSION_SUMMARY,ADR,GLOSSARY")
    dry_run    = os.environ.get("ARCHIVE_DRY_RUN", "").lower() in {"1", "true", "yes"}

    print("=" * 60)
    print("🗂  Brain archival job")
    print(f"   age threshold  : {age_days} days")
    print(f"   idle threshold : {idle_days} days")
    print(f"   protected types: {protected}")
    print(f"   dry run        : {dry_run}")
    print("=" * 60)

    engine = create_engine(get_database_url())

    # Placeholders for protected types tuple (SQLAlchemy text binding)
    prot_params = {f"pt{i}": t for i, t in enumerate(protected)}
    prot_clause = "(" + ", ".join(f":pt{i}" for i in range(len(protected))) + ")"
    if not protected:
        prot_clause = "('')"

    with engine.connect() as conn:

        # ── Preview counts before archiving ───────────────────────
        canon_count = conn.execute(text(f"""
            SELECT COUNT(*) FROM canon_items
            WHERE is_active = TRUE
              AND created_at < NOW() - INTERVAL '{age_days} days'
              AND COALESCE(last_accessed_at, created_at) < NOW() - INTERVAL '{idle_days} days'
              AND access_count = 0
              AND type NOT IN {prot_clause}
        """), prot_params).scalar()

        mem_count = conn.execute(text(f"""
            SELECT COUNT(*) FROM memory_entries
            WHERE deleted = FALSE
              AND timestamp < NOW() - INTERVAL '{age_days} days'
              AND COALESCE(last_accessed_at, timestamp) < NOW() - INTERVAL '{idle_days} days'
              AND access_count = 0
        """)).scalar()

        print(f"\n📦 Candidates:")
        print(f"   canon_items    : {canon_count} rows")
        print(f"   memory_entries : {mem_count} rows")

        if dry_run:
            print("\n⚠️  DRY RUN — no changes written.")
            return

        # ── Archive canon_items per project ───────────────────────
        if canon_count and canon_count > 0:
            proj_rows = conn.execute(text(f"""
                SELECT project_id_int, COUNT(*) AS n
                FROM canon_items
                WHERE is_active = TRUE
                  AND created_at < NOW() - INTERVAL '{age_days} days'
                  AND COALESCE(last_accessed_at, created_at) < NOW() - INTERVAL '{idle_days} days'
                  AND access_count = 0
                  AND type NOT IN {prot_clause}
                GROUP BY project_id_int
                ORDER BY project_id_int
            """), prot_params).fetchall()

            conn.execute(text(f"""
                UPDATE canon_items
                SET is_active = FALSE
                WHERE is_active = TRUE
                  AND created_at < NOW() - INTERVAL '{age_days} days'
                  AND COALESCE(last_accessed_at, created_at) < NOW() - INTERVAL '{idle_days} days'
                  AND access_count = 0
                  AND type NOT IN {prot_clause}
            """), prot_params)
            conn.commit()

            print(f"\n✅ Archived {canon_count} canon_items:")
            for row in proj_rows:
                print(f"   project {row.project_id_int}: {row.n} items")
        else:
            print("\n✅ No canon_items to archive")

        # ── Archive memory_entries per project ────────────────────
        if mem_count and mem_count > 0:
            proj_rows = conn.execute(text(f"""
                SELECT project_id_int, COUNT(*) AS n
                FROM memory_entries
                WHERE deleted = FALSE
                  AND timestamp < NOW() - INTERVAL '{age_days} days'
                  AND COALESCE(last_accessed_at, timestamp) < NOW() - INTERVAL '{idle_days} days'
                  AND access_count = 0
                GROUP BY project_id_int
                ORDER BY project_id_int
            """)).fetchall()

            conn.execute(text(f"""
                UPDATE memory_entries
                SET deleted = TRUE
                WHERE deleted = FALSE
                  AND timestamp < NOW() - INTERVAL '{age_days} days'
                  AND COALESCE(last_accessed_at, timestamp) < NOW() - INTERVAL '{idle_days} days'
                  AND access_count = 0
            """))
            conn.commit()

            print(f"\n✅ Archived {mem_count} memory_entries:")
            for row in proj_rows:
                print(f"   project {row.project_id_int}: {row.n} entries")
        else:
            print("\n✅ No memory_entries to archive")

    print("\n🎉 Archival job completed")


if __name__ == "__main__":
    try:
        run_archival()
    except Exception as exc:
        import traceback
        print(f"\n❌ Archival job failed: {exc}")
        traceback.print_exc()
        sys.exit(1)
