"""
One-time migration: backfill project_id in claude_usage_logs where it is NULL.

Usage:
    DATABASE_URL=postgresql://... python fix_project_id_lookup.py
"""

from __future__ import annotations

import os
import sys

import psycopg2


def _extract_project_slug(raw: str | None) -> str | None:
    """Same logic as usage_analytics._extract_project_slug."""
    if not raw:
        return None
    marker = "-projects-"
    idx = raw.find(marker)
    if idx != -1:
        return raw[idx + len(marker):]
    return raw.rstrip("/").split("/")[-1]


def main() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)
    if db_url.startswith("postgresql+"):
        db_url = "postgresql://" + db_url.split("://", 1)[1]

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM claude_usage_logs WHERE project_id IS NULL")
    total = cur.fetchone()[0]
    print(f"Records with project_id IS NULL: {total}")

    BATCH = 100
    fixed = 0
    still_null = 0
    processed = 0

    while True:
        cur.execute(
            """
            SELECT id, project_name FROM claude_usage_logs
            WHERE project_id IS NULL
            LIMIT %s
            """,
            (BATCH,),
        )
        rows = cur.fetchall()
        if not rows:
            break

        batch_fixed = 0
        batch_null = 0
        for record_id, project_name in rows:
            slug = _extract_project_slug(project_name)
            if not slug:
                batch_null += 1
                continue

            cur.execute(
                "SELECT id FROM projects WHERE name = %s OR folder_identifier = %s LIMIT 1",
                (slug, slug),
            )
            found = cur.fetchone()
            if not found:
                # mark as unfixable so next batch doesn't re-fetch the same row
                cur.execute(
                    "UPDATE claude_usage_logs SET project_id = -1 WHERE id = %s",
                    (record_id,),
                )
                batch_null += 1
                continue

            cur.execute(
                "UPDATE claude_usage_logs SET project_id = %s WHERE id = %s",
                (found[0], record_id),
            )
            batch_fixed += 1

        conn.commit()
        fixed += batch_fixed
        still_null += batch_null
        processed += len(rows)
        print(f"  batch done — processed {processed}, fixed so far: {fixed}, still null: {still_null}")

    # reset sentinel values back to NULL
    cur.execute("UPDATE claude_usage_logs SET project_id = NULL WHERE project_id = -1")
    conn.commit()

    cur.close()
    conn.close()

    print(f"\nFixed:      {fixed} / {total}")
    print(f"Still NULL: {still_null} / {total}")


if __name__ == "__main__":
    main()
