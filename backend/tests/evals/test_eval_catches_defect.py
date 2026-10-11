"""
Defect-injection meta-test (spec section 6 / 7 "первый милстоун").

Proves that the eval harness measures a REAL regression, not a trivial pass.
Strategy:
  1. Monkeypatch the quote_supported function to a no-op (always returns True).
     This simulates a broken quote gate that can never refute a fabricated claim.
  2. Run verify_refuted case — it MUST FAIL (RED).
  3. Restore via a second setattr call within the same test.
  4. Run verify_refuted again — it MUST PASS (GREEN).

No committed defect. monkeypatch auto-reverts after test teardown anyway.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import asyncio
import pytest

import app.services.verify_manager as _vm


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _eval_case_passes(case_name: str) -> bool:
    """
    Run one eval case by name and return whether it passes.

    Calls quote_supported (or resolve_source) directly from verify_manager —
    the monkeypatch on _vm propagates because the eval_runner does a lazy import
    of verify_manager each call.
    """
    from app.config.eval_cases import EVAL_CASES

    case = next(c for c in EVAL_CASES if c["name"] == case_name)

    if case["kind"] == "quote_supported":
        # Import inside function so we always get the current module attribute
        from app.services.verify_manager import quote_supported
        inp = case["input"]
        result = quote_supported(inp["quote"], inp["document"])
        expected_true = (case["assert"] == "is_true")
        return result == expected_true

    if case["kind"] == "resolve_source":
        from app.services.verify_manager import _resolve_source
        inp = case["input"]
        result = _resolve_source(inp["source"])
        if case["assert"] == "is_none":
            return result is None
        if case["assert"] == "url_contains":
            url = (result or {}).get("url", "")
            return result is not None and case.get("expected_url_fragment", "") in url

    raise ValueError(f"Unsupported case kind for defect test: {case['kind']}")


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestQuoteGateDefectInjection:
    """
    Red→green proof: the verify_refuted eval detects a broken quote gate.
    """

    def test_baseline_verify_refuted_passes(self):
        """Baseline: verify_refuted passes with the real quote_supported."""
        assert _eval_case_passes("verify_refuted"), (
            "BASELINE FAIL — verify_refuted should pass without any defect injected. "
            "Check that quote_supported('guaranteed impression pool of 300-500…', doc) "
            "returns False."
        )

    def test_baseline_verify_verified_passes(self):
        """Baseline: verify_verified passes with the real quote_supported."""
        assert _eval_case_passes("verify_verified"), (
            "BASELINE FAIL — verify_verified should pass without any defect injected."
        )

    def test_defect_makes_verify_refuted_fail(self, monkeypatch):
        """
        With a no-op quote gate (always True), verify_refuted MUST FAIL.
        A broken gate that cannot say 'not found' would silently verify fabricated claims.
        The eval harness must catch this.
        """
        # Inject defect: quote_supported always returns True (gate never fires)
        monkeypatch.setattr(_vm, "quote_supported", lambda q, d: True)

        assert not _eval_case_passes("verify_refuted"), (
            "DEFECT NOT DETECTED — verify_refuted should FAIL when quote_supported "
            "is a no-op. The eval harness is not measuring the real gate."
        )

    def test_defect_does_not_break_verify_verified(self, monkeypatch):
        """
        verify_verified STILL passes under the always-True defect.
        This confirms the defect is directional — it breaks only the refuted case.
        """
        monkeypatch.setattr(_vm, "quote_supported", lambda q, d: True)

        assert _eval_case_passes("verify_verified"), (
            "verify_verified should still pass when quote_supported always returns True."
        )

    def test_red_green_cycle_within_one_test(self, monkeypatch):
        """
        Complete red→green proof in a single test:
          1. Inject defect → eval RED
          2. Restore       → eval GREEN
        """
        real_quote_supported = _vm.quote_supported

        # ── RED phase ────────────────────────────────────────────────
        monkeypatch.setattr(_vm, "quote_supported", lambda q, d: True)
        assert not _eval_case_passes("verify_refuted"), (
            "RED: eval must FAIL with broken quote gate"
        )

        # ── Restore within test (monkeypatch.undo() is unavailable;
        #    we use a second setattr to the saved real function) ──────
        monkeypatch.setattr(_vm, "quote_supported", real_quote_supported)

        # ── GREEN phase ──────────────────────────────────────────────
        assert _eval_case_passes("verify_refuted"), (
            "GREEN: eval must PASS after quote gate is restored"
        )


class TestResolveSourceDefectInjection:
    """
    Red→green proof: verify_unchecked_source eval detects a broken source resolver.
    """

    def test_baseline_unchecked_passes(self):
        """Baseline: verify_unchecked_source passes normally."""
        assert _eval_case_passes("verify_unchecked_source"), (
            "BASELINE FAIL — _resolve_source('Attention Is All You Need') should be None."
        )

    def test_defect_makes_unchecked_fail(self, monkeypatch):
        """
        If _resolve_source always returns a fake URL (broken resolver),
        verify_unchecked_source must FAIL — the 'unresolvable' path is gone.
        """
        monkeypatch.setattr(_vm, "_resolve_source", lambda s: {"url": "https://fake.url", "origin": "stated"})

        assert not _eval_case_passes("verify_unchecked_source"), (
            "DEFECT NOT DETECTED — verify_unchecked_source should FAIL when "
            "_resolve_source never returns None."
        )
