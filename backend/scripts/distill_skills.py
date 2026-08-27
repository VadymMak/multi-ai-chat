#!/usr/bin/env python3
"""
Distill brain_skills from resolved errors and session summaries.

Run weekly (or on demand):
  DATABASE_URL=<url> OPENAI_API_KEY=<key> python backend/scripts/distill_skills.py
  DATABASE_URL=<url> OPENAI_API_KEY=<key> python backend/scripts/distill_skills.py --dry-run
  DATABASE_URL=<url> OPENAI_API_KEY=<key> python backend/scripts/distill_skills.py --project-id 20
  DATABASE_URL=<url> OPENAI_API_KEY=<key> python backend/scripts/distill_skills.py --since-days 60
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

database_url = os.environ.get("DATABASE_URL", "")
if database_url.startswith("postgres://"):
    os.environ["DATABASE_URL"] = database_url.replace("postgres://", "postgresql://", 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Distill brain_skills from resolved errors + session summaries"
    )
    parser.add_argument(
        "--project-id", type=int, default=None,
        help="Limit to one project (default: cross-project)",
    )
    parser.add_argument(
        "--since-days", type=int, default=30,
        help="Days to look back (default: 30)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview proposed skills without saving",
    )
    args = parser.parse_args()

    from app.services.skill_distiller import distill

    print(
        f"🧠 Distilling skills "
        f"(project={args.project_id}, since_days={args.since_days}, dry_run={args.dry_run})"
    )
    result = distill(
        project_id=args.project_id,
        since_days=args.since_days,
        dry_run=args.dry_run,
    )

    proposed = result["proposed"]
    saved = result["saved"]
    skipped = result["skipped"]

    if not proposed:
        print("\n📭 No skills proposed — not enough resolved errors or session summaries yet.")
        return

    print(f"\n📋 Proposed ({len(proposed)}):")
    for s in proposed:
        tag = "[update]" if s["action"] == "update" else "[new]"
        print(f"  {tag} {s['name']} ({s['category']})")
        print(f"       {s['description']}")

    if skipped:
        print(f"\n⏭️  Skipped ({len(skipped)}):")
        for s in skipped:
            print(f"  {s['name']}: {s['reason']}")

    if args.dry_run:
        print("\n🔍 Dry run — nothing saved. Re-run without --dry-run to persist.")
    else:
        print(f"\n✅ Saved: {len(saved)} skill(s)")
        for s in saved:
            print(f"  [{s['action']}] {s['name']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        print(f"\n❌ Script failed: {exc}")
        traceback.print_exc()
        sys.exit(1)
