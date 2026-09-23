"""
Unit tests for verify_manager.normalize() and quote_supported().

Phase 1 acceptance criteria:
  1.  Hyphen line-break join: "prop-\ner" → "proper"
  2.  NBSP / narrow-NBSP inside numbers: "1 000" == "1 000"
  3.  En-dash → hyphen in a numeric range: "100–200" → "100-200"
  4.  Curly → straight quotes
  5.  Ligature via NFKC: "ﬁne" (ﬁ ligature) → "fine"
  6.  Multi-space collapse → single space
  7.  Fabricated quote NOT present in a short text → quote_supported returns False
  8.  Real verbatim quote IS present → quote_supported returns True
  9.  Quote shorter than 8 chars → quote_supported returns False regardless
"""
import sys
import os

# Make sure imports resolve when run from backend/ or repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.services.verify_manager import normalize, quote_supported


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
