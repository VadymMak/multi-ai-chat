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


async def _run_guardrail_case(case: dict) -> dict:
    """
    Calls a destructive MCP tool function directly to verify the confirm-gate.

    setup="insert_registry_row" seeds a throwaway ProjectRegistry row that
    confirm=True will delete; the row uses name="__eval_guardrail_target__" so
    it is clearly a test artifact and never collides with real data.

    assert="preview_response"  → response must have "preview": True, no "deleted" key
    assert="deleted_response"  → response must have "deleted" key truthy
    """
    from app.mcp_server import registry_delete
    from app.memory.db import SessionLocal

    inp = case["input"]
    tool_name = inp["tool"]
    kwargs    = dict(inp.get("kwargs", {}))
    setup     = inp.get("setup")

    if tool_name != "registry_delete":
        return {
            "passed": False,
            "details": {"reason": f"guardrail runner only supports registry_delete, got {tool_name!r}"},
        }

    # ── optional seed ─────────────────────────────────────────────────────────
    if setup == "insert_registry_row":
        db = SessionLocal()
        try:
            # Resolve the same user_id that registry_delete will use
            uid_row = db.execute(
                text("SELECT id FROM users WHERE is_superuser = TRUE ORDER BY id ASC LIMIT 1")
            ).fetchone()
            if not uid_row:
                uid_row = db.execute(
                    text("SELECT id FROM users ORDER BY id ASC LIMIT 1")
                ).fetchone()
            if not uid_row:
                return {"passed": False, "details": {"reason": "no users in DB for seed"}}
            uid = uid_row[0]

            # Remove any stale row from a previous failed run
            db.execute(
                text("DELETE FROM project_registry WHERE name = :n"),
                {"n": "__eval_guardrail_target__"},
            )
            db.execute(
                text(
                    "INSERT INTO project_registry (name, notes, status, user_id) "
                    "VALUES (:n, :notes, 'active', :uid)"
                ),
                {"n": "__eval_guardrail_target__", "notes": "eval guardrail throwaway row", "uid": uid},
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            return {
                "passed": False,
                "details": {"reason": f"setup insert failed: {exc}"},
            }
        finally:
            db.close()

    # ── call the tool ─────────────────────────────────────────────────────────
    raw: str = await registry_delete(**kwargs)
    try:
        result = json.loads(raw)
    except Exception:
        result = {}

    # ── assert ────────────────────────────────────────────────────────────────
    if case["assert"] == "preview_response":
        has_preview   = result.get("preview") is True
        no_deleted    = "deleted" not in result
        confirm_req   = result.get("confirm_required") is True
        passed = has_preview and no_deleted and confirm_req
        return {
            "passed": passed,
            "details": {
                "result":         result,
                "has_preview":    has_preview,
                "no_deleted_key": no_deleted,
                "confirm_required": confirm_req,
            },
        }

    if case["assert"] == "deleted_response":
        deleted_key = "deleted" in result
        deleted_val = bool(result.get("deleted"))
        # Verify row is actually gone
        db = SessionLocal()
        try:
            row = db.execute(
                text("SELECT id FROM project_registry WHERE name = :n"),
                {"n": "__eval_guardrail_target__"},
            ).fetchone()
            row_gone = row is None
        finally:
            db.close()

        passed = deleted_key and deleted_val and row_gone
        return {
            "passed": passed,
            "details": {
                "result":    result,
                "deleted_key": deleted_key,
                "deleted_val": deleted_val,
                "row_gone":    row_gone,
            },
        }

    return {"passed": False, "details": {"reason": f"unknown assert: {case['assert']}"}}


async def _run_debate_stubbed_case(case: dict) -> dict:
    """
    Runs run_debate() with model calls monkeypatched to return canned responses.

    Phase 3: also patches _ask_with_usage_fn (returns (text, in_toks, out_toks))
    and _debate_smart_context_fn (returns a stub context string).
    No live network calls — cheap and deterministic.
    """
    import app.services.debate_engine as _engine_mod

    inp = case["input"]
    ordered_responses: List[str] = inp.get("ask_model_ordered", [])
    verify_stub = inp.get("verify_stub")
    stub_token_counts = tuple(inp.get("stub_token_counts", [100, 50]))  # (in, out)
    context_stub: Optional[str] = inp.get("context_stub")

    call_counter = {"n": 0}
    call_log: List[dict] = []  # records each model call for context assertions

    def _stubbed_ask_model(messages, model_key=None, **kwargs):  # type: ignore[override]
        idx = call_counter["n"] % max(len(ordered_responses), 1)
        call_counter["n"] += 1
        resp = ordered_responses[idx] if ordered_responses else "stub response"
        if resp == "__CRITIC_RAISES__":
            raise RuntimeError("stubbed critic failure")
        return resp

    def _stubbed_ask_with_usage(messages, model_key=None, **kwargs):  # type: ignore[override]
        prompt_text = messages[0].get("content", "") if messages else ""
        call_n_before = call_counter["n"]
        text = _stubbed_ask_model(messages, model_key, **kwargs)  # may raise
        in_toks = int(stub_token_counts[0]) if len(stub_token_counts) > 0 else 100
        out_toks = int(stub_token_counts[1]) if len(stub_token_counts) > 1 else 50
        call_log.append({"call_n": call_n_before, "prompt": prompt_text})
        return text, in_toks, out_toks

    async def _stubbed_smart_context(question, project_id, folder_identifier):
        return context_stub or ""

    # Save originals
    orig_ask_model        = _engine_mod.ask_model
    orig_ask_with_usage   = getattr(_engine_mod, "_ask_with_usage_fn", None)
    orig_debate_verify    = _engine_mod._debate_verify
    orig_smart_context    = getattr(_engine_mod, "_debate_smart_context_fn", None)

    try:
        _engine_mod.ask_model = _stubbed_ask_model  # type: ignore[assignment]
        _engine_mod._ask_with_usage_fn = _stubbed_ask_with_usage  # type: ignore[assignment]

        if context_stub is not None:
            _engine_mod._debate_smart_context_fn = _stubbed_smart_context  # type: ignore[assignment]

        if verify_stub is not None:
            _engine_mod._debate_verify = lambda text, max_claims, fetch, high_assurance: verify_stub  # type: ignore[assignment]
        else:
            _engine_mod._debate_verify = None  # type: ignore[assignment]

        result = await _engine_mod.run_debate(**inp.get("kwargs", {}))

    finally:
        _engine_mod.ask_model = orig_ask_model  # type: ignore[assignment]
        _engine_mod._ask_with_usage_fn = orig_ask_with_usage  # type: ignore[assignment]
        _engine_mod._debate_verify = orig_debate_verify  # type: ignore[assignment]
        _engine_mod._debate_smart_context_fn = orig_smart_context  # type: ignore[assignment]

    assert_type = case["assert"]

    if assert_type == "has_all_keys":
        required = case.get("required_keys", [])
        missing = [k for k in required if k not in result]
        return {
            "passed": not missing,
            "details": {"keys_present": sorted(result.keys()), "missing": missing},
        }

    if assert_type == "confidence_in_range":
        conf = result.get("confidence")
        passed = isinstance(conf, int) and 0 <= conf <= 100
        return {"passed": passed, "details": {"confidence": conf, "type": type(conf).__name__}}

    if assert_type == "critic_failure_degraded":
        has_final    = bool(result.get("final_answer"))
        has_notes    = any("critic" in str(n) for n in result.get("notes", []))
        conf         = result.get("confidence")
        conf_reduced = conf is not None and conf <= 79
        return {
            "passed": has_final and has_notes and conf_reduced,
            "details": {
                "has_final_answer": has_final, "critic_note_found": has_notes,
                "confidence": conf, "notes": result.get("notes"),
            },
        }

    if assert_type == "verify_reduces_confidence":
        base    = case.get("base_confidence", 80)
        penalty = case.get("expected_penalty", 15)
        conf    = result.get("confidence")
        vc      = result.get("verified_claims")
        passed  = (
            conf is not None
            and conf <= base - penalty
            and vc is not None
            and vc.get("refuted_or_unverified", 0) > 0
        )
        return {
            "passed": passed,
            "details": {
                "confidence": conf, "base_confidence": base,
                "expected_max": base - penalty, "verified_claims": vc,
            },
        }

    if assert_type == "has_cost_block":
        cost = result.get("cost")
        passed = (
            isinstance(cost, dict)
            and "total_usd" in cost
            and isinstance(cost.get("by_role"), dict)
            and "proposer_usd" in cost.get("by_role", {})
            and isinstance(cost.get("tokens"), dict)
        )
        return {"passed": passed, "details": {"cost": cost}}

    if assert_type == "context_proposer_only":
        marker = case.get("context_marker", "PROPOSER_CONTEXT_STUB_UNIQUE_MARKER")
        proposer_has_ctx = len(call_log) > 0 and marker in call_log[0].get("prompt", "")
        critic_no_ctx    = len(call_log) < 2 or marker not in call_log[1].get("prompt", "")
        assembler_no_ctx = len(call_log) < 3 or marker not in call_log[2].get("prompt", "")
        context_note     = any("smart_context" in str(n) for n in result.get("notes", []))
        passed = proposer_has_ctx and critic_no_ctx and assembler_no_ctx and context_note
        return {
            "passed": passed,
            "details": {
                "proposer_has_context":  proposer_has_ctx,
                "critic_no_context":     critic_no_ctx,
                "assembler_no_context":  assembler_no_ctx,
                "context_note_in_notes": context_note,
                "notes":                 result.get("notes"),
                "call_count":            len(call_log),
            },
        }

    return {"passed": False, "details": {"reason": f"unknown assert: {assert_type}"}}


async def _run_debate_job_case(case: dict) -> dict:
    """
    Tests the async debate_start / debate_result job flow.

    Uses an in-memory _job_store and a stubbed _debate_run_fn so no DB table or
    live model calls are needed — cheap and deterministic on Railway and locally.

    assert="job_start_and_poll"  — debate_id returned, status transitions to "done"
    assert="job_timeout"         — stub that hangs → status transitions to "timeout"
    """
    import app.services.debate_job_service as _job_mod

    inp = case["input"]
    kwargs: dict = inp.get("kwargs", {})
    stub_result: Optional[dict] = inp.get("stub_result")
    stub_hang: bool = inp.get("stub_hang", False)
    job_max_s_override: Optional[float] = inp.get("job_max_s_override")

    # ── Build stubs ────────────────────────────────────────────────────────────
    async def _fast_stub(**kw):
        return stub_result or {}

    async def _hang_stub(**kw):
        await asyncio.sleep(9999)  # hangs until wait_for timeout

    orig_run_fn    = _job_mod._debate_run_fn
    orig_job_store = _job_mod._job_store
    orig_max_s     = _job_mod._JOB_MAX_S

    _job_mod._debate_run_fn = _hang_stub if stub_hang else _fast_stub
    _job_mod._job_store = {}
    if job_max_s_override is not None:
        _job_mod._JOB_MAX_S = float(job_max_s_override)

    try:
        debate_id = await _job_mod.start_job(**kwargs)

        # Let the background task run (stub is instant or hits the tiny timeout)
        sleep_s = max(0.3, (job_max_s_override or 0) + 0.2)
        await asyncio.sleep(sleep_s)

        job = await _job_mod.get_job(debate_id)
        status = job.get("status")

        if case["assert"] == "job_start_and_poll":
            has_id   = bool(debate_id) and isinstance(debate_id, str) and len(debate_id) > 8
            is_done  = status == "done"
            result   = job.get("result") or {}
            has_fa   = bool(result.get("final_answer"))
            has_cost = isinstance(result.get("cost"), dict)
            passed   = has_id and is_done and has_fa and has_cost
            return {
                "passed": passed,
                "details": {
                    "debate_id":       debate_id,
                    "poll_status":     status,
                    "has_final_answer": has_fa,
                    "has_cost_block":   has_cost,
                },
            }

        if case["assert"] == "job_timeout":
            is_timeout = status == "timeout"
            has_error  = bool(job.get("error"))
            passed = is_timeout and has_error
            return {
                "passed": passed,
                "details": {
                    "debate_id":  debate_id,
                    "poll_status": status,
                    "error":       job.get("error"),
                },
            }

        return {"passed": False, "details": {"reason": f"unknown assert: {case['assert']}"}}

    finally:
        _job_mod._debate_run_fn = orig_run_fn
        _job_mod._job_store     = orig_job_store
        _job_mod._JOB_MAX_S     = orig_max_s


async def _run_debate_confirm_gate_case(case: dict) -> dict:
    """
    Tests the confirm-gate directly — no DB, no model call.

    assert="needs_confirmation"  — real decision + confirmed=False → needs_confirmation:true
    assert="confirmed_bypasses"  — confirmed=True → gate returns None (debate proceeds)
    """
    from app.services.debate_job_service import _debate_confirm_gate

    inp = case["input"]
    gate_result = _debate_confirm_gate(
        question=inp["question"],
        rounds=inp.get("rounds", 1),
        verify=inp.get("verify", True),
        confirmed=inp.get("confirmed", False),
        force=inp.get("force", False),
    )

    if case["assert"] == "needs_confirmation":
        passed = (
            gate_result is not None
            and gate_result.get("needs_confirmation") is True
            and not gate_result.get("skipped")
        )
        return {
            "passed": passed,
            "details": {
                "needs_confirmation": (gate_result or {}).get("needs_confirmation"),
                "estimated_cost_usd": (gate_result or {}).get("estimated_cost_usd"),
                "estimated_latency_s": (gate_result or {}).get("estimated_latency_s"),
            },
        }

    if case["assert"] == "confirmed_bypasses":
        passed = gate_result is None
        return {
            "passed": passed,
            "details": {"gate_bypassed": gate_result is None, "gate_result": gate_result},
        }

    return {"passed": False, "details": {"reason": f"unknown assert: {case['assert']}"}}


async def _run_debate_gate_case(case: dict) -> dict:
    """
    Tests the deterministic analysis gate directly — no DB, no model call.

    assert="gate_skipped"  — analysis question blocked, gate returns a skip-dict
    assert="gate_bypassed" — force=True causes gate to return None (debate proceeds)
    """
    from app.services.debate_job_service import _debate_analysis_gate

    inp = case["input"]
    question: str = inp["question"]
    force: bool = inp.get("force", False)

    gate_result = _debate_analysis_gate(question, force)

    if case["assert"] == "gate_skipped":
        passed = gate_result is not None and gate_result.get("skipped") is True
        return {
            "passed": passed,
            "details": {
                "skipped":    gate_result.get("skipped") if gate_result else None,
                "reason":     (gate_result or {}).get("reason"),
                "matched":    (gate_result or {}).get("matched"),
            },
        }

    if case["assert"] == "gate_bypassed":
        passed = gate_result is None
        return {
            "passed": passed,
            "details": {
                "bypassed": gate_result is None,
                "gate_result": gate_result,
            },
        }

    return {"passed": False, "details": {"reason": f"unknown assert: {case['assert']}"}}


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
    "guardrail":           _run_guardrail_case,
    "debate_stubbed":      _run_debate_stubbed_case,
    "debate_job":          _run_debate_job_case,
    "debate_gate":         _run_debate_gate_case,
    "debate_confirm_gate": _run_debate_confirm_gate_case,
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
