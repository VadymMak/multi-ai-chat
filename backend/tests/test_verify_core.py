"""
Unit tests for verify_manager: normalize(), quote_supported(), _resolve_source().

Phase 1 acceptance criteria (normalize / quote_supported):
  1.  Hyphen line-break join: "prop-\ner" → "proper"
  2.  NBSP / narrow-NBSP inside numbers: "1 000" == "1 000"
  3.  En-dash → hyphen in a numeric range: "100–200" → "100-200"
  4.  Curly → straight quotes
  5.  Ligature via NFKC: "ﬁne" (ﬁ ligature) → "fine"
  6.  Multi-space collapse → single space
  7.  Fabricated quote NOT present in a short text → quote_supported returns False
  8.  Real verbatim quote IS present → quote_supported returns True
  9.  Quote shorter than 8 chars → quote_supported returns False regardless

Phase 2 acceptance criteria (_resolve_source):
  10. Bare arXiv id "2209.07663" → ar5iv URL
  11. Prefixed "arXiv:2209.07663" → ar5iv URL
  12. DOI "10.1145/3600100.3600101" → doi.org URL
  13. Plain https URL → used as-is, origin "stated"
  14. Bare paper title → None (unresolvable)
"""
import sys
import os

# Make sure imports resolve when run from backend/ or repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock

import pytest
from app.services.verify_manager import (
    normalize,
    quote_supported,
    _resolve_source,
    _fetch_text,
    _find_quote,
    _verify_sourced_claim,
)


# ─────────────────────────────────────────────────────────────────
# normalize() tests
# ─────────────────────────────────────────────────────────────────

def test_hyphen_line_break_join():
    # PDF line-wrap artefact: "prop-\ner" should merge to "proper"
    assert normalize("prop-\ner") == "proper"


def test_nbsp_inside_number():
    # Non-breaking space (U+00A0) and narrow no-break space (U+202F)
    # should collapse to a regular space like any other whitespace
    assert normalize("1 000") == "1 000"
    assert normalize("1 000") == "1 000"


def test_en_dash_to_hyphen():
    # En-dash in a range should normalise to hyphen
    assert normalize("100–200") == "100-200"


def test_curly_to_straight_quotes():
    assert normalize("“hello”") == '"hello"'
    assert normalize("‘world’") == "'world'"


def test_nfkc_ligature():
    # U+FB01 LATIN SMALL LIGATURE FI → "fi" via NFKC
    assert normalize("ﬁne") == "fine"


def test_multi_space_collapse():
    assert normalize("one   two\t\tthree") == "one two three"


# ─────────────────────────────────────────────────────────────────
# quote_supported() tests
# ─────────────────────────────────────────────────────────────────

_DOCUMENT = (
    "Monolith uses a collisionless embedding table to support online learning "
    "with real-time updates, allowing the recommendation system to adapt rapidly "
    "to changing user preferences without batch retraining."
)


def test_fabricated_quote_not_supported():
    # Gemini's fabricated claim — guaranteed impression pool — is NOT in the doc
    fabricated = "guaranteed impression pool of 300-500 via a multi-armed bandit"
    assert quote_supported(fabricated, _DOCUMENT) is False


def test_real_quote_supported():
    # A verbatim excerpt from _DOCUMENT
    real_quote = "collisionless embedding table to support online learning"
    assert quote_supported(real_quote, _DOCUMENT) is True


def test_short_quote_rejected():
    # Even a string that IS present in the document is rejected when < 8 chars
    assert quote_supported("table", _DOCUMENT) is False
    assert quote_supported("", _DOCUMENT) is False
    assert quote_supported(None, _DOCUMENT) is False


# ─────────────────────────────────────────────────────────────────
# _resolve_source() tests (Phase 2)
# ─────────────────────────────────────────────────────────────────

