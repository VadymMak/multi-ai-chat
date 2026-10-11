"""
Debate Engine v2 — stateless async three-vendor debate.

run_debate(question, context="", rounds=1, verify=True,
           project_id=None, folder_identifier=None, use_context=True) → dict

Flow (rounds=1): proposer → critic → assembler
Flow (rounds=2): proposer → critic → rebuttal(proposer) → assembler

ALL LLM calls go off the event loop via asyncio.to_thread(ask_model_with_usage, ...).
No module-level mutable state.

Phase 3 additions:
- Accurate per-call cost from real token counts (ask_model_with_usage).
- "cost" block in result: {total_usd, by_role, tokens, latency_ms}.
- Cost-smart context: build ONE proposer-only context from smart_context,
  capped at _DEBATE_CONTEXT_CHAR_CAP chars. Critic / assembler never receive it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.providers.factory import ask_model
from app.config.settings import settings
from app.config.debate_prompts import (
    DEBATE2_PREAMBLE,
    DEBATE2_PROPOSER_PROMPT,
    DEBATE2_CRITIC_PROMPT,
    DEBATE2_ASSEMBLER_PROMPT,
    DEBATE2_REBUTTAL_PROMPT,
)

logger = logging.getLogger(__name__)

# ── Module-level aliases (patchable by evals) ────────────────────────────────

# Module-level alias so evals can monkeypatch without touching verify_manager.
try:
    from app.services.verify_manager import run_verify as _debate_verify
except Exception:  # pragma: no cover
    _debate_verify = None  # type: ignore

# Usage-tracked caller — evals may replace with a stub.
try:
    from app.providers.factory import ask_model_with_usage as _ask_with_usage_fn
except Exception:  # pragma: no cover
    _ask_with_usage_fn = None  # type: ignore


# ── Role seat fallback chains (first available wins) ─────────────────────────
_PROPOSER_CHAIN  = ["claude-sonnet-4.5", "gpt-4o", "grok-3"]
_CRITIC_CHAIN    = ["grok-3", "claude-sonnet-4.5", "gpt-4o"]
_ASSEMBLER_CHAIN = ["gpt-4o", "claude-sonnet-4.5", "grok-3"]

# Token caps per role
_CAP_PROPOSER  = 2500
_CAP_CRITIC    = 2000
_CAP_ASSEMBLER = 1500
_CAP_REBUTTAL  = 600

# Per-role wall-clock timeout (seconds)
_ROLE_TIMEOUT = 60.0

# Cap on claims sent to verify_manager per debate (cost/latency guard)
_MAX_VERIFY_CLAIMS = 5

# Smart context hard cap (~3000 tokens)
_DEBATE_CONTEXT_CHAR_CAP = 12_000

# Per-model pricing (input_per_1M_USD, output_per_1M_USD)
_COST_RATES: Dict[str, Tuple[float, float]] = {
    "claude-sonnet-4.5":        (3.0, 15.0),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "gpt-4o":                   (2.5, 10.0),
    "gpt-4o-mini":              (0.15, 0.6),
    "grok-3":                   (3.0, 15.0),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_seat(chain: List[str]) -> Tuple[str, bool]:
    """
    Return (model_key, is_fallback).
    Skips grok if GROK_API_KEY is not set.
    Raises RuntimeError if no seat can be filled.
    """
    from app.config.model_registry import MODEL_REGISTRY
    grok_ok = bool(getattr(settings, "GROK_API_KEY", ""))
    for i, key in enumerate(chain):
        info = MODEL_REGISTRY.get(key)
        if not info:
            continue
        if info.get("provider") == "xai" and not grok_ok:
            continue
        return key, (i > 0)
    raise RuntimeError(f"No model available for chain {chain}")


def _estimate_cost(model_key: str, out_tokens: int) -> float:
    """Rough projection — used ONLY for circuit-breaker check before calls."""
    inp_per_1m, out_per_1m = _COST_RATES.get(model_key, (3.0, 15.0))
    tokens_in = out_tokens * 2
    return (tokens_in / 1_000_000 * inp_per_1m) + (out_tokens / 1_000_000 * out_per_1m)


def _compute_cost(model_key: str, input_tokens: int, output_tokens: int) -> float:
    """Accurate cost from real token counts."""
    inp_per_1m, out_per_1m = _COST_RATES.get(model_key, (3.0, 15.0))
    return (input_tokens / 1_000_000 * inp_per_1m) + (output_tokens / 1_000_000 * out_per_1m)


def _count_flaws(critic_text: str) -> int:
    """Count numbered items (1. / 1) style) as a proxy for fatal-flaw count."""
    if not critic_text.strip():
        return 0
    return max(1, len(re.findall(r"^\s*\d+[\.\)]\s", critic_text, re.MULTILINE)))


def _parse_assembler(raw: str) -> Dict[str, Any]:
    """Extract and parse the assembler's JSON output, tolerating markdown fences."""
    text = re.sub(r"```(?:json)?\s*", "", raw)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    try:
        return json.loads(text)
    except Exception:
        return {
            "final_answer":             raw[:2000],
            "confidence":               None,
            "unresolved_disagreements": [],
            "key_risks_still_present":  [],
            "what_survived":            [],
            "what_was_dropped_or_fixed": [],
            "_parse_error":             "assembler output was not valid JSON",
        }


