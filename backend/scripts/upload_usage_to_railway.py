#!/usr/bin/env python3
"""
Upload local Claude Code JSONL usage logs to the Railway backend.

Walks ~/.claude/projects/*/*.jsonl, parses assistant turns that carry a
`usage` block, applies Claude 4.x pricing, and POSTs the parsed records as
JSON to the Railway sync endpoint. Designed to run on the Windows host where
the JSONL files live; the Railway container itself can't see them.

Usage:
    python backend/scripts/upload_usage_to_railway.py
    python backend/scripts/upload_usage_to_railway.py --since 2026-04-01
    python backend/scripts/upload_usage_to_railway.py --root "C:\\Users\\eto\\.claude\\projects"
    python backend/scripts/upload_usage_to_railway.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_URL = "https://multi-ai-chat-production.up.railway.app/api/usage/sync"
DEFAULT_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxIiwiZXhwIjoxODA5MDYwMTA2fQ."
    "088PkzLccpsp4adsYxmqFyvbliqDGFAZRF_A1U0KF5s"
)
DEFAULT_BATCH_SIZE = 50


# Pricing matches backend/scripts/claude_usage_parser.py.
PRICING = {
    "opus":   {"input": 15.00 / 1_000_000, "output": 75.00 / 1_000_000},
    "sonnet": {"input":  3.00 / 1_000_000, "output": 15.00 / 1_000_000},
    "haiku":  {"input":  0.25 / 1_000_000, "output":  1.25 / 1_000_000},
}
CACHE_READ_DISCOUNT = 0.10
CACHE_WRITE_PREMIUM = 1.25

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
    m = (model or "").lower()
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return "sonnet"


def calc_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation: int,
    cache_read: int,
) -> Tuple[float, float, float]:
    p = PRICING[detect_model_family(model)]
    in_price, out_price = p["input"], p["output"]
    actual = (
        input_tokens * in_price
        + output_tokens * out_price
        + cache_creation * in_price * CACHE_WRITE_PREMIUM
        + cache_read * in_price * CACHE_READ_DISCOUNT
    )
    no_cache = (
        (input_tokens + cache_creation + cache_read) * in_price
        + output_tokens * out_price
    )
    return actual, no_cache, max(0.0, no_cache - actual)


@dataclass
class UsageRecord:
    session_id: Optional[str]
    message_id: Optional[str]
    request_id: Optional[str]
    timestamp: str
    model: str
    project_path: Optional[str]
    project_name: Optional[str]
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_tokens: int
    cost_usd: float
    cost_without_cache_usd: float
    cache_savings_usd: float
    used_brain_context: bool
    brain_tools_called: List[str]
    had_retry: bool
    raw_jsonl_path: str


def project_name_from_dir(dir_name: str) -> Tuple[str, str]:
    return dir_name.replace("--", "/").replace("-", "/"), dir_name


def iter_jsonl_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            yield jsonl


def parse_assistant_line(
    obj: Dict[str, Any],
    project_path: str,
    project_name: str,
    jsonl_path: Path,
) -> Optional[UsageRecord]:
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
        ts = (datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
              if ts_raw else datetime.now(timezone.utc))
    except Exception:
        ts = datetime.now(timezone.utc)

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
        timestamp=ts.isoformat(),
        model=model,
        project_path=project_path,
        project_name=project_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation,
        cache_read_tokens=cache_read,
        total_tokens=input_tokens + output_tokens + cache_creation + cache_read,
        cost_usd=actual,
        cost_without_cache_usd=no_cache,
        cache_savings_usd=savings,
        used_brain_context=bool(brain_tools),
        brain_tools_called=brain_tools,
        had_retry=bool(obj.get("isApiErrorMessage")),
        raw_jsonl_path=str(jsonl_path),
    )


def parse_jsonl_file(path: Path, since: Optional[date]) -> List[UsageRecord]:
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
                rec = parse_assistant_line(obj, decoded, encoded, path)
                if rec is None:
                    continue
                if since:
                    try:
                        rec_date = datetime.fromisoformat(rec.timestamp).date()
                    except Exception:
                        rec_date = None
                    if rec_date and rec_date < since:
                        continue
                out.append(rec)
    except Exception as e:
        print(f"WARN: failed to parse {path}: {e}", file=sys.stderr)
    return out


def post_batch(url: str, token: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
    body = json.dumps({"records": records}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                return {"raw_response": payload, "status": resp.status}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {detail}") from e


def chunked(seq: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=str, default=None,
                        help="Path to ~/.claude/projects (default: $HOME/.claude/projects)")
    parser.add_argument("--since", type=str, default=None,
                        help="Only upload records on/after this date (YYYY-MM-DD)")
    parser.add_argument("--url", type=str, default=os.environ.get("USAGE_SYNC_URL", DEFAULT_URL))
    parser.add_argument("--token", type=str,
                        default=os.environ.get("USAGE_SYNC_TOKEN", DEFAULT_TOKEN))
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and summarize without POSTing")
    args = parser.parse_args()

    root = Path(args.root) if args.root else Path.home() / ".claude" / "projects"
    if not root.exists():
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 2

    since: Optional[date] = None
    if args.since:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            print("ERROR: --since must be YYYY-MM-DD", file=sys.stderr)
            return 2

    files_scanned = 0
    all_records: List[UsageRecord] = []
    for jsonl in iter_jsonl_files(root):
        files_scanned += 1
        all_records.extend(parse_jsonl_file(jsonl, since))

    total_cost = sum(r.cost_usd for r in all_records)
    total_no_cache_cost = sum(r.cost_without_cache_usd for r in all_records)
    total_savings = sum(r.cache_savings_usd for r in all_records)
    cache_eff_pct = (
        (total_savings / total_no_cache_cost * 100.0)
        if total_no_cache_cost > 0 else 0.0
    )

    print(f"Root:          {root}")
    print(f"Files scanned: {files_scanned}")
    print(f"Records found: {len(all_records)}")
    if since:
        print(f"Since:         {since.isoformat()}")

    if not all_records:
        print("Nothing to upload.")
        return 0

    uploaded = 0
    server_inserted = 0
    server_skipped = 0
    if not args.dry_run:
        payloads = [asdict(r) for r in all_records]
        for batch in chunked(payloads, args.batch_size):
            resp = post_batch(args.url, args.token, batch)
            uploaded += len(batch)
            server_inserted += int(resp.get("inserted", 0) or 0)
            server_skipped += int(resp.get("skipped", 0) or 0)
            print(f"  posted batch: size={len(batch)} "
                  f"inserted={resp.get('inserted', '?')} "
                  f"skipped={resp.get('skipped', '?')}")

    print()
    print("─" * 50)
    print(f"Records uploaded:    {uploaded if not args.dry_run else 0}"
          f"{'  (dry-run)' if args.dry_run else ''}")
    if not args.dry_run:
        print(f"Server inserted:     {server_inserted}")
        print(f"Server skipped:      {server_skipped}  (likely duplicates)")
    print(f"Total cost (USD):    ${total_cost:,.4f}")
    print(f"Cost w/o cache:      ${total_no_cache_cost:,.4f}")
    print(f"Cache savings:       ${total_savings:,.4f}")
    print(f"Cache efficiency:    {cache_eff_pct:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
