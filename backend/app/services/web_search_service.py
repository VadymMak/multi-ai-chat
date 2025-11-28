from __future__ import annotations

import os
import re
from typing import List, Dict, Optional

# Optional centralized defaults (fall back if settings isn't ready yet)
try:
    from app.config.settings import settings
    _DEFAULT_MAX_RESULTS = int(getattr(settings, "WEB_SEARCH_MAX_RESULTS", 3))
except Exception:
    _DEFAULT_MAX_RESULTS = 3

# Feature flag + debug
_ENABLED = (os.getenv("WEB_SEARCH_ENABLED") or "1").strip().lower() not in {"0", "false", "no", "off"}
_DEBUG = (os.getenv("WEB_SEARCH_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on"}

def _log(msg: str) -> None:
    if _DEBUG:
        print(f"[Web] {msg}")

# Defer wikipedia import so missing lib doesn't kill import-time
try:
    import wikipedia  # type: ignore
    _HAVE_WIKIPEDIA = True
except Exception:
    wikipedia = None  # type: ignore
    _HAVE_WIKIPEDIA = False


def _clamp_max_results(n: Optional[int]) -> int:
    try:
        v = int(n if n is not None else _DEFAULT_MAX_RESULTS)
    except Exception:
        v = _DEFAULT_MAX_RESULTS
    return max(1, min(v, 10))  # keep small for speed


def _clean_query(query: str, max_length: int = 180) -> str:
    """Remove special chars, compress whitespace, and trim length."""
    query = (query or "").strip()
    query = re.sub(r"[^a-zA-Z0-9\s]", " ", query)
    query = re.sub(r"\s+", " ", query)
    return query[:max_length]


def _extract_keywords_fallback(query: str) -> str:
    """
    Fallback keyword extraction. If no keywords match, return cleaned query.
    """
    domain_terms = {
        "logarithm", "log", "ln", "base", "e", "math", "mathematics",
        "function", "exponent", "natural", "definition", "properties",
        "compound", "interest", "population", "modeling", "growth", "calculus",
        "physics", "finance", "derivative", "integral", "science", "biology",
        "rate", "decay", "frontend", "accessibility", "design", "web",
        "contactor", "motor", "electrical", "relay", "voltage",
        "ai", "gpu", "nvidia", "model", "architecture", "comparison", "transformer",
        "language", "openai", "claude", "chatbot", "multimodal"
    }
    words = (query or "").lower().split()
    keywords = [w for w in words if w in domain_terms]
    fallback = " ".join(keywords[:6])
    if not fallback:
        fallback = _clean_query(query, max_length=80)
        _log(f"No matching domain keywords. Fallback to cleaned: '{fallback}'")
    else:
        _log(f"Keyword fallback query: '{fallback}'")
    return fallback


def _search_wikipedia_titles(q: str, max_results: int) -> List[str]:
    """Small wrapper to guard against missing library and common errors."""
    if not _HAVE_WIKIPEDIA or wikipedia is None:
        _log("wikipedia library not installed; skipping API calls.")
        return []
    try:
        # Optional language override
        lang = (os.getenv("WIKIPEDIA_LANG") or "en").strip() or "en"
        try:
            wikipedia.set_lang(lang)  # type: ignore[attr-defined]
        except Exception:
            pass
        return wikipedia.search(q, results=max_results) or []  # type: ignore[attr-defined]
    except Exception as e:
        _log(f"wikipedia.search error: {e}")
        return []


def _get_page_info(title: str) -> Dict[str, str]:
    """
    Fetch a single page's title/url/summary with defensive error handling.
    Returns {} on failure.
    """
    if not _HAVE_WIKIPEDIA or wikipedia is None:
        return {}
    try:
        # Try summary first (fast), then page() for URL and canonical title.
        try:
            summary = wikipedia.summary(title, sentences=3)  # type: ignore[attr-defined]
        except Exception:
            summary = ""

        try:
            page = wikipedia.page(title, auto_suggest=False)  # type: ignore[attr-defined]
            url = getattr(page, "url", f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}")
            real_title = getattr(page, "title", title)
        except Exception:
            # Fallback URL if page fetch failed
            url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
            real_title = title

        snippet = (summary or "").strip()
        if snippet:
            snippet = (snippet[:300] + "...") if len(snippet) > 300 else snippet
        else:
            snippet = "Wikipedia article preview unavailable."

        return {"title": str(real_title), "url": str(url), "snippet": str(snippet)}
    except Exception as e:
        _log(f"wikipedia.page error for '{title}': {e}")
        return {}


def perform_web_search(query: str, max_results: int = _DEFAULT_MAX_RESULTS) -> List[Dict[str, str]]:
    """
    Performs a Wikipedia-backed web search and returns up to `max_results`
    relevant page summaries. Includes layered fallbacks and stable shape.

    Returns: List[{"title": str, "url": str, "snippet": str}]
    """
    try:
        if not _ENABLED:
            _log("WEB_SEARCH_ENABLED=0 — returning empty result.")
            return []

        k = _clamp_max_results(max_results)
        cleaned_query = _clean_query(query)
        if not cleaned_query:
            _log("Empty query after cleaning — returning empty result.")
            return []

        _log(f"Cleaned query: '{cleaned_query}' (max_results={k})")

        titles = _search_wikipedia_titles(cleaned_query, k)
        search_query = cleaned_query

        # Fallback #1: keyword-based
        if not titles:
            fallback_query = _extract_keywords_fallback(query)
            titles = _search_wikipedia_titles(fallback_query, k)
            search_query = fallback_query

        # Fallback #2: strip voltage like "220V"
        if not titles and re.search(r"\b\d+V\b", query or "", flags=re.IGNORECASE):
            stripped = re.sub(r"\b\d+V\b", "", query or "", flags=re.IGNORECASE).strip()
            _log(f"Retrying stripped query: '{stripped}'")
            titles = _search_wikipedia_titles(_clean_query(stripped), k)
            search_query = stripped

        # Build results with dedupe
        results: List[Dict[str, str]] = []
        seen_urls = set()
        for t in titles:
            info = _get_page_info(t)
            if not info:
                continue
            url = info.get("url", "").strip().lower()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(info)
            if len(results) >= k:
                break

        # Final fallback: give a Google search link
        if not results:
            _log("No readable pages found. Returning fallback search link.")
            q = _clean_query(search_query or query or "technology")
            return [{
                "title": "No relevant web articles found",
                "snippet": "Try searching this query manually:",
                "url": f"https://www.google.com/search?q={q.replace(' ', '+')}",
            }]

        return results

    except Exception as e:
        _log(f"Unexpected web search error: {e} | Query: {query}")
        return [{
            "title": "Web search error",
            "url": "https://en.wikipedia.org/",
            "snippet": "An error occurred during the web search. Try again later or search manually.",
        }]


# ==================== GOOGLE CUSTOM SEARCH ====================

def perform_google_search(
    query: str, 
    max_results: int = _DEFAULT_MAX_RESULTS
) -> List[Dict[str, str]]:
    """
    Use Google Custom Search API (100 free queries/day)
    
    Environment variables:
    - GOOGLE_API_KEY: Your Google API key
    - GOOGLE_CSE_ID: Your Custom Search Engine ID
    """
    # ✅ FIXED: Use correct environment variable names
    api_key = os.getenv('GOOGLE_API_KEY', '').strip()
    cx = os.getenv('GOOGLE_CSE_ID', '').strip()
    
    if not api_key or not cx:
        print(f"[Google Search] Not configured: api_key={bool(api_key)}, cx={bool(cx)}")
        _log("Google Search API not configured, using Wikipedia fallback")
        return perform_web_search(query, max_results)
    
    try:
        import requests
        
        url = 'https://www.googleapis.com/customsearch/v1'
        params = {
            'key': api_key,
            'cx': cx,
            'q': query,
            'num': min(max_results, 10)  # Max 10 per request
        }
        
        print(f"[Google Search] Searching: '{query}' (max={max_results})")
        
        response = requests.get(url, params=params, timeout=10)
        
        # Log response status
        print(f"[Google Search] Response status: {response.status_code}")
        
        if response.status_code != 200:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get('error', {}).get('message', response.text[:200])
            print(f"[Google Search] Error: {error_msg}")
            return perform_web_search(query, max_results)
        
        data = response.json()
        items = data.get('items', [])
        
        results = []
        for item in items:
            results.append({
                'title': item.get('title', 'Untitled'),
                'url': item.get('link', ''),
                'snippet': item.get('snippet', '')[:300]
            })
        
        print(f"[Google Search] ✅ Returned {len(results)} results")
        
        # If no results from Google, fallback to Wikipedia
        if not results:
            print(f"[Google Search] No results, falling back to Wikipedia")
            return perform_web_search(query, max_results)
        
        return results
        
    except Exception as e:
        print(f"[Google Search] ❌ Failed: {e}, falling back to Wikipedia")
        return perform_web_search(query, max_results)


def perform_web_search_enhanced(
    query: str, 
    max_results: int = _DEFAULT_MAX_RESULTS
) -> List[Dict[str, str]]:
    """
    Try Google Search first, fallback to Wikipedia.
    
    This is the recommended entry point when Google Search is configured.
    """
    api_key = os.getenv('GOOGLE_API_KEY', '').strip()
    
    if api_key:
        return perform_google_search(query, max_results)
    else:
        return perform_web_search(query, max_results)


__all__ = ["perform_web_search", "perform_google_search", "perform_web_search_enhanced"]