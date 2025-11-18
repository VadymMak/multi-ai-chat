# File: app/providers/youtube_provide.py
from __future__ import annotations

import os
from typing import List, Dict, Any, Optional

# Prefer the shared HTTP helper (uses googleapiclient if present; else HTTP)
try:
    from app.services.youtube_http import search_youtube as _http_search  # type: ignore
    _HAVE_HTTP_HELPER = True
except Exception:
    _HAVE_HTTP_HELPER = False

# Defaults from settings when available
try:
    from app.config.settings import settings  # type: ignore
    _DEFAULT_MAX_RESULTS = int(getattr(settings, "YT_SEARCH_MAX_RESULTS", 3))
    _DEFAULT_TIMEOUT = float(getattr(settings, "YT_SEARCH_TIMEOUT", 6.0))
    _SETTINGS_OK = True
except Exception:
    _DEFAULT_MAX_RESULTS = 3
    _DEFAULT_TIMEOUT = 6.0
    _SETTINGS_OK = False

_YT_DEBUG = (os.getenv("YOUTUBE_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on"}

# Prefer settings; fallback to env (only needed for inline fallback path)
_YT_API_KEY = (
    (getattr(settings, "YOUTUBE_API_KEY", None) if _SETTINGS_OK else None)
    or os.getenv("YOUTUBE_API_KEY")
)

# Region / safe-search (support both env spellings)
_YT_REGION = (
    (os.getenv("YOUTUBE_REGION_CODE") or os.getenv("YOUTUBE_REGION") or "").strip() or None
)
_YT_SAFE_SEARCH = (
    (os.getenv("YOUTUBE_SAFESEARCH") or os.getenv("YOUTUBE_SAFE_SEARCH") or "moderate")
    .strip()
    .lower()
    or "moderate"
)
if _YT_SAFE_SEARCH not in {"none", "moderate", "strict"}:
    _YT_SAFE_SEARCH = "moderate"


def _clean(s: Optional[str]) -> str:
    return (s or "").strip()


def _clamp(n: Optional[int]) -> int:
    try:
        v = int(n if n is not None else _DEFAULT_MAX_RESULTS)
    except Exception:
        v = _DEFAULT_MAX_RESULTS
    return max(1, min(v, 25))


# Minimal inline HTTP search (used only if app.services.youtube_http is missing)
def _inline_http_search(query: str, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
    if not _YT_API_KEY:
        raise EnvironmentError("Missing YOUTUBE_API_KEY in environment/settings")

    q = _clean(query)
    if not q:
        return []

    from urllib.parse import urlencode  # local import to avoid overhead if unused
    import requests

    safe = _YT_SAFE_SEARCH  # normalize once

    params = {
        "part": "snippet",
        "q": q,
        "type": "video",
        "maxResults": _clamp(max_results),
        "key": _YT_API_KEY,
        "order": "relevance",
        "safeSearch": safe,  # none|moderate|strict
    }
    if _YT_REGION:
        params["regionCode"] = _YT_REGION

    url = f"https://www.googleapis.com/youtube/v3/search?{urlencode(params)}"
    if _YT_DEBUG:
        print(f"[YouTubeProvider] HTTP GET → {url}")

    resp = requests.get(url, timeout=_DEFAULT_TIMEOUT)
    resp.raise_for_status()
    data = resp.json() or {}

    out: List[Dict[str, Any]] = []
    for item in data.get("items", []):
        vid = ((item.get("id") or {}).get("videoId") or "").strip()
        if not vid:
            continue
        snip = item.get("snippet") or {}
        title = _clean(snip.get("title")) or "Untitled"
        desc = _clean(snip.get("description"))
        out.append(
            {
                "title": title,
                "videoId": vid,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "description": (desc[:300] if desc else ""),
            }
        )
    return out[: _clamp(max_results)]


def search_youtube(query: str, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Provider entrypoint used across the app.

    Returns a list of dicts:
      { "title": str, "videoId": str, "url": str, "description": str }

    - Uses app.services.youtube_http when available; otherwise a tiny inline HTTP fallback.
    - Deduplicates by URL.
    - Returns [] on error or empty query.
    """
    q = _clean(query)
    if not q:
        return []

    mr = _clamp(max_results)
    if _YT_DEBUG:
        print(f"[YouTubeProvider] query='{q}' max_results={mr} helper={_HAVE_HTTP_HELPER}")

    try:
        if _HAVE_HTTP_HELPER:
            raw = _http_search(query=q, max_results=mr)  # type: ignore[arg-type]
        else:
            raw = _inline_http_search(query=q, max_results=mr)
    except Exception as e:
        if _YT_DEBUG:
            print(f"[YouTubeProvider] search error: {e}")
        return []

    # Normalize + dedupe
    seen = set()
    out: List[Dict[str, Any]] = []
    for item in raw or []:
        title = _clean(item.get("title")) or "Untitled"
        vid = _clean(item.get("videoId"))
        url = _clean(item.get("url")) or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
        if not url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "title": title,
                "videoId": vid,
                "url": url,
                "description": _clean(item.get("description"))[:300] if item.get("description") else "",
            }
        )

    if _YT_DEBUG:
        print(f"[YouTubeProvider] results={len(out)}")
    return out


__all__ = ["search_youtube"]
