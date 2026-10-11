"""
Eval harness runner.

run_suite(suite, model_key) executes all eval cases (or one suite),
applies mechanical asserts, persists each row to brain_evals, and returns
a report with denominators:
  { run_id, suite, total, passed, failed, model_key, elapsed_s, results }
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.config.eval_cases import EVAL_CASES
from app.memory.db import SessionLocal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────

def _persist_result(row: dict) -> None:
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO brain_evals
                (run_id, suite, eval_name, passed, score, model_key, details)
            VALUES
                (:run_id, :suite, :eval_name, :passed, :score, :model_key, :details)
        """), {
            "run_id":     row["run_id"],
            "suite":      row["suite"],
            "eval_name":  row["eval_name"],
            "passed":     row["passed"],
            "score":      row.get("score"),
            "model_key":  row.get("model_key"),
            "details":    json.dumps(row.get("details") or {}, ensure_ascii=False),
        })
        db.commit()
    except Exception as exc:
        logger.warning("eval_persist error for %s: %s", row.get("eval_name"), exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Case executors
# ─────────────────────────────────────────────────────────────────────────────

async def _run_hybrid_search_case(case: dict) -> dict:
    from app.services.hybrid_search_service import hybrid_search

    inp = case["input"]
    top_n = inp.get("top_n", 5)

    db = SessionLocal()
    try:
        results: List[dict] = await asyncio.to_thread(
            hybrid_search,
            inp["query"],
            inp["project_id"],
            db,
            limit=top_n,
        )
    finally:
        db.close()

    top_paths = [r.get("file_path", "") for r in results[:top_n]]
    fragment = case["expected_file"]

    if case["assert"] == "file_in_top_n":
        matched = any(fragment in p for p in top_paths)
        return {
            "passed": matched,
            "details": {
                "top_paths": top_paths,
                "expected_fragment": fragment,
                "matched": matched,
            },
        }

    if case["assert"] == "file_not_in_top_n":
        not_matched = not any(fragment in p for p in top_paths)
        return {
            "passed": not_matched,
            "details": {
                "top_paths": top_paths,
                "expected_fragment": fragment,
                "not_found": not_matched,
            },
        }

    return {"passed": False, "details": {"reason": f"unknown assert: {case['assert']}"}}


async def _run_build_context_case(case: dict) -> dict:
    from app.services.smart_context import build_smart_context
    from app.memory.manager import MemoryManager
    from app.services.trace_service import trace as _trace, trace_span as _span

    inp = case["input"]
    query = inp["query"]

    db = SessionLocal()
    try:
        memory = MemoryManager(db)
        context: str = ""
        try:
            async with _trace("query", summary=f"eval:{case['name']} q={query[:100]}") as _t:
                async with _span(_t, "context", "smart_context",
                                 input_summary=f"pid={inp['project_id']} q={query[:100]}") as _s:
                    context = await build_smart_context(
                        project_id=inp["project_id"],
                        role_id=inp.get("role_id", 0),
                        query=query,
                        session_id="",
                        db=db,
                        memory=memory,
                    )
                    _s["output_summary"] = f"{len(context)} chars"
        except Exception:
            context = await build_smart_context(
                project_id=inp["project_id"],
                role_id=inp.get("role_id", 0),
                query=query,
                session_id="",
                db=db,
                memory=memory,
            )
    finally:
        db.close()

    if case["assert"] == "non_empty_under_budget":
        max_chars = case.get("max_chars", 20_000)
        non_empty = bool(context and context.strip())
        under_budget = len(context) <= max_chars
        return {
            "passed": non_empty and under_budget,
            "score": len(context),
            "details": {
                "length": len(context),
                "max_chars": max_chars,
                "non_empty": non_empty,
                "under_budget": under_budget,
            },
        }

    if case["assert"] == "contains_markers":
        markers = case.get("markers", [])
        found = [m for m in markers if m in context]
        return {
            "passed": len(found) > 0,
            "details": {
                "markers_found": found,
                "markers_checked": markers,
            },
        }

    return {"passed": False, "details": {"reason": f"unknown assert: {case['assert']}"}}


async def _run_quote_supported_case(case: dict) -> dict:
    from app.services.verify_manager import quote_supported

    inp = case["input"]
    result: bool = await asyncio.to_thread(
        quote_supported, inp["quote"], inp["document"]
    )

    if case["assert"] == "is_true":
        return {
            "passed": result is True,
            "details": {"quote": inp["quote"][:80], "result": result},
        }

    if case["assert"] == "is_false":
        return {
            "passed": result is False,
            "details": {"quote": inp["quote"][:80], "result": result},
        }

    return {"passed": False, "details": {"reason": f"unknown assert: {case['assert']}"}}


async def _run_resolve_source_case(case: dict) -> dict:
    from app.services.verify_manager import _resolve_source

    inp = case["input"]
    result = await asyncio.to_thread(_resolve_source, inp["source"])

    if case["assert"] == "is_none":
        return {
            "passed": result is None,
            "details": {"source": inp["source"], "result": result},
        }

    if case["assert"] == "url_contains":
        fragment = case.get("expected_url_fragment", "")
        url = (result or {}).get("url", "")
        passed = result is not None and fragment in url
        return {
            "passed": passed,
            "details": {
                "source": inp["source"],
                "url": url,
                "expected_fragment": fragment,
            },
        }

    return {"passed": False, "details": {"reason": f"unknown assert: {case['assert']}"}}


async def _run_extract_claims_case(case: dict) -> dict:
    from app.services.verify_manager import extract_claims

    inp = case["input"]
    text = inp["text"]
    model_key = inp.get("model_key", "gpt-4o-mini")

    all_claims = await asyncio.to_thread(extract_claims, text, model_key)
    fact_count = sum(1 for c in all_claims if c.get("type") == "fact")

    if case["assert"] == "count_within_tolerance":
        expected = case["expected_count"]
        tol = case.get("tolerance", 2)
        passed = abs(fact_count - expected) <= tol
        return {
            "passed": passed,
            "score": fact_count,
            "details": {
                "fact_count": fact_count,
                "expected_count": expected,
                "tolerance": tol,
                "model_key": model_key,
                "claims_preview": [c["claim"][:80] for c in all_claims[:8]],
            },
        }

    return {"passed": False, "details": {"reason": f"unknown assert: {case['assert']}"}}


async def _run_skip_case(case: dict) -> dict:
    return {
        "passed": True,
        "details": {
            "status": "skipped",
            "reason": case.get("description", "no reason given"),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

_DISPATCHERS = {
    "hybrid_search":       _run_hybrid_search_case,
    "build_smart_context": _run_build_context_case,
    "quote_supported":     _run_quote_supported_case,
    "resolve_source":      _run_resolve_source_case,
    "extract_claims":      _run_extract_claims_case,
    "skip":                _run_skip_case,
}


async def run_suite(
    suite: str = "all",
    model_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run eval cases and return a report with denominators.
    One bad case never aborts the run — exceptions are caught per-case.
    """
    t0 = time.perf_counter()
    run_id = str(uuid.uuid4())

    cases = EVAL_CASES if suite == "all" else [c for c in EVAL_CASES if c["suite"] == suite]

    results: List[dict] = []

    for case in cases:
        row: Dict[str, Any] = {
            "run_id":    run_id,
            "suite":     case["suite"],
            "eval_name": case["name"],
            "model_key": model_key,
            "passed":    False,
            "score":     None,
            "details":   {},
        }

        try:
            dispatcher = _DISPATCHERS.get(case["kind"])
            if dispatcher is None:
                row["details"] = {"reason": f"unknown kind: {case['kind']}"}
            else:
                outcome = await dispatcher(case)
                row.update(outcome)
        except Exception as exc:
            logger.warning("eval case %s raised: %s", case["name"], exc)
            row["passed"] = False
            row["details"] = {"error": str(exc)}

        # Persist (best-effort — failure does not affect the report)
        try:
            await asyncio.to_thread(_persist_result, row)
        except Exception as exc:
            logger.warning("eval persist failed for %s: %s", case["name"], exc)

        results.append({
            "eval_name": row["eval_name"],
            "suite":     row["suite"],
            "passed":    row["passed"],
            "score":     row.get("score"),
            "details":   row.get("details", {}),
        })

    total   = len(results)
    passed  = sum(1 for r in results if r["passed"])
    elapsed = round(time.perf_counter() - t0, 3)

    return {
        "run_id":    run_id,
        "suite":     suite,
        "total":     total,
        "passed":    passed,
        "failed":    total - passed,
        "model_key": model_key,
        "elapsed_s": elapsed,
        "results":   results,
    }