def test_resolve_arxiv_bare_id():
    r = _resolve_source("2209.07663")
    assert r is not None
    assert r["url"] == "https://ar5iv.org/abs/2209.07663"
    assert r["origin"] == "stated"


def test_resolve_arxiv_prefixed():
    r = _resolve_source("arXiv:2209.07663")
    assert r is not None
    assert r["url"] == "https://ar5iv.org/abs/2209.07663"
    assert r["origin"] == "stated"


def test_resolve_doi():
    r = _resolve_source("10.1145/3600100.3600101")
    assert r is not None
    assert r["url"] == "https://doi.org/10.1145/3600100.3600101"
    assert r["origin"] == "stated"


def test_resolve_plain_url():
    url = "https://example.com/paper.html"
    r = _resolve_source(url)
    assert r is not None
    assert r["url"] == url
    assert r["origin"] == "stated"


def test_resolve_title_is_none():
    # Bare paper title cannot be resolved deterministically → None
    assert _resolve_source("Attention Is All You Need") is None
    assert _resolve_source("") is None
    assert _resolve_source(None) is None


# ─────────────────────────────────────────────────────────────────
# _fetch_text() + _verify_sourced_claim() tests — MOCKED (Phase 3)
# All httpx calls are intercepted; no network access.
# ─────────────────────────────────────────────────────────────────

_MODULE = "app.services.verify_manager"

_SAMPLE_HTML = b"<html><body><p>Monolith uses a collisionless embedding table.</p></body></html>"
_SAMPLE_TEXT = "Monolith uses a collisionless embedding table."


def _mock_resp(status: int = 200, content: bytes = _SAMPLE_HTML,
               content_type: str = "text/html", encoding: str = "utf-8") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    resp.headers = {"content-type": content_type}
    resp.encoding = encoding
    return resp


def _patch_client(mock_resp_obj: MagicMock):
    """Return a patch for httpx.Client that yields mock_resp_obj on .get()."""
    client_cm = MagicMock()
    client_cm.__enter__ = MagicMock(return_value=client_cm)
    client_cm.__exit__ = MagicMock(return_value=False)
    client_cm.get = MagicMock(return_value=mock_resp_obj)
    return patch(f"{_MODULE}.httpx.Client", return_value=client_cm)


# 15 — Successful fetch: resolve + fetch + quote gate (Phase 4 active)
# Model says not_found → refuted (gate ran; no hallucination to catch here).
def test_fetch_success_path():
    with _patch_client(_mock_resp(200, _SAMPLE_HTML)):
        with patch("app.services.verify_manager.ask_model",
                   return_value='{"verdict": "not_found", "quote": ""}'):
            result = _verify_sourced_claim("some claim", "2209.07663")
    assert result["bucket"] == "refuted"
    assert result["reason"] == "not_found_in_text"


# 16 — http_404
def test_fetch_failure_404():
    with _patch_client(_mock_resp(404)):
        r = _fetch_text("https://example.com/missing")
    assert r == {"ok": False, "reason": "http_404"}


# 17 — timeout (both attempts)
def test_fetch_failure_timeout():
    import httpx as _httpx
    with patch(f"{_MODULE}.httpx.Client") as mock_cls:
        inst = MagicMock()
        inst.__enter__ = MagicMock(return_value=inst)
        inst.__exit__ = MagicMock(return_value=False)
        inst.get = MagicMock(side_effect=_httpx.TimeoutException("timed out"))
        mock_cls.return_value = inst
        r = _fetch_text("https://example.com/slow")
    assert r == {"ok": False, "reason": "timeout"}


# 18 — paywall (HTTP 402)
def test_fetch_failure_paywall():
    with _patch_client(_mock_resp(402)):
        r = _fetch_text("https://journal.com/article")
    assert r == {"ok": False, "reason": "paywall"}


# 19 — robots_denied (HTTP 403)
def test_fetch_failure_robots_denied():
    with _patch_client(_mock_resp(403)):
        r = _fetch_text("https://example.com/forbidden")
    assert r == {"ok": False, "reason": "robots_denied"}


