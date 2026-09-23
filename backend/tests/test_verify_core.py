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


# 15 — Successful fetch: resolve + fetch success → quote_check_not_implemented
def test_fetch_success_path():
    with _patch_client(_mock_resp(200, _SAMPLE_HTML)):
        result = _verify_sourced_claim("some claim", "2209.07663")
    assert result["bucket"] == "unchecked"
    assert result["reason"] == "quote_check_not_implemented"
    assert "_fetched_text" in result
    assert "collisionless" in result["_fetched_text"]


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