async def _call_role(
    role_name: str,
    model_key: str,
    system: str,
    prompt: str,
    max_tokens: int,
    trace_obj: Any = None,
) -> Tuple[str, float, int, int]:
    """
    Run one role call off the event loop.
    Returns (response_text, cost_usd, input_tokens, output_tokens).
    Uses ask_model_with_usage for accurate token counts.
    Falls back to ask_model + estimate if _ask_with_usage_fn is unavailable.
    """
    _afn = _ask_with_usage_fn  # read module attr for eval monkeypatching

    async def _do() -> Tuple[str, int, int]:
        if _afn is not None:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(
                        _afn,
                        [{"role": "user", "content": prompt}],
                        model_key=model_key,
                        system_prompt=system,
                        max_tokens=max_tokens,
                    ),
                    timeout=_ROLE_TIMEOUT,
                )
            except (asyncio.TimeoutError, TimeoutError) as te:
                raise RuntimeError(f"timeout after {_ROLE_TIMEOUT}s") from te
        # Fallback: no usage data (shouldn't happen in prod)
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(
                    ask_model,
                    [{"role": "user", "content": prompt}],
                    model_key=model_key,
                    system_prompt=system,
                    max_tokens=max_tokens,
                ),
                timeout=_ROLE_TIMEOUT,
            )
        except (asyncio.TimeoutError, TimeoutError) as te:
            raise RuntimeError(f"timeout after {_ROLE_TIMEOUT}s") from te
        est_in = max_tokens * 2
        est_out = max(1, len(text) // 4)
        return text, est_in, est_out

    if trace_obj is None:
        text, in_toks, out_toks = await _do()
        cost = _compute_cost(model_key, in_toks, out_toks)
        return text, cost, in_toks, out_toks

    # Best-effort span — if trace import or setup fails, still run the model call
    try:
        from app.services.trace_service import trace_span
    except Exception:
        text, in_toks, out_toks = await _do()
        cost = _compute_cost(model_key, in_toks, out_toks)
        return text, cost, in_toks, out_toks

    try:
        async with trace_span(
            trace_obj, "model", role_name,
            input_summary=f"model={model_key} max_tokens={max_tokens}",
            model_key=model_key,
        ) as span:
            text, in_toks, out_toks = await _do()
            cost = _compute_cost(model_key, in_toks, out_toks)
            span["cost_usd"] = cost
            span["output_summary"] = f"{len(text)} chars"
        return text, cost, in_toks, out_toks
    except Exception:
        raise   # model failure OR span exit failure — propagate to caller


# ── Verify annotation ────────────────────────────────────────────────────────

async def _annotate_with_verify(
    final_answer: str,
    trace_obj: Any,
    current_confidence: Optional[int],
    notes: List[str],
    unresolved: List[str],
) -> Tuple[Dict[str, Any], Optional[int], List[str], List[str]]:
    """
    Best-effort verify annotation. Never raises — returns unchanged inputs on error.
    Returns (verified_claims_block, adjusted_confidence, updated_notes, updated_unresolved).
    """
    _vfn = _debate_verify  # read module attr so evals can monkeypatch
    if _vfn is None:
        return {"error": "verify_manager unavailable"}, current_confidence, notes, unresolved

    empty_block: Dict[str, Any] = {"checked": 0, "verified": 0, "refuted_or_unverified": 0}
    try:
        report = await asyncio.to_thread(
            _vfn, final_answer, _MAX_VERIFY_CLAIMS, True, False,
        )
    except Exception as exc:
        logger.debug("debate verify annotation failed (non-fatal): %s", exc)
        return {**empty_block, "error": str(exc)}, current_confidence, notes, unresolved

    # Record a best-effort verify span
    if trace_obj is not None:
        try:
            from app.services.trace_service import trace_span
            stats = report.get("stats", {})
            async with trace_span(
                trace_obj, "verify", "verify_annotation",
                input_summary=f"max_claims={_MAX_VERIFY_CLAIMS}",
            ) as span:
                span["output_summary"] = (
                    f"checked={stats.get('claims_total', 0)} "
                    f"refuted={stats.get('refuted', 0)} "
                    f"unchecked={stats.get('unchecked', 0)}"
                )
        except Exception:
            pass

    stats = report.get("stats", {})
    refuted_count   = len(report.get("refuted", []))
    unchecked_list  = report.get("unchecked", [])
    unverified_count = sum(
        1 for c in unchecked_list
        if c.get("source") and c.get("reason") not in ("no_source_given",)
    )
    bad_count = refuted_count + unverified_count

    block: Dict[str, Any] = {
        "checked":              stats.get("claims_total", 0),
        "verified":             stats.get("verified", 0),
        "refuted_or_unverified": bad_count,
    }

    new_conf = current_confidence
    new_notes = list(notes)
    new_unresolved = list(unresolved)

    if bad_count > 0:
        if new_conf is not None:
            new_conf = max(0, new_conf - 15 * bad_count)
        new_notes.append(f"verify_penalty:{bad_count}_claims")
        for c in report.get("refuted", []):
            new_unresolved.append(f"[verify-refuted] {c.get('claim','')[:120]}")
        for c in unchecked_list:
            if c.get("source") and c.get("reason") not in ("no_source_given",):
                new_unresolved.append(f"[verify-unconfirmed] {c.get('claim','')[:120]}")

    return block, new_conf, new_notes, new_unresolved


# ── Smart context (proposer-only, opt-in) ────────────────────────────────────

async def _build_debate_context_async(
    question: str,
    project_id: Optional[int],
    folder_identifier: Optional[str],
) -> str:
    """
    Build compressed smart context for the PROPOSER ONLY.
    Caps at _DEBATE_CONTEXT_CHAR_CAP chars (~3000 tokens).
    Best-effort — never raises.
    """
    from app.memory.db import SessionLocal
    from app.memory.manager import MemoryManager
    from app.services.smart_context import build_smart_context as _bsc
    from sqlalchemy import text as _text

    db = SessionLocal()
    try:
        pid = project_id
        if pid is None and folder_identifier:
            row = db.execute(
                _text("SELECT id FROM projects WHERE folder_identifier = :fi LIMIT 1"),
                {"fi": folder_identifier},
            ).fetchone()
            if row:
                pid = int(row[0])

        if pid is None:
            return ""

        memory = MemoryManager(db)
        ctx = await _bsc(
            project_id=pid,
            role_id=0,
            query=question,
            session_id="",
            db=db,
            memory=memory,
        )
        if len(ctx) > _DEBATE_CONTEXT_CHAR_CAP:
            ctx = ctx[:_DEBATE_CONTEXT_CHAR_CAP] + "\n...[context trimmed]"
        return ctx
    except Exception as exc:
        logger.debug("debate smart_context build failed (non-fatal): %s", exc)
        return ""
    finally:
        db.close()


# Module-level alias so evals can monkeypatch with a stub async coroutine.
_debate_smart_context_fn = _build_debate_context_async


# ── Public API ────────────────────────────────────────────────────────────────

async def run_debate(
    question: str,
    context: str = "",
    rounds: int = 1,
    verify: bool = True,
    project_id: Optional[int] = None,
    folder_identifier: Optional[str] = None,
    use_context: bool = True,
) -> Dict[str, Any]:
    """
    Stateless async multi-model debate.

    rounds=1: proposer → critic → assembler
    rounds=2: proposer → critic → proposer-rebuttal → assembler

    verify=True (default): after the assembler, run_verify annotates the
    final_answer with checkable claims. Refuted/unverified claims lower
    confidence by 15 each (floor 0) and appear in unresolved_disagreements.

    project_id / folder_identifier + use_context=True: build ONE compressed
    context from smart_context and inject it into the PROPOSER ONLY.
    Critic and assembler never receive it (cost-smart design).
    """
    debate_id = str(uuid.uuid4())
    t_start   = time.perf_counter()
    notes: List[str] = []
    total_cost = 0.0

    # ── smart context (proposer-only, opt-in) ────────────────────────────────
    if not context.strip() and use_context and (project_id is not None or folder_identifier):
        _ctx_fn = _debate_smart_context_fn  # read module attr for eval patching
        if _ctx_fn is not None:
            try:
                built_ctx = await _ctx_fn(question, project_id, folder_identifier)
                if built_ctx:
                    context = built_ctx
                    notes.append(f"smart_context:{len(built_ctx)}chars")
            except Exception as exc:
                logger.debug("debate context build outer error (non-fatal): %s", exc)

    # ── seat resolution ───────────────────────────────────────────────────────
    try:
        proposer_key, prop_fb = _resolve_seat(_PROPOSER_CHAIN)
        if prop_fb:
            notes.append(f"proposer_fallback:{proposer_key}")
    except RuntimeError as exc:
        return {
            "error": f"proposer_unavailable: {exc}",
            "debate_id": debate_id,
            "cost_estimate_usd": 0.0,
            "latency_ms": int((time.perf_counter() - t_start) * 1000),
        }

    critic_key: Optional[str] = None
    try:
        critic_key, crit_fb = _resolve_seat(_CRITIC_CHAIN)
        if crit_fb:
            notes.append(f"critic_fallback:{critic_key}")
    except RuntimeError:
        notes.append("grok_unavailable")

    assembler_key: Optional[str] = None
    try:
        assembler_key, asm_fb = _resolve_seat(_ASSEMBLER_CHAIN)
        if asm_fb:
            notes.append(f"assembler_fallback:{assembler_key}")
    except RuntimeError:
        pass  # assembler_failed handled below

    # ── cost circuit-breaker ──────────────────────────────────────────────────
    max_usd = float(getattr(settings, "DEBATE_MAX_USD", 0.40))
    projected = (
        _estimate_cost(proposer_key, _CAP_PROPOSER)
        + (_estimate_cost(critic_key, _CAP_CRITIC) if critic_key else 0)
        + (_estimate_cost(proposer_key, _CAP_REBUTTAL) if rounds >= 2 and critic_key else 0)
        + _estimate_cost(assembler_key or proposer_key, _CAP_ASSEMBLER)
    )
    if projected > max_usd:
        fallback_answer = await asyncio.to_thread(
            ask_model,
            [{"role": "user", "content": question}],
            model_key=proposer_key,
            system_prompt="Answer the question directly and thoroughly.",
            max_tokens=2000,
        )
        return {
            "final_answer":       fallback_answer,
            "confidence":         None,
            "cost_capped":        True,
            "projected_cost_usd": round(projected, 4),
            "cost_limit_usd":     max_usd,
            "notes":              ["cost_capped"],
            "debate_id":          debate_id,
            "cost_estimate_usd":  round(_estimate_cost(proposer_key, 2000), 4),
            "latency_ms":         int((time.perf_counter() - t_start) * 1000),
        }

    # ── open trace (best-effort) ──────────────────────────────────────────────
    _trace_obj  = None
    _trace_cm   = None
    try:
        from app.services.trace_service import trace as _trace_fn
        _trace_cm  = _trace_fn("debate", summary=question[:200])
        _trace_obj = await _trace_cm.__aenter__()
    except Exception as exc:
        logger.debug("debate trace open failed (non-fatal): %s", exc)
        _trace_cm  = None
        _trace_obj = None

    try:
        result = await _run_rounds(
            question=question, context=context, rounds=rounds, verify=verify,
            proposer_key=proposer_key, critic_key=critic_key, assembler_key=assembler_key,
            debate_id=debate_id, t_start=t_start, notes=notes, total_cost=total_cost,
            trace_obj=_trace_obj,
        )
    finally:
        if _trace_cm is not None:
            try:
                await _trace_cm.__aexit__(None, None, None)
            except Exception:
                pass

    return result


async def _run_rounds(
    *,
    question: str,
    context: str,
    rounds: int,
    verify: bool,
    proposer_key: str,
    critic_key: Optional[str],
    assembler_key: Optional[str],
    debate_id: str,
    t_start: float,
    notes: List[str],
    total_cost: float,
    trace_obj: Any,
) -> Dict[str, Any]:
    """Inner logic — separated so the trace context manager wraps it cleanly."""

    # Per-role cost and token tracking
    role_costs: Dict[str, float] = {}
    role_tokens: Dict[str, Tuple[int, int]] = {}  # role → (in_toks, out_toks)

    # ── PROPOSER ─────────────────────────────────────────────────────────────
    context_block = f"\n\n## Context\n{context}" if context.strip() else ""
    proposer_prompt = DEBATE2_PROPOSER_PROMPT.format(
        question=question, context=context_block,
    )
    try:
        proposer_text, p_cost, p_in, p_out = await _call_role(
            "proposer", proposer_key, DEBATE2_PREAMBLE,
            proposer_prompt, _CAP_PROPOSER, trace_obj,
        )
        total_cost += p_cost
        role_costs["proposer_usd"] = p_cost
        role_tokens["proposer"] = (p_in, p_out)
    except Exception as exc:
        return {
            "error": f"proposer_failed: {exc}",
            "debate_id": debate_id,
            "cost_estimate_usd": round(total_cost, 4),
            "latency_ms": int((time.perf_counter() - t_start) * 1000),
        }

    # ── CRITIC ────────────────────────────────────────────────────────────────
    critic_text      = ""
    critic_flaw_count = 0
    confidence_penalty = 0

    if critic_key:
        critic_prompt = DEBATE2_CRITIC_PROMPT.format(
            question=question, proposal=proposer_text,
        )
        try:
            critic_text, c_cost, c_in, c_out = await _call_role(
                "critic", critic_key, DEBATE2_PREAMBLE,
                critic_prompt, _CAP_CRITIC, trace_obj,
            )
            total_cost     += c_cost
            role_costs["critic_usd"] = c_cost
            role_tokens["critic"] = (c_in, c_out)
            critic_flaw_count = _count_flaws(critic_text)
        except Exception as exc:
            logger.warning("debate critic failed (degraded): %s", exc)
            notes.append("critic_unavailable")
            confidence_penalty = -20
    else:
        confidence_penalty = -20

    # ── REBUTTAL (rounds ≥ 2) ────────────────────────────────────────────────
    if rounds >= 2 and critic_text:
        rebuttal_prompt = DEBATE2_REBUTTAL_PROMPT.format(
            question=question, proposal=proposer_text, critique=critic_text,
        )
        try:
            _, r_cost, r_in, r_out = await _call_role(
                "rebuttal", proposer_key, DEBATE2_PREAMBLE,
                rebuttal_prompt, _CAP_REBUTTAL, trace_obj,
            )
            total_cost += r_cost
            role_costs["rebuttal_usd"] = r_cost
        except Exception as exc:
            logger.warning("debate rebuttal failed (non-fatal): %s", exc)
            notes.append("rebuttal_failed")

    # ── ASSEMBLER ─────────────────────────────────────────────────────────────
    assembler_failed = False
    assembler_parsed: Dict[str, Any] = {}

    if assembler_key:
        assembler_prompt = DEBATE2_ASSEMBLER_PROMPT.format(
            question=question,
            proposal=proposer_text,
            critique=critic_text or "(critic unavailable)",
            rebuttal="(no rebuttal)",
            confidence_penalty=confidence_penalty,
        )
        try:
            asm_raw, a_cost, a_in, a_out = await _call_role(
                "assembler", assembler_key, DEBATE2_PREAMBLE,
                assembler_prompt, _CAP_ASSEMBLER, trace_obj,
            )
            total_cost     += a_cost
            role_costs["assembler_usd"] = a_cost
            role_tokens["assembler"] = (a_in, a_out)
            assembler_parsed = _parse_assembler(asm_raw)
        except Exception as exc:
            logger.warning("debate assembler failed: %s", exc)
            assembler_failed = True
            notes.append("assembler_failed")
    else:
        assembler_failed = True
        notes.append("assembler_unavailable")

    latency_ms = int((time.perf_counter() - t_start) * 1000)

    # ── BUILD RESULT ─────────────────────────────────────────────────────────
    if assembler_failed:
        result: Dict[str, Any] = {
            "final_answer":             proposer_text,
            "confidence":               None,
            "assembler_failed":         True,
            "raw_proposal":             proposer_text,
            "raw_critique":             critic_text,
            "unresolved_disagreements": [],
            "key_risks_still_present":  [],
            "what_survived":            [],
            "what_was_dropped_or_fixed": [],
        }
    else:
        raw_conf = assembler_parsed.get("confidence")
        adjusted = (int(raw_conf) + confidence_penalty) if raw_conf is not None else None
        result = {
            "final_answer":             assembler_parsed.get("final_answer", proposer_text),
            "confidence":               max(0, min(100, adjusted)) if adjusted is not None else None,
            "unresolved_disagreements": assembler_parsed.get("unresolved_disagreements", []),
            "key_risks_still_present":  assembler_parsed.get("key_risks_still_present",  []),
            "what_survived":            assembler_parsed.get("what_survived",            []),
            "what_was_dropped_or_fixed": assembler_parsed.get("what_was_dropped_or_fixed", []),
        }

    # ── VERIFY ANNOTATION (best-effort, never breaks result) ─────────────────
    verified_claims_block: Optional[Dict[str, Any]] = None
    if verify and result.get("final_answer"):
        try:
            vc_block, new_conf, notes, new_unresolved = await _annotate_with_verify(
                final_answer=result["final_answer"],
                trace_obj=trace_obj,
                current_confidence=result.get("confidence"),
                notes=notes,
                unresolved=list(result.get("unresolved_disagreements", [])),
            )
            verified_claims_block = vc_block
            result["confidence"] = new_conf
            result["unresolved_disagreements"] = new_unresolved
        except Exception as exc:
            logger.debug("verify annotation outer error (non-fatal): %s", exc)

    # ── COST BLOCK ────────────────────────────────────────────────────────────
    p_tok = role_tokens.get("proposer", (0, 0))
    c_tok = role_tokens.get("critic",   (0, 0))
    a_tok = role_tokens.get("assembler",(0, 0))
    cost_block: Dict[str, Any] = {
        "total_usd": round(total_cost, 6),
        "by_role": {
            "proposer_usd":  round(role_costs.get("proposer_usd",  0.0), 6),
            "critic_usd":    round(role_costs.get("critic_usd",    0.0), 6),
            "assembler_usd": round(role_costs.get("assembler_usd", 0.0), 6),
            "verify_usd":    0.0,
        },
        "tokens": {
            "proposer_in":   p_tok[0], "proposer_out":   p_tok[1],
            "critic_in":     c_tok[0], "critic_out":     c_tok[1],
            "assembler_in":  a_tok[0], "assembler_out":  a_tok[1],
        },
        "latency_ms": latency_ms,
    }

    result.update({
        "roles": {
            "proposer":  {"model": proposer_key,                    "summary": proposer_text[:300]},
            "critic":    {"model": critic_key or "unavailable",     "fatal_flaws_count": critic_flaw_count},
            "assembler": {"model": assembler_key or "unavailable"},
        },
        "debate_id":         debate_id,
        "cost":              cost_block,
        "cost_estimate_usd": round(total_cost, 4),  # kept for backward compat
        "latency_ms":        latency_ms,
    })
    if verified_claims_block is not None:
        result["verified_claims"] = verified_claims_block
    if notes:
        result["notes"] = notes

    return result
