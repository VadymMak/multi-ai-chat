#!/usr/bin/env python3
"""
Skill distillation cron setup.

Tests pg_cron availability (expected to fail on Neon/Railway) and prints
Railway cron service instructions as fallback — same pattern as setup_archival_cron.py.

Run once:
  DATABASE_URL=<url> python backend/scripts/setup_distill_cron.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text

_CRON_JOB_NAME = "distill-brain-skills"
_CRON_SCHEDULE = "0 4 * * 1"  # Monday 04:00 UTC (after Sunday archival at 03:00)


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


def _try_pg_cron(conn) -> tuple:
    try:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_cron"))
        conn.commit()
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


def _print_railway_instructions() -> None:
    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FALLBACK: Railway cron service (pg_cron not available on Neon)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

In Railway dashboard → your project → New Service → Empty service:

  Name      : brain-distill-cron
  Schedule  : 0 4 * * 1          ← Monday 04:00 UTC (weekly)
  Command   : python backend/scripts/distill_skills.py
  Repo      : same repo, same branch (main)

Required environment variables (copy from main service):
  DATABASE_URL
  OPENAI_API_KEY

Optional:
  DISTILL_PROJECT_ID   (integer, limit to one project; omit for cross-project)
  DISTILL_SINCE_DAYS   (default 30)

Pass --dry-run in Command for a first test run:
  python backend/scripts/distill_skills.py --dry-run

Cost: Railway cron services are billed only for execution time
      (a few seconds per week) — effectively free at this scale.

Verify: check Railway logs for the cron service after Monday 04:00 UTC.
Remove a skill: DELETE FROM brain_skills WHERE name = '<name>';
List auto skills: SELECT name, description FROM brain_skills
                  WHERE description LIKE '[auto]%' ORDER BY name;
""")


def main() -> None:
    url = get_database_url()
    print(f"🔌 Connecting to: {url[:40]}...")
    engine = create_engine(url)

    with engine.connect() as conn:
        print("\n🧪 Testing pg_cron availability...")
        ok, reason = _try_pg_cron(conn)

        if ok:
            print("✅ pg_cron is available — but skill distillation needs Python (OpenAI calls).")
            print("   Use the Railway cron service instead (instructions below).")
        else:
            print(f"❌ pg_cron NOT available: {reason}")

        _print_railway_instructions()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        print(f"\n❌ Script failed: {exc}")
        traceback.print_exc()
        sys.exit(1)