# 20 — pdf_unparseable (PDF content-type but fitz fails)
def test_fetch_failure_pdf_unparseable():
    with _patch_client(_mock_resp(200, b"%PDF-garbage", "application/pdf")):
        with patch(f"{_MODULE}._extract_pdf_text", return_value=None):
            r = _fetch_text("https://example.com/paper.pdf")
    assert r == {"ok": False, "reason": "pdf_unparseable"}


# 21 — fetch_error (unexpected non-200)
def test_fetch_failure_generic_error():
    with _patch_client(_mock_resp(500)):
        r = _fetch_text("https://example.com/broken")
    assert r == {"ok": False, "reason": "fetch_error"}


# 22 — source_unresolvable propagates through _verify_sourced_claim
def test_verify_sourced_claim_unresolvable():
    result = _verify_sourced_claim("some claim", "Attention Is All You Need")
    assert result["bucket"] == "unchecked"
    assert result["reason"] == "source_unresolvable"
    assert not result.get("_is_fetch_failure")


# ═════════════════════════════════════════════════════════════════
# Phase 4 — ACCEPTANCE TESTS (mocked-document, fully offline)
# ═════════════════════════════════════════════════════════════════
#
# Stub document: contains a sentence about collisionless embedding table
# (matching the true-positive claim) but does NOT mention any impression pool
# (so the fabricated claim cannot pass the gate).
_MONOLITH_STUB = (
    "Monolith employs a collisionless embedding table that avoids hash collision "
    "through a dedicated hashtable per feature. "
    "This design enables online training with real-time data, allowing the model "
    "to continuously adapt to user preferences without batch retraining. "
    "The system processes streaming click events and updates parameters in place."
)
# A real verbatim substring of _MONOLITH_STUB for the true-positive test.
_REAL_QUOTE = "collisionless embedding table that avoids hash collision through a dedicated hashtable per feature"


def _patch_fetch_stub():
    """Patch _fetch_text to return _MONOLITH_STUB without hitting the network."""
    return patch(
        "app.services.verify_manager._fetch_text",
        return_value={"ok": True, "text": _MONOLITH_STUB},
    )


# ─── Acceptance test 1 — TRUE NEGATIVE (mocked) ───────────────────────────
# The fabricated claim is NOT in the stub.
# Scenario A: model honestly returns not_found.
def test_acceptance_true_negative_model_honest():
    fabricated_claim = (
        "ByteDance Monolith documents a guaranteed impression pool of 300-500 "
        "via a multi-armed bandit algorithm"
    )
    mock_model_response = '{"verdict": "not_found", "quote": ""}'
    with _patch_fetch_stub():
        with patch("app.services.verify_manager.ask_model", return_value=mock_model_response):
            result = _verify_sourced_claim(fabricated_claim, "2209.07663")
    assert result["bucket"] == "refuted", f"Expected refuted, got {result}"
    assert result.get("reason") == "not_found_in_text"


# Scenario B: model HALLUCINATES a quote — the gate must catch it.
def test_acceptance_true_negative_gate_catches_hallucination():
    fabricated_claim = (
        "ByteDance Monolith documents a guaranteed impression pool of 300-500 "
        "via a multi-armed bandit algorithm"
    )
    # Model invents a quote that looks plausible but is not in _MONOLITH_STUB.
    hallucinated_response = (
        '{"verdict": "supported", "quote": "guaranteed impression pool of 300-500 '
        'via a multi-armed bandit"}'
    )
    with _patch_fetch_stub():
        with patch("app.services.verify_manager.ask_model", return_value=hallucinated_response):
            result = _verify_sourced_claim(fabricated_claim, "2209.07663")
    # Gate must block — the hallucinated quote is NOT in _MONOLITH_STUB.
    assert result["bucket"] == "refuted", (
        f"GATE FAILED: model hallucinated a quote and it was NOT caught. result={result}"
    )
    assert result.get("reason") == "not_found_in_text"


