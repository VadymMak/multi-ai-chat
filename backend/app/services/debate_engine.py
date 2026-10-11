"""
Debate Engine v2 — stateless async three-vendor debate.

run_debate(question, context="", rounds=1) → dict

Flow (rounds=1): proposer → critic → assembler
Flow (rounds=2): proposer → critic → rebuttal(proposer) → assembler

ALL LLM calls go off the event loop via asyncio.to_thread(ask_model, ...).
No module-level mutable state.
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

# Rough cost rates (input_per_1m, output_per_1m) in USD
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
    inp_per_1m, out_per_1m = _COST_RATES.get(model_key, (3.0, 15.0))
    tokens_in = out_tokens * 2  # rough input estimate
    return (tokens_in / 1_000_000 * inp_per_1m) + (out_tokens / 1_000_000 * out_per_1m)


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
) -> Tuple[str, float]:
    """
    Run one role call off the event loop.
    Model failures propagate. Span recording is best-effort (never breaks the call).
    Returns (response_text, cost_usd).
    """
    cost = _estimate_cost(model_key, max_tokens)

    async def _do() -> str:
        try:
            return await asyncio.wait_for(
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

    if trace_obj is None:
        return await _do(), cost

    # Best-effort span — if trace import or setup fails, still run the model call
    try:
        from app.services.trace_service import trace_span
    except Exception:
        return await _do(), cost

    try:
        async with trace_span(
            trace_obj, "model", role_name,
            input_summary=f"model={model_key} max_tokens={max_tokens}",
            model_key=model_key,
        ) as span:
            span["cost_usd"] = cost
            text = await _do()
            span["output_summary"] = f"{len(text)} chars"
        return text, cost
    except Exception:
        raise   # model failure OR span exit failure — propagate to caller


# ── Public API ────────────────────────────────────────────────────────────────

async def run_debate(
    question: str,
    context: str = "",
    rounds: int = 1,
) -> Dict[str, Any]:
    """
    Stateless async multi-model debate.

    rounds=1: proposer → critic → assembler
    rounds=2: proposer → critic → proposer-rebuttal → assembler

    Returns the Phase-1 result dict (see mcp_server debate tool for full schema).
    """
    debate_id = str(uuid.uuid4())
    t_start   = time.perf_counter()
    notes: List[str] = []
    total_cost = 0.0

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
            question=question, context=context, rounds=rounds,
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

    # ── PROPOSER ─────────────────────────────────────────────────────────────
    context_block = f"\n\n## Context\n{context}" if context.strip() else ""
    proposer_prompt = DEBATE2_PROPOSER_PROMPT.format(
        question=question, context=context_block,
    )
    try:
        proposer_text, p_cost = await _call_role(
            "proposer", proposer_key, DEBATE2_PREAMBLE,
            proposer_prompt, _CAP_PROPOSER, trace_obj,
        )
        total_cost += p_cost
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
            critic_text, c_cost = await _call_role(
                "critic", critic_key, DEBATE2_PREAMBLE,
                critic_prompt, _CAP_CRITIC, trace_obj,
            )
            total_cost     += c_cost
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
            _, r_cost = await _call_role(
                "rebuttal", proposer_key, DEBATE2_PREAMBLE,
                rebuttal_prompt, _CAP_REBUTTAL, trace_obj,
            )
            total_cost += r_cost
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
            asm_raw, a_cost = await _call_role(
                "assembler", assembler_key, DEBATE2_PREAMBLE,
                assembler_prompt, _CAP_ASSEMBLER, trace_obj,
            )
            total_cost     += a_cost
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

    result.update({
        "roles": {
            "proposer":  {"model": proposer_key,                    "summary": proposer_text[:300]},
            "critic":    {"model": critic_key or "unavailable",     "fatal_flaws_count": critic_flaw_count},
            "assembler": {"model": assembler_key or "unavailable"},
        },
        "debate_id":         debate_id,
        "cost_estimate_usd": round(total_cost, 4),
        "latency_ms":        latency_ms,
    })
    if notes:
        result["notes"] = notes

    return result
