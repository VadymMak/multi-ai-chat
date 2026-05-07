#!/usr/bin/env python3
"""
Claude Code usage parser.

Walks the Claude Code project directories at ~/.claude/projects/*/*.jsonl,
parses assistant messages with usage data, computes cost using current Claude
4.x pricing, and inserts rows into claude_usage_logs.

Pricing (USD per 1M tokens):
    Opus 4.x:    $15.00 input, $75.00 output
    Sonnet 4.x:  $3.00  input, $15.00 output
    Haiku 4.x:   $0.25  input, $1.25  output
    Cache read:  90% discount on the model's input price
    Cache write: 25% premium over the model's input price

Run as CLI:
    python backend/scripts/claude_usage_parser.py
    python backend/scripts/claude_usage_parser.py --root ~/.claude/projects
    python backend/scripts/claude_usage_parser.py --since 2026-01-01

Or import and call:
    from backend.scripts.claude_usage_parser import sync_usage
    result = sync_usage(db_session)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Pricing
# ─────────────────────────────────────────────────────────────────
PRICING = {
    "opus":   {"input": 15.00 / 1_000_000, "output": 75.00 / 1_000_000},
    "sonnet": {"input":  3.00 / 1_000_000, "output": 15.00 / 1_000_000},
    "haiku":  {"input":  0.25 / 1_000_000, "output":  1.25 / 1_000_000},
}
CACHE_READ_DISCOUNT = 0.10   # cache read costs 10% of input price
CACHE_WRITE_PREMIUM = 1.25   # cache creation costs 125% of input price

BRAIN_TOOL_NAMES = {
    "search_project_files", "get_file_content", "hybrid_search_files",
    "build_context_for_query", "get_active_project", "get_project_stats",
    "get_index_status", "get_developer_patterns", "get_file_dependencies",
    "get_file_versions", "list_canon_items", "save_session_summary",
    "get_session_summaries", "search_session_memory",
    "search_conversation_memory", "ensure_project_indexed",
    "create_project_with_index", "index_local_project",
}


def detect_model_family(model: str) -> str:
    """Map a model id like 'claude-opus-4-7' to a pricing key."""
    m = (model or "").lower()
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    # default to sonnet pricing for unknown model
    return "sonnet"


@dataclass
class UsageRecord:
    session_id: Optional[str]
    message_id: Optional[str]
    request_id: Optional[str]
    timestamp: datetime
    model: str
    project_path: Optional[str]
    project_name: Optional[str]
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float
    cost_without_cache_usd: float
    cache_savings_usd: float
    used_brain_context: bool
    brain_tools_called: List[str]
    had_retry: bool
    raw_jsonl_path: str

    @property
    def total_tokens(self) -> int:
        return (self.input_tokens + self.output_tokens
                + self.cache_creation_tokens + self.cache_read_tokens)


def calc_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation: int,
    cache_read: int,
) -> Tuple[float, float, float]:
    """Return (actual_cost, cost_if_no_cache, cache_savings)."""
    family = detect_model_family(model)
    p = PRICING[family]
    in_price = p["input"]
    out_price = p["output"]

    actual = (
        input_tokens * in_price
        + output_tokens * out_price
        + cache_creation * in_price * CACHE_WRITE_PREMIUM
        + cache_read * in_price * CACHE_READ_DISCOUNT
    )
    # If there were no cache, those tokens would have been priced as input.
    no_cache = (
        (input_tokens + cache_creation + cache_read) * in_price
        + output_tokens * out_price
    )
    savings = max(0.0, no_cache - actual)
    return actual, no_cache, savings


# ─────────────────────────────────────────────────────────────────
# JSONL traversal
# ─────────────────────────────────────────────────────────────────
def default_claude_root() -> Path:
    return Path.home() / ".claude" / "projects"


def project_name_from_dir(dir_name: str) -> Tuple[str, str]:
    """
    Claude Code encodes project paths as folder names by replacing path
    separators with `-`. We can't fully recover the path, but we expose both
    the encoded name and a best-effort decoded form.
    """
    encoded = dir_name
    decoded = dir_name.replace("--", "/").replace("-", "/")
    return decoded, encoded


def iter_jsonl_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            yield jsonl


def parse_assistant_record(
    obj: Dict[str, Any],
    project_path: str,
    project_name: str,
    jsonl_path: Path,
) -> Optional[UsageRecord]:
    """Extract usage from a single JSONL line if it is an assistant turn."""
    if obj.get("type") != "assistant":
        return None

    msg = obj.get("message") or {}
    usage = msg.get("usage") or {}
    if not usage:
        return None

    model = msg.get("model") or obj.get("model") or "unknown"
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)

    if input_tokens + output_tokens + cache_creation + cache_read == 0:
        return None

    ts_raw = obj.get("timestamp") or msg.get("created_at")
    try:
        timestamp = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")) \
            if ts_raw else datetime.now(timezone.utc)
    except Exception:
        timestamp = datetime.now(timezone.utc)

    # Brain detection: scan tool_use blocks in the assistant content
    brain_tools: List[str] = []
    content = msg.get("content") or []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = (block.get("name") or "").split("__")[-1]
                if name in BRAIN_TOOL_NAMES:
                    brain_tools.append(name)

    actual, no_cache, savings = calc_cost(
        model, input_tokens, output_tokens, cache_creation, cache_read
    )

    return UsageRecord(
        session_id=obj.get("sessionId") or obj.get("session_id"),
        message_id=msg.get("id"),
        request_id=obj.get("requestId") or obj.get("request_id"),
        timestamp=timestamp,
        model=model,
        project_path=project_path,
        project_name=project_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation,
        cache_read_tokens=cache_read,
        cost_usd=actual,
        cost_without_cache_usd=no_cache,
        cache_savings_usd=savings,
        used_brain_context=bool(brain_tools),
        brain_tools_called=brain_tools,
        had_retry=bool(obj.get("isApiErrorMessage")),
        raw_jsonl_path=str(jsonl_path),
    )


def parse_jsonl_file(path: Path) -> List[UsageRecord]:
    decoded, encoded = project_name_from_dir(path.parent.name)
    out: List[UsageRecord] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rec = parse_assistant_record(obj, decoded, encoded, path)
                if rec:
                    out.append(rec)
    except Exception as e:
        logger.warning("failed to parse %s: %s", path, e)
    return out


# ─────────────────────────────────────────────────────────────────
# DB insertion
# ─────────────────────────────────────────────────────────────────
def _project_id_for_path(db: Session, project_path: Optional[str]) -> Optional[int]:
    if not project_path:
        return None
    try:
        row = db.execute(
            text("""
                SELECT id FROM projects
                WHERE name = :n
                LIMIT 1
            """),
            {"n": project_path.rstrip("/").split("/")[-1]},
        ).fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


def insert_records(db: Session, records: List[UsageRecord]) -> Dict[str, int]:
    inserted = 0
    skipped = 0
    for rec in records:
        try:
            project_id = _project_id_for_path(db, rec.project_path)
            params = {
                "session_id": rec.session_id,
                "message_id": rec.message_id,
                "request_id": rec.request_id,
                "timestamp": rec.timestamp,
                "model": rec.model,
                "project_id": project_id,
                "project_path": rec.project_path,
                "project_name": rec.project_name,
                "input_tokens": rec.input_tokens,
                "output_tokens": rec.output_tokens,
                "cache_creation_tokens": rec.cache_creation_tokens,
                "cache_read_tokens": rec.cache_read_tokens,
                "total_tokens": rec.total_tokens,
                "cost_usd": rec.cost_usd,
                "cost_without_cache_usd": rec.cost_without_cache_usd,
                "cache_savings_usd": rec.cache_savings_usd,
                "used_brain_context": rec.used_brain_context,
                "brain_tools_called": rec.brain_tools_called,
                "had_retry": rec.had_retry,
                "raw_jsonl_path": rec.raw_jsonl_path,
            }
            dialect = db.bind.dialect.name if db.bind else "postgresql"
            # SAVEPOINT per record so a single bad row doesn't poison the
            # outer transaction (Postgres aborts on any error otherwise).
            with db.begin_nested():
                if dialect == "postgresql":
                    result = db.execute(
                        text("""
                            INSERT INTO claude_usage_logs (
                                session_id, message_id, request_id, timestamp, model,
                                project_id, project_path, project_name,
                                input_tokens, output_tokens, cache_creation_tokens,
                                cache_read_tokens, total_tokens,
                                cost_usd, cost_without_cache_usd, cache_savings_usd,
                                used_brain_context, brain_tools_called,
                                had_retry, raw_jsonl_path
                            ) VALUES (
                                :session_id, :message_id, :request_id, :timestamp, :model,
                                :project_id, :project_path, :project_name,
                                :input_tokens, :output_tokens, :cache_creation_tokens,
                                :cache_read_tokens, :total_tokens,
                                :cost_usd, :cost_without_cache_usd, :cache_savings_usd,
                                :used_brain_context, :brain_tools_called,
                                :had_retry, :raw_jsonl_path
                            )
                            ON CONFLICT (message_id) DO NOTHING
                            RETURNING id
                        """),
                        params,
                    )
                    if result.fetchone():
                        inserted += 1
                    else:
                        skipped += 1
                else:
                    # SQLite: serialize array, dedupe via existence check
                    params["brain_tools_called"] = json.dumps(rec.brain_tools_called)
                    params["used_brain_context"] = 1 if rec.used_brain_context else 0
                    params["had_retry"] = 1 if rec.had_retry else 0
                    exists = db.execute(
                        text("SELECT 1 FROM claude_usage_logs WHERE message_id = :mid"),
                        {"mid": rec.message_id},
                    ).fetchone()
                    if exists:
                        skipped += 1
                    else:
                        db.execute(
                            text("""
                                INSERT INTO claude_usage_logs (
                                    session_id, message_id, request_id, timestamp, model,
                                    project_id, project_path, project_name,
                                    input_tokens, output_tokens, cache_creation_tokens,
                                    cache_read_tokens, total_tokens,
                                    cost_usd, cost_without_cache_usd, cache_savings_usd,
                                    used_brain_context, brain_tools_called,
                                    had_retry, raw_jsonl_path
                                ) VALUES (
                                    :session_id, :message_id, :request_id, :timestamp, :model,
                                    :project_id, :project_path, :project_name,
                                    :input_tokens, :output_tokens, :cache_creation_tokens,
                                    :cache_read_tokens, :total_tokens,
                                    :cost_usd, :cost_without_cache_usd, :cache_savings_usd,
                                    :used_brain_context, :brain_tools_called,
                                    :had_retry, :raw_jsonl_path
                                )
                            """),
                            params,
                        )
                        inserted += 1
        except Exception as e:
            db.rollback()  # reset aborted outer-transaction state so the next iteration starts clean
            logger.warning("insert failed for %s: %s", rec.message_id, e)
            skipped += 1
    db.commit()
    return {"inserted": inserted, "skipped": skipped}


def aggregate_daily(db: Session) -> int:
    """Recompute usage_daily_stats from claude_usage_logs."""
    db.execute(text("DELETE FROM usage_daily_stats"))
    dialect = db.bind.dialect.name if db.bind else "postgresql"
    if dialect == "postgresql":
        db.execute(text("""
            INSERT INTO usage_daily_stats (
                date, project_id, project_name, model,
                request_count, input_tokens, output_tokens,
                cache_creation_tokens, cache_read_tokens, total_tokens,
                cost_usd, cache_savings_usd,
                brain_assisted_count, retry_count
            )
            SELECT
                DATE(timestamp), project_id, MAX(project_name), model,
                COUNT(*),
                COALESCE(SUM(input_tokens), 0),
                COALESCE(SUM(output_tokens), 0),
                COALESCE(SUM(cache_creation_tokens), 0),
                COALESCE(SUM(cache_read_tokens), 0),
                COALESCE(SUM(total_tokens), 0),
                COALESCE(SUM(cost_usd), 0),
                COALESCE(SUM(cache_savings_usd), 0),
                COALESCE(SUM(CASE WHEN used_brain_context THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN had_retry THEN 1 ELSE 0 END), 0)
            FROM claude_usage_logs
            GROUP BY DATE(timestamp), project_id, model
        """))
    else:
        db.execute(text("""
            INSERT INTO usage_daily_stats (
                date, project_id, project_name, model,
                request_count, input_tokens, output_tokens,
                cache_creation_tokens, cache_read_tokens, total_tokens,
                cost_usd, cache_savings_usd,
                brain_assisted_count, retry_count
            )
            SELECT
                DATE(timestamp), project_id, MAX(project_name), model,
                COUNT(*),
                COALESCE(SUM(input_tokens), 0),
                COALESCE(SUM(output_tokens), 0),
                COALESCE(SUM(cache_creation_tokens), 0),
                COALESCE(SUM(cache_read_tokens), 0),
                COALESCE(SUM(total_tokens), 0),
                COALESCE(SUM(cost_usd), 0),
                COALESCE(SUM(cache_savings_usd), 0),
                COALESCE(SUM(used_brain_context), 0),
                COALESCE(SUM(had_retry), 0)
            FROM claude_usage_logs
            GROUP BY DATE(timestamp), project_id, model
        """))
    row = db.execute(text("SELECT COUNT(*) FROM usage_daily_stats")).fetchone()
    db.commit()
    return int(row[0]) if row else 0


# ─────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────
def sync_usage(
    db: Session,
    root: Optional[Path] = None,
    since: Optional[date] = None,
) -> Dict[str, Any]:
    """Read all JSONL files under `root`, insert new records, refresh aggregates."""
    root = Path(root) if root else default_claude_root()
    all_records: List[UsageRecord] = []
    files_scanned = 0

    for jsonl in iter_jsonl_files(root):
        files_scanned += 1
        recs = parse_jsonl_file(jsonl)
        if since:
            recs = [r for r in recs if r.timestamp.date() >= since]
        all_records.extend(recs)

    insert_result = insert_records(db, all_records)
    daily_rows = aggregate_daily(db)

    return {
        "root": str(root),
        "files_scanned": files_scanned,
        "records_parsed": len(all_records),
        "inserted": insert_result["inserted"],
        "skipped": insert_result["skipped"],
        "daily_stat_rows": daily_rows,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Parse Claude Code JSONL usage logs.")
    parser.add_argument("--root", type=str, default=None,
                        help="Path to ~/.claude/projects (default uses HOME)")
    parser.add_argument("--since", type=str, default=None,
                        help="Only ingest records on/after this date (YYYY-MM-DD)")
    args = parser.parse_args()

    since = None
    if args.since:
        since = date.fromisoformat(args.since)

    from app.memory.db import SessionLocal
    db = SessionLocal()
    try:
        result = sync_usage(
            db,
            root=Path(args.root) if args.root else None,
            since=since,
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
