#!/usr/bin/env python3
"""
Archival cron setup: tests pg_cron availability and schedules the job.

Run once against the production DATABASE_URL:
  DATABASE_URL=<url> python backend/scripts/setup_archival_cron.py

What it does:
  1. Tests whether pg_cron is available (tries CREATE EXTENSION).
  2a. If YES — creates a cron.schedule() job that runs the archival SQL weekly.
  2b. If NO  — prints exact Railway cron service instructions (fallback).

Railway / Neon note:
  Neon (serverless Postgres used by Railway) does NOT support pg_cron —
  it requires shared_preload_libraries and a persistent background worker,
  neither of which are available in Neon's architecture. Expect path 2b.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text


# ── Archival SQL (same logic as archive_stale_memory.py) ──────────
# Thresholds hard-coded here for pg_cron; env-based thresholds only
# work in the Python script because pg_cron runs pure SQL.
_ARCHIVE_SQL = """
-- Archive stale canon_items (sets is_active=FALSE, NOT deleted)
UPDATE canon_items
SET    is_active = FALSE
WHERE  is_active = TRUE
  AND  created_at < NOW() - INTERVAL '90 days'
  AND  COALESCE(last_accessed_at, created_at) < NOW() - INTERVAL '60 days'
  AND  access_count = 0
  AND  type NOT IN ('SESSION_SUMMARY', 'ADR', 'GLOSSARY');

-- Archive stale memory_entries (sets deleted=TRUE)
UPDATE memory_entries
SET    deleted = TRUE
WHERE  deleted = FALSE
  AND  timestamp < NOW() - INTERVAL '90 days'
  AND  COALESCE(last_accessed_at, timestamp) < NOW() - INTERVAL '60 days'
  AND  access_count = 0;
"""

_CRON_JOB_NAME = "archive-stale-brain"
_CRON_SCHEDULE = "0 3 * * 0"  # Sunday 03:00 UTC


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
        print("❌ DATABASE_URL not set")
        sys.exit(1)
    return url.replace("postgres://", "postgresql://", 1)


def _try_pg_cron(conn) -> tuple[bool, str]:
    """
    Attempt to enable pg_cron. Returns (success, reason).
    Rolls back on failure so subsequent queries still work.
    """
    try:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_cron"))
        conn.commit()
        # Verify the cron schema is accessible
        conn.execute(text("SELECT COUNT(*) FROM cron.job"))
        return True, "ok"
    except Exception as exc:
        err = str(exc)
        try:
            conn.rollback()
        except Exception:
            pass
        if "shared_preload_libraries" in err:
            return False, "requires shared_preload_libraries (not configurable on Neon/Railway)"
        if "permission denied" in err.lower():
            return False, "permission denied — superuser required"
        return False, err


def _setup_pg_cron(conn) -> None:
    """Register the weekly archival job via cron.schedule()."""
    # Remove stale job if it exists
    try:
        conn.execute(
            text("SELECT cron.unschedule(:name)"),
            {"name": _CRON_JOB_NAME},
        )
        conn.commit()
        print(f"  ℹ️  Removed existing job '{_CRON_JOB_NAME}'")
    except Exception:
        conn.rollback()

    conn.execute(
        text("SELECT cron.schedule(:name, :schedule, :sql)"),
        {
            "name":     _CRON_JOB_NAME,
            "schedule": _CRON_SCHEDULE,
            "sql":      _ARCHIVE_SQL,
        },
    )
    conn.commit()

    row = conn.execute(
        text("SELECT jobid, schedule, command FROM cron.job WHERE jobname = :name"),
        {"name": _CRON_JOB_NAME},
    ).fetchone()

    print(f"\n✅ pg_cron job registered:")
    print(f"   jobid    : {row.jobid}")
    print(f"   schedule : {row.schedule}  (weekly Sunday 03:00 UTC)")
    print(f"   job name : {_CRON_JOB_NAME}")
    print()
    print("Management:")
    print("  View   : SELECT * FROM cron.job;")
    print("  History: SELECT * FROM cron.job_run_details ORDER BY start_time DESC LIMIT 10;")
    print(f"  Remove : SELECT cron.unschedule('{_CRON_JOB_NAME}');")


def _print_railway_fallback() -> None:
    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FALLBACK: Railway cron service (pg_cron not available)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

In Railway dashboard → your project → New Service → Empty service:

  Name      : brain-archival-cron
  Schedule  : 0 3 * * 0          ← Sunday 03:00 UTC
  Command   : python backend/scripts/archive_stale_memory.py
  Repo      : same repo, same branch (main)

Required environment variables (copy from main service):
  DATABASE_URL
  ARCHIVE_AGE_DAYS   (optional, default 90)
  ARCHIVE_IDLE_DAYS  (optional, default 60)
  PROTECTED_TYPES    (optional, default SESSION_SUMMARY,ADR,GLOSSARY)
  ARCHIVE_DRY_RUN    (set "true" to preview without writing)

Cost: Railway cron services are billed only for execution time
      (seconds per week) — effectively free at this scale.

Verify it ran: check Railway logs for the cron service after Sunday 03:00 UTC.
Restore items: UPDATE canon_items   SET is_active = TRUE  WHERE id IN (...);
               UPDATE memory_entries SET deleted   = FALSE WHERE id IN (...);
""")


def main() -> None:
    url = get_database_url()
    print(f"🔌 Connecting to: {url[:40]}...")
    engine = create_engine(url)

    with engine.connect() as conn:

        print("\n🧪 Testing pg_cron availability...")
        ok, reason = _try_pg_cron(conn)

        if ok:
            print(f"✅ pg_cron is available → scheduling job")
            _setup_pg_cron(conn)
            print("\n✅ Done. No extra Railway service needed.")
        else:
            print(f"❌ pg_cron NOT available: {reason}")
            _print_railway_fallback()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        print(f"\n❌ Script failed: {exc}")
        traceback.print_exc()
        sys.exit(1)
