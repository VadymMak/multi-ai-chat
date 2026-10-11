#!/usr/bin/env python3
"""
One-time cleanup: remove eval harness files from file_embeddings.

eval_cases.py and tests/evals/** were indexed before being added to SKIP_PATTERNS.
Their embeddings contaminate retrieval evals (file ranks for its own query strings).
This script deletes only those specific rows. Safe to re-run (DELETE of 0 rows is fine).
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy import create_engine, text


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
            url = os.environ.get("DATABASE_URL", "")
        except ImportError:
            pass
    if not url:
        url = f"sqlite:///{os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'memory.db'))}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def run() -> None:
    print("Cleanup: remove eval contamination rows from file_embeddings")
    url = _db_url()
    engine = create_engine(url)

    with engine.connect() as conn:
        try:
            # Delete rows for eval_cases.py (any project)
            r1 = conn.execute(text(
                "DELETE FROM file_embeddings WHERE file_path LIKE '%app/config/eval_cases.py%'"
            ))
            r1_count = r1.rowcount if r1.rowcount is not None else 0

            # Delete rows for tests/evals/** (any project)
            r2 = conn.execute(text(
                "DELETE FROM file_embeddings WHERE file_path LIKE '%tests/evals/%'"
            ))
            r2_count = r2.rowcount if r2.rowcount is not None else 0

            conn.commit()
            print(f"  Deleted {r1_count} eval_cases.py row(s)")
            print(f"  Deleted {r2_count} tests/evals row(s)")
        except Exception as e:
            conn.rollback()
            print(f"  Cleanup skipped (non-fatal): {e}")

    print("Cleanup complete.")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"Cleanup failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()
    sys.exit(0)
