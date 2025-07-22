# File: app/services/youtube_http.py
from __future__ import annotations

import os
from urllib.parse import urlencode
from typing import List, Dict, Any, Optional

import requests

# Prefer centralized settings (timeout/max_results) if available
try:
    from app.config.settings import settings
    _DEFAULT_MAX_RESULTS = int(getattr(settings, "YT_SEARCH_MAX_RESULTS", 3))
    _DEFAULT_TIMEOUT = float(getattr(settings, "YT_SEARCH_TIMEOUT", 6.0))
except Exception:  # fallback if settings is unavailable during early imports/tests
    _DEFAULT_MAX_RESULTS = 3
    _DEFAULT_TIMEOUT = 6.0

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

def _clamp_max_results(n: Optional[int]) -> int:
    try:
        v = int(n if n is not None else _DEFAULT_MAX_RESULTS)
    except Exception:
        v = _DEFAULT_MAX_RESULTS
    # YouTube API caps at 50; we keep 25 for faster/light responses
    return max(1, min(v, 25))

def _clean(s: Optional[str]) -> str:
    return (s or "").strip()

def search_youtube(query: str, max_results: int = _DEFAULT_MAX_RESULTS, timeout: float = _DEFAULT_TIMEOUT) -> List[Dict[str, Any]]:
    """
    Lightweight YouTube search via HTTP (no googleapiclient).
    RETURNS (detailed): list of dicts with {title, videoId, url, description}.
    RAISES:
      - EnvironmentError if YOUTUBE_API_KEY is missing
      - requests.HTTPError on non-2xx
      - requests.Timeout / RequestException on network issues
    """
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("Missing YOUTUBE_API_KEY in environment")

    q = _clean(query)
    if not q:
        return []

    params = {
        "part": "snippet",
        "q": q,
        "type": "video",
        "maxResults": _clamp_max_results(max_results),
        "key": YOUTUBE_API_KEY,
        # optional quality hints:
        "order": "relevance",
        "safeSearch": "moderate",
    }

    resp = requests.get(f"{YOUTUBE_SEARCH_URL}?{urlencode(params)}", timeout=float(timeout))
    resp.raise_for_status()
    data = resp.json() or {}

    results: List[Dict[str, Any]] = []
    for item in data.get("items", []):
        vid = (item.get("id") or {}).get("videoId")
        if not vid:
            continue
        snippet = item.get("snippet") or {}
        title = _clean(snippet.get("title"))
        description = _clean(snippet.get("description"))

        results.append({
            "title": title or "Untitled",
            "videoId": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "description": description[:300],
        })

    # Final clamp in case API returned more than requested
    return results[: _clamp_max_results(max_results)]

def safe_youtube_search(query: str, max_results: Optional[int] = None, timeout: Optional[float] = None) -> List[Dict[str, str]]:
    """
    SAFE WRAPPER for chat prompts / prompt builder.
    RETURNS (minimal): list of {title, url} and NEVER raises.
    Falls back to [] if API key is absent or any error occurs.
    """
    try:
        results = search_youtube(
            query=query,
            max_results=_clamp_max_results(max_results),
            timeout=float(timeout if timeout is not None else _DEFAULT_TIMEOUT),
        )
        return [{"title": r.get("title") or "Untitled", "url": r.get("url") or ""} for r in results]
    except Exception:
        return []

__all__ = ["search_youtube", "safe_youtube_search"]
