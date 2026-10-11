"""
Lightweight per-request tracer for Brain.

Usage:
    async with trace("query", summary="build_context_for_query: how does X work") as t:
        async with trace_span(t, "context", "smart_context") as span:
            result = await build_smart_context(...)
            span["output_summary"] = result[:200]

        async with trace_span(t, "tool", "hybrid_search") as span:
            hits = hybrid_search(...)

Design:
- Spans are held in memory during the request; ONE batch INSERT at trace close.
- Flush via asyncio.to_thread — never blocks the event loop.
- ALL failures inside tracing are swallowed. Never propagates to the real request.
- Summaries only: input_summary/output_summary truncated to 200 chars.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

_SUMMARY_MAX = 200


def _trunc(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return s[:_SUMMARY_MAX] if len(s) > _SUMMARY_MAX else s


# ─────────────────────────────────────────────────────────────────────────────
# Trace object — carries spans in memory until flush
# ─────────────────────────────────────────────────────────────────────────────

class _Trace:
    def __init__(self, kind: str, summary: str) -> None:
        self.trace_id: str = str(uuid.uuid4())
        self.kind: str = kind
        self.summary: str = summary[:_SUMMARY_MAX] if summary else ""
        self.status: str = "ok"
        self.total_cost_usd: Optional[float] = None
        self.spans: List[Dict[str, Any]] = []
        self._seq: int = 0
        self._t0: float = time.perf_counter()

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)


# ─────────────────────────────────────────────────────────────────────────────
# DB flush — sync, runs in a thread
# ─────────────────────────────────────────────────────────────────────────────

def _flush_sync(trace: _Trace) -> None:
    from app.memory.db import SessionLocal

    db = SessionLocal()
    try:
        total_ms = trace._elapsed_ms()

        # Aggregate cost from spans
        costs = [s["cost_usd"] for s in trace.spans if s.get("cost_usd") is not None]
        total_cost = sum(costs) if costs else None

        db.execute(text("""
            INSERT INTO brain_traces
                (trace_id, kind, summary, status, total_cost_usd, total_ms)
            VALUES
                (:trace_id, :kind, :summary, :status, :total_cost_usd, :total_ms)
        """), {
            "trace_id":      trace.trace_id,
            "kind":          trace.kind,
            "summary":       trace.summary,
            "status":        trace.status,
            "total_cost_usd": total_cost,
            "total_ms":      total_ms,
        })

        for span in trace.spans:
            db.execute(text("""
                INSERT INTO brain_trace_spans
                    (trace_id, seq, layer, name, status,
                     input_summary, output_summary, error,
                     model_key, cost_usd, duration_ms)
                VALUES
                    (:trace_id, :seq, :layer, :name, :status,
                     :input_summary, :output_summary, :error,
                     :model_key, :cost_usd, :duration_ms)
            """), {
                "trace_id":       trace.trace_id,
                "seq":            span["seq"],
                "layer":          span["layer"],
                "name":           span["name"],
                "status":         span["status"],
                "input_summary":  _trunc(span.get("input_summary")),
                "output_summary": _trunc(span.get("output_summary")),
                "error":          span.get("error"),
                "model_key":      span.get("model_key"),
                "cost_usd":       span.get("cost_usd"),
                "duration_ms":    span.get("duration_ms"),
            })

        db.commit()
    except Exception as exc:
        logger.warning("trace flush error (non-fatal): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Public API — context managers
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def trace(
    kind: str,
    summary: str = "",
) -> AsyncGenerator[_Trace, None]:
    """
    Open a trace for one request.  Yields the _Trace object so inner spans
    can attach to it.  Flushes on exit (best-effort, never raises).

    Example:
        async with trace("query", summary=query[:200]) as t:
            async with trace_span(t, "context", "smart_context") as span:
                ...
    """
    t = _Trace(kind=kind, summary=summary)
    try:
        yield t
    except Exception as exc:
        t.status = "error"
        raise
    finally:
        try:
            await asyncio.to_thread(_flush_sync, t)
        except Exception as flush_exc:
            logger.warning("trace flush thread error (non-fatal): %s", flush_exc)


@asynccontextmanager
async def trace_span(
    trace_obj: _Trace,
    layer: str,
    name: str,
    input_summary: Optional[str] = None,
    model_key: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Open a span inside a trace.  Yields a mutable dict so the caller can
    set output_summary, cost_usd, model_key after the work completes.

    Any exception inside is re-raised (the span records status=error first).
    The TRACE status is NOT changed — one failing span does not abort the trace.

    Example:
        async with trace_span(t, "tool", "hybrid_search",
                              input_summary=query[:200]) as span:
            results = await ...
            span["output_summary"] = f"{len(results)} hits"
    """
    seq = trace_obj._next_seq()
    span: Dict[str, Any] = {
        "seq":            seq,
        "layer":          layer,
        "name":           name,
        "status":         "ok",
        "input_summary":  _trunc(input_summary),
        "output_summary": None,
        "error":          None,
        "model_key":      model_key,
        "cost_usd":       None,
        "duration_ms":    None,
    }
    t0 = time.perf_counter()
    try:
        yield span
    except Exception as exc:
        span["status"] = "error"
        span["error"] = str(exc)[:400]
        raise
    finally:
        span["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        trace_obj.spans.append(span)
