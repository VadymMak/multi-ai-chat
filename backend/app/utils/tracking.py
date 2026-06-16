"""
Fire-and-forget access tracking for canon_items and memory_entries.

Usage (sync or async context — always non-blocking):
    from app.utils.tracking import bump_access_bg
    from app.memory.db import SessionLocal

    bump_access_bg(SessionLocal, "canon_items", [row.id for row in rows])
    bump_access_bg(SessionLocal, "memory_entries", [r.id for r in hits])
"""
import logging
import threading
from typing import Callable, List

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _bump_sync(db_factory: Callable, table: str, ids: List[int]) -> None:
    db = db_factory()
    try:
        db.execute(
            text(f"""
                UPDATE {table}
                SET access_count     = access_count + 1,
                    last_accessed_at = NOW()
                WHERE id = ANY(:ids)
            """),
            {"ids": ids},
        )
        db.commit()
    except Exception as exc:
        logger.warning("bump_access %s ids=%s: %s", table, ids, exc)
    finally:
        db.close()


def bump_access_bg(db_factory: Callable, table: str, ids: List[int]) -> None:
    """Start a daemon thread to bump access counters — returns immediately."""
    if not ids:
        return
    threading.Thread(
        target=_bump_sync, args=(db_factory, table, ids), daemon=True
    ).start()