# ─── Acceptance test 2 — TRUE POSITIVE (mocked) ───────────────────────────
# The real quote IS in the stub; model returns it verbatim; gate passes.
def test_acceptance_true_positive():
    real_claim = "Monolith uses a collisionless embedding table to avoid hash collisions"
    model_response = f'{{"verdict": "supported", "quote": "{_REAL_QUOTE}"}}'
    with _patch_fetch_stub():
        with patch("app.services.verify_manager.ask_model", return_value=model_response):
            result = _verify_sourced_claim(real_claim, "2209.07663")
    assert result["bucket"] == "verified", f"Expected verified, got {result}"
    assert result.get("quote") == _REAL_QUOTE
    assert result.get("source_origin") == "stated"


# ─── Acceptance test 3 — HONEST REFUSAL ───────────────────────────────────
# A claim with no stated source must land in unchecked/no_source_given.
# This goes through the orchestrator directly (no mocking needed).
def test_acceptance_honest_refusal_no_source():
    from app.services.verify_manager import run_verify
    # run_verify calls extract_claims which calls ask_model. Mock it to return
    # a single fact claim with no source.
    claims_response = '[{"claim": "The sky is green.", "source": null, "type": "fact"}]'
    with patch("app.services.verify_manager.ask_model", return_value=claims_response):
        report = run_verify("The sky is green.", fetch=True)
    assert len(report["unchecked"]) == 1
    item = report["unchecked"][0]
    assert item["reason"] == "no_source_given"
    assert item["source"] is None
    assert len(report["verified"]) == 0
    assert len(report["refuted"]) == 0


# ─── _find_quote unit tests ────────────────────────────────────────────────
def test_find_quote_gate_blocks_fabricated_quote():
    doc = "The system uses vector embeddings for efficient retrieval."
    # Model returns a quote NOT present in the doc → gate blocks it.
    bad_resp = '{"verdict": "supported", "quote": "guaranteed impression pool of 300-500"}'
    with patch("app.services.verify_manager.ask_model", return_value=bad_resp):
        result = _find_quote("some claim", doc)
    assert result is None


def test_find_quote_passes_real_quote():
    doc = "The system uses vector embeddings for efficient retrieval."
    real_quote = "vector embeddings for efficient retrieval"
    good_resp = f'{{"verdict": "supported", "quote": "{real_quote}"}}'
    with patch("app.services.verify_manager.ask_model", return_value=good_resp):
        result = _find_quote("claim about retrieval", doc)
    assert result == real_quote


def test_find_quote_not_found_returns_none():
    doc = "The system uses vector embeddings for efficient retrieval."
    resp = '{"verdict": "not_found", "quote": ""}'
    with patch("app.services.verify_manager.ask_model", return_value=resp):
        result = _find_quote("claim about impression pool", doc)
    assert result is None


# ═════════════════════════════════════════════════════════════════
# Phase 5 — HIGH ASSURANCE tests (dual-model cross-check, fully mocked)
# ═════════════════════════════════════════════════════════════════

from app.services.verify_manager import VERIFY_EXTRACT_MODEL, VERIFY_SECOND_MODEL


def _make_ask_model_side_effect(model_responses: dict):
    """Return a side_effect function that returns different responses per model_key."""
    def side_effect(messages, model_key, system_prompt=None, temperature=0.0, max_tokens=500):
        return model_responses.get(model_key, '{"verdict": "not_found", "quote": ""}')
    return side_effect


