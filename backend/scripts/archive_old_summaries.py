#!/usr/bin/env python3
"""
Soft retention for SESSION_SUMMARY canon_items.

For each project: keep the newest KEEP_ACTIVE (default 30) SESSION_SUMMARY rows
active; mark all older ones is_active=FALSE (never deleted — fully recoverable).

This runs AFTER skill_distiller in the weekly brain-distill-cron Railway service.

Flags:
  --dry-run          Print per-project counts, write nothing.
  --keep N           Override KEEP_ACTIVE (default 30).
  --project-id ID    Limit to a single project.

Safe to run multiple times (idempotent once settled).
Only touches type='SESSION_SUMMARY' — LESSON, ADR, GLOSSARY etc. are untouched.

Restore archived rows:
  UPDATE canon_items SET is_active = TRUE WHERE id IN (<ids>);
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text

DEFAULT_KEEP_ACTIVE = 30

# Trace retention — prune brain_traces (+ cascade spans) older than N days
# OR beyond the last M rows, whichever is tighter.
TRACE_RETENTION_DAYS = int(os.environ.get("TRACE_RETENTION_DAYS", "14"))
TRACE_RETENTION_MAX  = int(os.environ.get("TRACE_RETENTION_MAX", "5000"))


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


def _run_project(conn, project_id: int, keep: int, dry_run: bool) -> dict:
    """
    Returns {total, active_before, to_archive, archived}.
    """
    total = conn.execute(
        text("""
            SELECT COUNT(*) FROM canon_items
            WHERE type = 'SESSION_SUMMARY'
              AND project_id_int = :pid
        """),
        {"pid": project_id},
    ).scalar() or 0

    active_before = conn.execute(
        text("""
            SELECT COUNT(*) FROM canon_items
            WHERE type = 'SESSION_SUMMARY'
              AND project_id_int = :pid
              AND is_active = TRUE
        """),
        {"pid": project_id},
    ).scalar() or 0

    # How many rows will be archived: active rows beyond rank `keep`
    to_archive = conn.execute(
        text("""
            SELECT COUNT(*) FROM (
                SELECT id, ROW_NUMBER() OVER (ORDER BY created_at DESC) AS rn
                FROM canon_items
                WHERE type = 'SESSION_SUMMARY'
                  AND project_id_int = :pid
                  AND is_active = TRUE
            ) ranked
            WHERE rn > :keep
        """),
        {"pid": project_id, "keep": keep},
    ).scalar() or 0

    archived = 0
    if not dry_run and to_archive > 0:
        result = conn.execute(
            text("""
                UPDATE canon_items
                SET is_active = FALSE
                FROM (
                    SELECT id, ROW_NUMBER() OVER (ORDER BY created_at DESC) AS rn
                    FROM canon_items
                    WHERE type = 'SESSION_SUMMARY'
                      AND project_id_int = :pid
                      AND is_active = TRUE
                ) ranked
                WHERE canon_items.id = ranked.id
                  AND ranked.rn > :keep
            """),
            {"pid": project_id, "keep": keep},
        )
        conn.commit()
        archived = result.rowcount

    return {
        "total": total,
        "active_before": active_before,
        "to_archive": to_archive,
        "archived": archived,
    }


def _prune_traces(conn, dry_run: bool) -> dict:
    """
    Delete brain_traces (and their spans via trace_id match) that are either:
      - older than TRACE_RETENTION_DAYS days, OR
      - beyond the most recent TRACE_RETENTION_MAX rows
    whichever is tighter. Idempotent. Best-effort — errors are surfaced, not raised.
    """
    # Check table exists before touching it
    tbl_exists = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='brain_traces'"
    )).scalar() or 0
    if not tbl_exists:
        return {"skipped": True, "reason": "brain_traces table does not exist yet"}

    deleted_by_age = 0
    deleted_by_cap = 0

    # ── 1. Delete by age ───────────────────────────────────────────────────
    age_ids = conn.execute(text("""
        SELECT trace_id FROM brain_traces
        WHERE created_at < NOW() - INTERVAL ':days days'
    """.replace(":days days", f"{TRACE_RETENTION_DAYS} days"))).fetchall()
    age_trace_ids = [r.trace_id for r in age_ids]

    if age_trace_ids and not dry_run:
        conn.execute(text(
            "DELETE FROM brain_trace_spans WHERE trace_id = ANY(:ids)"
        ), {"ids": age_trace_ids})
        r = conn.execute(text(
            "DELETE FROM brain_traces WHERE trace_id = ANY(:ids)"
        ), {"ids": age_trace_ids})
        conn.commit()
        deleted_by_age = r.rowcount or 0
    else:
        deleted_by_age = len(age_trace_ids)

    # ── 2. Delete by row cap (keep only newest TRACE_RETENTION_MAX) ────────
    total_remaining = conn.execute(text("SELECT COUNT(*) FROM brain_traces")).scalar() or 0
    over_cap = max(0, total_remaining - (TRACE_RETENTION_MAX if not dry_run else (total_remaining - deleted_by_age)))

    if over_cap > 0:
        cap_ids = conn.execute(text("""
            SELECT trace_id FROM brain_traces
            ORDER BY created_at ASC
            LIMIT :n
        """), {"n": over_cap}).fetchall()
        cap_trace_ids = [r.trace_id for r in cap_ids]

        if cap_trace_ids and not dry_run:
            conn.execute(text(
                "DELETE FROM brain_trace_spans WHERE trace_id = ANY(:ids)"
            ), {"ids": cap_trace_ids})
            r2 = conn.execute(text(
                "DELETE FROM brain_traces WHERE trace_id = ANY(:ids)"
            ), {"ids": cap_trace_ids})
            conn.commit()
            deleted_by_cap = r2.rowcount or 0
        else:
            deleted_by_cap = len(cap_trace_ids)

    return {
        "dry_run":         dry_run,
        "deleted_by_age":  deleted_by_age,
        "deleted_by_cap":  deleted_by_cap,
        "retention_days":  TRACE_RETENTION_DAYS,
        "retention_max":   TRACE_RETENTION_MAX,
    }


_DEBATE_JOB_RETENTION_DAYS = 14  # delete debate_jobs older than this


def _prune_debate_jobs(conn, dry_run: bool) -> dict:
    """
    Delete debate_jobs rows older than _DEBATE_JOB_RETENTION_DAYS days.
    Best-effort and idempotent — skipped silently if the table doesn't exist.
    """
    tbl_exists = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='debate_jobs'"
    )).scalar() or 0
    if not tbl_exists:
        return {"skipped": True, "reason": "debate_jobs table does not exist yet"}

    old_ids = conn.execute(text(
        "SELECT id FROM debate_jobs "
        "WHERE created_at < NOW() - INTERVAL ':days days'"
        .replace(":days days", f"{_DEBATE_JOB_RETENTION_DAYS} days")
    )).fetchall()

    deleted = 0
    if old_ids and not dry_run:
        id_list = [r[0] for r in old_ids]
        r = conn.execute(text(
            "DELETE FROM debate_jobs WHERE id = ANY(:ids)"
        ), {"ids": id_list})
        conn.commit()
        deleted = r.rowcount or 0
    else:
        deleted = len(old_ids)

    return {
        "dry_run":        dry_run,
        "deleted":        deleted,
        "retention_days": _DEBATE_JOB_RETENTION_DAYS,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Soft retention: archive old SESSION_SUMMARY rows per project."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print counts, write nothing")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP_ACTIVE,
                        help=f"Number of active summaries to keep per project (default {DEFAULT_KEEP_ACTIVE})")
    parser.add_argument("--project-id", type=int, default=None,
                        help="Limit to a single project_id_int")
    parser.add_argument("--prune-traces-only", action="store_true",
                        help="Only prune brain_traces/spans; skip SESSION_SUMMARY archival")
    args = parser.parse_args()

    keep = max(1, args.keep)

    print("=" * 65)
    print("📦 Brain: archive_old_summaries")
    print(f"   keep_active      : {keep}")
    print(f"   dry_run          : {args.dry_run}")
    print(f"   prune_traces_only: {args.prune_traces_only}")
    print(f"   trace_retain_days: {TRACE_RETENTION_DAYS}")
    print(f"   trace_retain_max : {TRACE_RETENTION_MAX}")
    if args.project_id:
        print(f"   project_id  : {args.project_id}")
    print("=" * 65)

    engine = create_engine(get_database_url())

    # ── Trace pruning (always runs, best-effort) ───────────────────
    print("\n── Trace retention ──────────────────────────────────────")
    try:
        with engine.connect() as conn:
            trace_stats = _prune_traces(conn, args.dry_run)
        if trace_stats.get("skipped"):
            print(f"  Skipped: {trace_stats.get('reason')}")
        else:
            action_word = "would delete" if args.dry_run else "deleted"
            print(f"  By age  : {action_word} {trace_stats['deleted_by_age']} trace(s) "
                  f"(>{TRACE_RETENTION_DAYS}d)")
            print(f"  By cap  : {action_word} {trace_stats['deleted_by_cap']} trace(s) "
                  f"(>last {TRACE_RETENTION_MAX})")
    except Exception as exc:
        print(f"  Trace pruning error (non-fatal): {exc}")

    # ── Debate job pruning (best-effort) ───────────────────────────
    print("\n── Debate job retention ──────────────────────────────────")
    try:
        with engine.connect() as conn:
            job_stats = _prune_debate_jobs(conn, args.dry_run)
        if job_stats.get("skipped"):
            print(f"  Skipped: {job_stats.get('reason')}")
        else:
            action_word = "would delete" if args.dry_run else "deleted"
            print(f"  {action_word} {job_stats['deleted']} debate_job(s) "
                  f"(>{_DEBATE_JOB_RETENTION_DAYS}d)")
    except Exception as exc:
        print(f"  Debate job pruning error (non-fatal): {exc}")

    if args.prune_traces_only:
        print("\nDone (--prune-traces-only).")
        return

    with engine.connect() as conn:
        # Discover projects that have SESSION_SUMMARYs
        if args.project_id:
            project_ids = [args.project_id]
        else:
            rows = conn.execute(text("""
                SELECT DISTINCT project_id_int
                FROM canon_items
                WHERE type = 'SESSION_SUMMARY'
                  AND project_id_int IS NOT NULL
                ORDER BY project_id_int
            """)).fetchall()
            project_ids = [r.project_id_int for r in rows]

        if not project_ids:
            print("\nℹ️  No SESSION_SUMMARY rows found.")
            return

        report: list[dict] = []
        errors: list[tuple] = []

        for pid in project_ids:
            try:
                stats = _run_project(conn, pid, keep, args.dry_run)
                report.append({"project_id": pid, **stats})
            except Exception as exc:
                errors.append((pid, str(exc)))
                try:
                    conn.rollback()
                except Exception:
                    pass

    # ── Summary table ─────────────────────────────────────────────
    print()
    action = "WOULD ARCHIVE" if args.dry_run else "ARCHIVED"
    print(f"{'project_id':>12}  {'total':>7}  {'active_before':>13}  {'kept_active':>11}  {action:>10}")
    print("-" * 65)
    for r in report:
        kept = min(r["active_before"], keep)
        archived_col = r["to_archive"] if args.dry_run else r["archived"]
        print(f"{r['project_id']:>12}  {r['total']:>7}  {r['active_before']:>13}  {kept:>11}  {archived_col:>10}")

    total_archived = sum(r["archived"] for r in report)
    total_to_archive = sum(r["to_archive"] for r in report)

    print("-" * 65)
    if args.dry_run:
        print(f"DRY RUN — would archive {total_to_archive} rows total across {len(report)} project(s).")
    else:
        print(f"Archived {total_archived} rows total across {len(report)} project(s).")

    if errors:
        print(f"\n⚠️  Errors in {len(errors)} project(s):")
        for pid, msg in errors:
            print(f"  project {pid}: {msg}")

    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        print(f"\n❌ Script failed: {exc}")
        traceback.print_exc()
        sys.exit(1)
