# tests/test_web_search_service.py
"""
Unit tests for perform_web_search in app.services.web_search_service
"""

import pytest
from app.services.web_search_service import perform_web_search


def test_clean_query_returns_results():
    """Should return results for a normal query with clean content."""
    query = "responsive accessibility pitfalls"
    results = perform_web_search(query)

    assert isinstance(results, list)
    assert len(results) > 0
    assert "title" in results[0]
    assert "url" in results[0]
    assert "snippet" in results[0]


def test_keyword_fallback_logic():
    """Should return results using domain keyword fallback."""
    query = "modeling exponential population growth"  # triggers domain keywords
    results = perform_web_search(query)

    assert isinstance(results, list)
    assert len(results) > 0


def test_numeric_voltage_strip_fallback():
    """Should still work even with numeric + technical terms."""
    query = "how 220V contactor works"
    results = perform_web_search(query)

    assert isinstance(results, list)
    assert len(results) > 0


def test_total_failure_returns_fallback_link():
    """Should return fallback Wikipedia search link when no match found."""
    query = "qwertyuioplkjhgfdsazxcvbnm"  # unlikely to match anything
    results = perform_web_search(query)

    assert isinstance(results, list)
    assert len(results) == 1
    assert "wikipedia.org" in results[0]["url"]
    assert "No specific Wikipedia results" in results[0]["title"]
