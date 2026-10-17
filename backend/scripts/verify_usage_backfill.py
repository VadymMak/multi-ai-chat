#!/usr/bin/env python3
"""
Diagnostic: verify brain_effectiveness UNIQUE constraint and retry backfill.

Prints:
  1. pg_constraint rows for brain_effectiveness (must show uq_brain_eff_usage_log, type=u)
  2. pg_indexes for brain_effectiveness
  3. session_retry_count for session 861dc7f6-98f0-41a4-ac32-60cd535c50f5 (sanity: should be 37)
  4. Top-10 sessions by session_retry_count
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


def main() -> None:
    url = get_database_url()
    is_pg = url.startswith("postgresql")
    engine = create_engine(url)

    with engine.connect() as conn:
        if is_pg:
            print("=" * 60)
            print("1. pg_constraint — brain_effectiveness")
            print("=" * 60)
            rows = conn.execute(text("""
                SELECT conname, contype, condeferrable, condeferred
                FROM pg_constraint
                WHERE conrelid = 'brain_effectiveness'::regclass
                ORDER BY conname
            """)).fetchall()
            for r in rows:
                tag = "✅ UNIQUE" if r.contype == "u" else f"type={r.contype}"
                print(f"  {r.conname}  {tag}")
            if not rows:
                print("  (no constraints found)")

            print()
            print("=" * 60)
            print("2. pg_indexes — brain_effectiveness")
            print("=" * 60)
            idx_rows = conn.execute(text("""
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'brain_effectiveness'
                ORDER BY indexname
            """)).fetchall()
            for r in idx_rows:
                print(f"  {r.indexname}")
                print(f"    {r.indexdef}")

        print()
        print("=" * 60)
        print("3. Sanity check — session 861dc7f6 retry_count (expect 37)")
        print("=" * 60)
        row = conn.execute(text("""
            SELECT session_id, MAX(session_retry_count) AS retry_count,
                   COUNT(*) AS msg_count
            FROM claude_usage_logs
            WHERE session_id = '861dc7f6-98f0-41a4-ac32-60cd535c50f5'
            GROUP BY session_id
        """)).fetchone()
        if row:
            ok = "✅" if (row.retry_count or 0) >= 37 else "❌ MISMATCH — UPSERT layer 1 not working"
            print(f"  session_retry_count = {row.retry_count}  msgs={row.msg_count}  {ok}")
        else:
            print("  ❌ session not found in claude_usage_logs")

        print()
        print("=" * 60)
        print("4. Top-10 sessions by session_retry_count")
        print("=" * 60)
        top = conn.execute(text("""
            SELECT session_id, MAX(session_retry_count) AS retries
            FROM claude_usage_logs
            GROUP BY session_id
            ORDER BY retries DESC
            LIMIT 10
        """)).fetchall()
        for r in top:
            print(f"  {r.session_id[:20]}…  retries={r.retries}")

        if is_pg:
            print()
            print("=" * 60)
            print("5. brain_effectiveness retry summary")
            print("=" * 60)
            be = conn.execute(text("""
                SELECT
                    used_brain,
                    COUNT(*) AS rows,
                    SUM(retries) AS total_retries,
                    ROUND(AVG(retries)::numeric, 4) AS avg_retries
                FROM brain_effectiveness
                GROUP BY used_brain
                ORDER BY used_brain DESC
            """)).fetchall()
            for r in be:
                brain = "with_brain" if r.used_brain else "without_brain"
                print(f"  {brain}: rows={r.rows} total_retries={r.total_retries} avg={r.avg_retries}")


if __name__ == "__main__":
    main()
