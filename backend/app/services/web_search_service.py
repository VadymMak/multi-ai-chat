# app/services/web_search_service.py
import os
import re
from typing import List, Dict

# Defer wikipedia import so missing lib doesn't kill the app at import-time
try:
    import wikipedia  # type: ignore
    _HAVE_WIKIPEDIA = True
except Exception:
    wikipedia = None  # type: ignore
    _HAVE_WIKIPEDIA = False


def _clean_query(query: str, max_length: int = 180) -> str:
    """Remove special chars and trim."""
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
        print(f"[Web] No matching domain keywords. Fallback to cleaned: '{fallback}'")
    else:
        print(f"[Web] Fallback keyword query: '{fallback}'")
    return fallback


def _search_wikipedia_titles(q: str, max_results: int) -> List[str]:
    """Small wrapper to guard against missing library and common errors."""
    if not _HAVE_WIKIPEDIA or wikipedia is None:
        print("[Web] wikipedia library not installed; skipping API calls.")
        return []
    try:
        # Optional language override
        lang = os.getenv("WIKIPEDIA_LANG", "en").strip() or "en"
        try:
            wikipedia.set_lang(lang)  # type: ignore[attr-defined]
        except Exception:
            pass
        return wikipedia.search(q, results=max_results) or []
    except Exception as e:
        print(f"[Web] wikipedia.search error: {e}")
        return []


def _get_page_info(title: str) -> Dict[str, str]:
    """
    Fetch a single page’s title/url/summary with defensive error handling.
    """
    if not _HAVE_WIKIPEDIA or wikipedia is None:
        return {}
    try:
        # Try faster: summary first, then page for URL if needed
        try:
            summary = wikipedia.summary(title, sentences=3)  # type: ignore[attr-defined]
        except Exception:
            summary = ""
        try:
            page = wikipedia.page(title, auto_suggest=False)  # type: ignore[attr-defined]
            url = page.url
            real_title = page.title
        except Exception:
            # Fallback URL (search link) if page failed
            url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
            real_title = title
        snippet = (summary or "").strip()
        if snippet:
            snippet = (snippet[:300] + "...") if len(snippet) > 300 else snippet
        else:
            snippet = "Wikipedia article preview unavailable."
        return {"title": real_title, "url": url, "snippet": snippet}
    except Exception as e:
        print(f"[Web] wikipedia.page error for '{title}': {e}")
        return {}


def perform_web_search(query: str, max_results: int = 3) -> List[dict]:
    """
    Performs a Wikipedia-backed web search and returns up to `max_results`
    relevant page summaries. Includes layered fallbacks and stable shape.

    Returns: List[{"title": str, "url": str, "snippet": str}]
    """
    try:
        cleaned_query = _clean_query(query)
        print(f"[Web] Cleaned query: '{cleaned_query}'")

        titles = _search_wikipedia_titles(cleaned_query, max_results)
        search_query = cleaned_query

        # Fallback #1: keyword-based
        if not titles:
            fallback_query = _extract_keywords_fallback(query)
            titles = _search_wikipedia_titles(fallback_query, max_results)
            search_query = fallback_query

        # Fallback #2: strip voltage like "220V"
        if not titles and re.search(r"\b\d+V\b", query or "", flags=re.IGNORECASE):
            stripped = re.sub(r"\b\d+V\b", "", query or "", flags=re.IGNORECASE).strip()
            print(f"[Web] Retrying stripped query: '{stripped}'")
            titles = _search_wikipedia_titles(_clean_query(stripped), max_results)
            search_query = stripped

        results: List[Dict[str, str]] = []
        for t in titles:
            info = _get_page_info(t)
            if info:
                results.append(info)
            if len(results) >= max_results:
                break

        # Final fallback: give a Google search link
        if not results:
            print("[Web] No readable pages found. Returning fallback search link.")
            q = _clean_query(search_query or query or "technology")
            return [{
                "title": "No relevant web articles found",
                "snippet": "Try searching this query manually:",
                "url": f"https://www.google.com/search?q={q.replace(' ', '+')}",
            }]

        return results

    except Exception as e:
        print(f"[Web] Unexpected web search error: {e} | Query: {query}")
        return [{
            "title": "Web search error",
            "url": "https://en.wikipedia.org/",
            "snippet": "An error occurred during the web search. Try again later or search manually.",
        }]