# HA-1: both models return the same real quote → verified + assurance="both_models_agree"
def test_high_assurance_both_agree():
    with _patch_fetch_stub():
        with patch("app.services.verify_manager.ask_model",
                   side_effect=_make_ask_model_side_effect({
                       VERIFY_EXTRACT_MODEL: f'{{"verdict": "supported", "quote": "{_REAL_QUOTE}"}}',
                       VERIFY_SECOND_MODEL:  f'{{"verdict": "supported", "quote": "{_REAL_QUOTE}"}}',
                   })):
            result = _verify_sourced_claim(
                "Monolith uses a collisionless embedding table", "2209.07663",
                high_assurance=True,
            )
    assert result["bucket"] == "verified", f"Expected verified, got {result}"
    assert result["assurance"] == "both_models_agree"
    assert _REAL_QUOTE in result["quote"]


# HA-2: model A finds gated quote, model B says not_found → unchecked/models_disagree
def test_high_assurance_disagree():
    with _patch_fetch_stub():
        with patch("app.services.verify_manager.ask_model",
                   side_effect=_make_ask_model_side_effect({
                       VERIFY_EXTRACT_MODEL: f'{{"verdict": "supported", "quote": "{_REAL_QUOTE}"}}',
                       VERIFY_SECOND_MODEL:  '{"verdict": "not_found", "quote": ""}',
                   })):
            result = _verify_sourced_claim(
                "Monolith uses a collisionless embedding table", "2209.07663",
                high_assurance=True,
            )
    assert result["bucket"] == "unchecked", f"Expected unchecked, got {result}"
    assert result["reason"] == "models_disagree"
    assert result["quote_a"] == _REAL_QUOTE    # model A found it
    assert result["quote_b"] is None           # model B did not


# HA-3: both models say not_found → refuted
def test_high_assurance_both_not_found():
    with _patch_fetch_stub():
        with patch("app.services.verify_manager.ask_model",
                   return_value='{"verdict": "not_found", "quote": ""}'):
            result = _verify_sourced_claim(
                "Monolith uses a collisionless embedding table", "2209.07663",
                high_assurance=True,
            )
    assert result["bucket"] == "refuted", f"Expected refuted, got {result}"
    assert result["reason"] == "not_found_in_text"


# HA-4: high_assurance=False regression — single model, existing behavior unchanged
def test_high_assurance_false_unchanged():
    with _patch_fetch_stub():
        with patch("app.services.verify_manager.ask_model",
                   return_value=f'{{"verdict": "supported", "quote": "{_REAL_QUOTE}"}}'):
            result = _verify_sourced_claim(
                "Monolith uses a collisionless embedding table", "2209.07663",
                high_assurance=False,
            )
    assert result["bucket"] == "verified", f"Expected verified, got {result}"
    assert "assurance" not in result          # no assurance key in standard mode
    assert result["quote"] == _REAL_QUOTE


# ─── Optional live integration tests ──────────────────────────────────────
# Skipped unless OPENAI_API_KEY is set and --integration flag is passed.
_HAS_API_KEY = bool(os.getenv("OPENAI_API_KEY"))

@pytest.mark.skipif(not _HAS_API_KEY, reason="OPENAI_API_KEY not configured")
def test_integration_true_negative_live():
    """Live: fetch ar5iv 2209.07663 + real model → must refute fabricated claim."""
    result = _verify_sourced_claim(
        "ByteDance Monolith documents a guaranteed impression pool of 300-500 "
        "via a multi-armed bandit algorithm",
        "2209.07663",
    )
    assert result["bucket"] == "refuted", f"Expected refuted, got {result}"


@pytest.mark.skipif(not _HAS_API_KEY, reason="OPENAI_API_KEY not configured")
def test_integration_true_positive_live():
    """Live: fetch ar5iv 2209.07663 + real model → must verify collisionless claim."""
    result = _verify_sourced_claim(
        "Monolith uses a collisionless embedding table to support online training",
        "2209.07663",
    )
    assert result["bucket"] == "verified", f"Expected verified, got {result}"
    assert result.get("quote"), "Expected a non-empty verbatim quote"
