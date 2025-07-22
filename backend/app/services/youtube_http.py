# app/services/youtube_http.py
from __future__ import annotations

import os
import json
import re
from typing import Tuple, List, Dict, Optional, Union, Any

import requests  # used by both HTTP paths and the new helpers

# -------------------- optional deps --------------------
try:
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.errors import HttpError  # type: ignore
    _HAVE_GOOGLE_API = True
except Exception:
    build = None  # type: ignore
    HttpError = Exception  # type: ignore
    _HAVE_GOOGLE_API = False

# -------------------- settings & flags --------------------
try:
    from app.config.settings import settings  # type: ignore
    _DEFAULT_MAX_RESULTS = int(getattr(settings, "YT_SEARCH_MAX_RESULTS", 3))
    _DEFAULT_TIMEOUT = float(getattr(settings, "YT_SEARCH_TIMEOUT", 6.0))
    _SAFESEARCH_ENV = getattr(settings, "YOUTUBE_SAFESEARCH", "moderate")
    _REGION_CODE = getattr(settings, "YOUTUBE_REGION_CODE", "") or ""
    _GLOBAL_DEBUG = bool(getattr(settings, "YOUTUBE_DEBUG", False))
except Exception:
    _DEFAULT_MAX_RESULTS = 3
    _DEFAULT_TIMEOUT = 6.0
    _SAFESEARCH_ENV = "moderate"
    _REGION_CODE = ""
    _GLOBAL_DEBUG = False

_YT_DEBUG = _GLOBAL_DEBUG or ((os.getenv("YOUTUBE_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on"})
_SAFESEARCH = (_SAFESEARCH_ENV or "moderate").strip().lower()  # none|moderate|strict

def _dbg(enabled: bool, *args: Any) -> None:
    if enabled or _YT_DEBUG:
        print(*args)

# Order normalization (accept both lower/camel env values)
_ORDER_RAW = (os.getenv("YOUTUBE_ORDER") or getattr(settings, "YOUTUBE_ORDER", "relevance")).strip()
_ORDER_LOWER = _ORDER_RAW.lower()
if _ORDER_LOWER not in {"relevance", "date", "rating", "title", "videocount", "viewcount"}:
    _YT_API_ORDER = "relevance"
else:
    if _ORDER_LOWER == "videocount":
        _YT_API_ORDER = "videoCount"
    elif _ORDER_LOWER == "viewcount":
        _YT_API_ORDER = "viewCount"
    else:
        _YT_API_ORDER = _ORDER_LOWER

_PIPED_DISABLE = (os.getenv("PIPED_DISABLE") or "").strip().lower() in {"1", "true", "yes"}

# Primary + optional fallbacks (env PIPED_HOSTS can override the list)
_env_hosts = [h.strip() for h in (os.getenv("PIPED_HOSTS") or "").split(",") if h.strip()]
_PIPED_HOSTS = _env_hosts or [
    os.getenv("PIPED_PRIMARY", "piped.video").strip() or "piped.video",
    "pipedapi.kavin.rocks",
    "piped.mha.fi",
    "piped.tokhmi.xyz",
    "yapi.vyper.me",
    "piped.privacy.com.de",
]

# Boost channels (env allows override/extend); used only for scoring Piped results.
_default_allow = ["react conf", "vercel", "jack herrington", "theo", "t3", "t3.gg"]
_YT_ALLOWLIST = [s.strip().lower() for s in (os.getenv("YOUTUBE_CHANNEL_ALLOWLIST") or "").split(",") if s.strip()] or _default_allow

from app.memory.manager import MemoryManager

# -------------------- small helpers --------------------
def _clean(s: Optional[str]) -> str:
    return (s or "").strip()

def _clamp_max(n: Optional[int]) -> int:
    try:
        v = int(n if n is not None else _DEFAULT_MAX_RESULTS)
    except Exception:
        v = _DEFAULT_MAX_RESULTS
    return max(1, min(v, 25))

def _extract_keywords(text: str, max_length: int = 120) -> str:
    """Clean text and return a space-separated keyword string."""
    text = (text or "").strip()
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
    words = text.split()
    stop = {"the", "and", "for", "with", "a", "an", "in", "to", "of", "by", "on"}
    keywords = [w for w in words if len(w) > 2 and w.lower() not in stop]
    return " ".join(keywords[:max_length]).strip()

def _current_year() -> str:
    try:
        import datetime as _dt
        return str(_dt.datetime.utcnow().year)
    except Exception:
        return "2025"

def _build_search_query(original: str) -> str:
    """
    Heuristics: keep it generic but helpful for tech/education queries.
    We bias toward tutorial/explainer and recent content.
    """
    cleaned = _extract_keywords(original.lower())
    if not cleaned:
        return "tutorial explainer 2025"

    year = _current_year()
    base = f"{cleaned} explained tutorial {year}"
    if "react" in cleaned or "next" in cleaned or "server components" in cleaned or "rsc" in cleaned:
        return f"{cleaned} react server components {year}"
    return base

# -------------------- YouTube video id parsing --------------------
_YT_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")

def _extract_video_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    if "watch?v=" in url:      # watch?v=XXXXXXXXXXX
        return url.split("watch?v=", 1)[1][:11]
    if "youtu.be/" in url:     # youtu.be/XXXXXXXXXXX
        return url.split("youtu.be/", 1)[1][:11]
    if "/shorts/" in url:      # shorts/XXXXXXXXXXX
        return url.split("/shorts/", 1)[1][:11]
    m = _YT_ID_RE.search(url)  # last-resort 11-char token search
    return m.group(0) if m else None

def _norm_hit(title: str, url: str, video_id: Optional[str], desc: Optional[str]) -> Dict[str, str]:
    return {
        "title": _clean(title) or "Untitled",
        "videoId": _clean(video_id),
        "url": _clean(url),
        "description": (_clean(desc)[:300] if desc else ""),
    }

# -------------------- Legacy Public API (kept for compatibility) --------------------
def _search_youtube_api(api_key: str, query: str, max_results: int) -> List[Dict[str, str]]:
    if not _HAVE_GOOGLE_API or build is None:
        _dbg(False, "[YouTube] googleapiclient not installed; skipping API call.")
        return []
    yt = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    _dbg(False, f"[YouTube] Searching (API): '{query}', max={max_results}, region={_REGION_CODE or '-'}, safe={_SAFESEARCH}, order={_YT_API_ORDER}")
    kwargs: Dict[str, Any] = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "order": _YT_API_ORDER,
        "safeSearch": _SAFESEARCH if _SAFESEARCH in {"none", "moderate", "strict"} else "moderate",
    }
    if _REGION_CODE:
        kwargs["regionCode"] = _REGION_CODE
    resp = yt.search().list(**kwargs).execute(num_retries=1)
    items = resp.get("items", []) or []
    hits: List[Dict[str, str]] = []
    for it in items:
        vid = ((it.get("id") or {}).get("videoId") or "").strip()
        if not vid:
            continue
        snip = it.get("snippet") or {}
        title = (snip.get("title") or "").strip() or "Untitled"
        desc = (snip.get("description") or "").strip()
        hits.append(_norm_hit(title, f"https://www.youtube.com/watch?v={vid}", vid, desc))
    return hits

def _search_youtube_http(api_key: str, query: str, max_results: int) -> List[Dict[str, str]]:
    from urllib.parse import urlencode
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "key": api_key,
        "order": _YT_API_ORDER,
        "safeSearch": _SAFESEARCH if _SAFESEARCH in {"none", "moderate", "strict"} else "moderate",
    }
    if _REGION_CODE:
        params["regionCode"] = _REGION_CODE
    url = f"https://www.googleapis.com/youtube/v3/search?{urlencode(params)}"
    # Mask key in logs
    _dbg(False, f"[YouTube] Searching (HTTP): '{query}', url={url.replace(api_key, '***')}")
    resp = requests.get(url, timeout=_DEFAULT_TIMEOUT)
    resp.raise_for_status()
    data = resp.json() or {}
    out: List[Dict[str, str]] = []
    for item in data.get("items", []):
        vid = ((item.get("id") or {}).get("videoId") or "").strip()
        if not vid:
            continue
        snip = item.get("snippet") or {}
        title = _clean(snip.get("title")) or "Untitled"
        desc = _clean(snip.get("description"))
        out.append(_norm_hit(title, f"https://www.youtube.com/watch?v={vid}", vid, desc))
    return out

def _search_youtube_piped(query: str, max_results: int) -> List[Dict[str, str]]:
    if _PIPED_DISABLE:
        return []
    params = {"q": query, "region": _REGION_CODE or "US", "filter": "videos"}
    errors: List[str] = []
    for host in _PIPED_HOSTS:
        base = host if host.startswith("http") else f"https://{host}"
        url = f"{base}/api/v1/search"
        try:
            _dbg(False, f"[YouTube:Piped] {url} q='{query}'")
            r = requests.get(url, params=params, timeout=_DEFAULT_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            items = data if isinstance(data, list) else data.get("items") or data.get("data") or []
            tmp: List[Tuple[Dict[str, str], str]] = []
            for it in items:
                if (it.get("type") or "video").lower() != "video":
                    continue
                title = it.get("title") or ""
                vid = (it.get("id") or it.get("videoId") or "").strip()
                url_path = (it.get("url") or "").strip()
                desc = it.get("shortDescription") or it.get("description") or ""
                author = (it.get("uploaderName") or it.get("author") or it.get("uploader") or "").strip()
                if not vid:
                    vid = _extract_video_id_from_url(url_path or "")
                url_final = f"https://www.youtube.com/watch?v={vid}" if vid else (
                    f"https://www.youtube.com{url_path}" if url_path.startswith("/") else url_path
                )
                if not url_final:
                    continue
                tmp.append((_norm_hit(title, url_final, vid, desc), author))
            if not tmp:
                continue
            def _score(item: Tuple[Dict[str, str], str]) -> Tuple[int, int]:
                hit, author = item
                t = (hit.get("title") or "").lower()
                a = (author or "").lower()
                u = (hit.get("url") or "").lower()
                score = 0
                for ch in _YT_ALLOWLIST:
                    if ch and (ch in a or ch in t):
                        score += 5
                for kw in ("react server components", "server components", "rsc", "next.js", "nextjs", "vercel", "react conf", "jack herrington", "theo"):
                    if kw in t:
                        score += 2
                if "youtube.com/watch" in u:
                    score += 1
                return (-score, 0)
            tmp.sort(key=_score)
            out = [hit for hit, _a in tmp][:max_results]
            if out:
                return out
        except Exception as e:
            errors.append(f"{host}: {e}")
            continue
    _dbg(False, "[YouTube:Piped] all hosts failed:", "; ".join(errors))
    return []

def search_youtube(query: str, max_results: Optional[int] = None) -> List[Dict[str, str]]:
    q = _clean(query)
    if not q:
        return []
    have_key = bool((os.getenv("YOUTUBE_API_KEY") or "").strip())
    try:
        hosts_str = ",".join(_PIPED_HOSTS[:3]) + ("…" if len(_PIPED_HOSTS) > 3 else "")
    except Exception:
        hosts_str = "(none)"
    _dbg(False, f"[YouTube:diag legacy] key={'yes' if have_key else 'no'} region={_REGION_CODE or '-'} order={_YT_API_ORDER} piped_disabled={_PIPED_DISABLE} hosts={hosts_str}")
    mr = _clamp_max(max_results)
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    search_query = _build_search_query(q)
    hits: List[Dict[str, str]] = []
    try:
        if api_key:
            hits = _search_youtube_api(api_key, search_query, mr) if _HAVE_GOOGLE_API \
                else _search_youtube_http(api_key, search_query, mr)
            if not hits:
                fallback_q = _extract_keywords(q) or q
                if _HAVE_GOOGLE_API:
                    hits = _search_youtube_api(api_key, fallback_q, mr)
                else:
                    hits = _search_youtube_http(api_key, fallback_q, mr)
                if not hits:
                    hits = _search_youtube_piped(fallback_q, mr)
        else:
            hits = _search_youtube_piped(search_query, mr)
            if not hits:
                hits = _search_youtube_piped(_extract_keywords(q) or q, mr)
    except Exception as e:
        _dbg(False, f"[YouTube] search error: {e}")
        hits = []
    seen_vid, seen_url, out = set(), set(), []
    for h in hits:
        vid = (h.get("videoId") or "").strip().lower()
        url = (h.get("url") or "").strip().lower()
        if vid:
            if vid in seen_vid:
                continue
            seen_vid.add(vid)
        elif url:
            if url in seen_url:
                continue
            seen_url.add(url)
        out.append(_norm_hit(h.get("title") or "Untitled", h.get("url") or "", h.get("videoId") or None, h.get("description") or None))
    _dbg(False, f"[YouTube] results={len(out)}")
    return out[:mr]

def perform_youtube_search(
    query: str,
    max_results: Optional[int] = None,
    mem: Optional[MemoryManager] = None,
    role_id: Optional[Union[int, str]] = None,
    project_id: Optional[Union[int, str]] = None,
) -> Union[List[Dict[str, str]], Tuple[str, List[Dict[str, str]]]]:
    hits = search_youtube(query, max_results=max_results)
    if mem is None or role_id is None or project_id is None:
        return hits
    try:
        raw = f"YouTube search ({query}): {json.dumps(hits, indent=2)}"
        summary = mem.summarize_messages([raw])
        mem.store_memory(project_id=str(project_id), role_id=int(role_id), summary=summary, raw_text=raw)
        try:
            mem.insert_audit_log(str(project_id), int(role_id), None, "youtube", "search", (query or "")[:300])
        except Exception:
            pass
    except Exception as e:
        _dbg(False, "[YouTube] Memory logging failed:", e)
    block = (
        f"\n\n▶️ **YouTube search results for:** `{(query or '').strip()}`\n"
        + ("\n".join(f"- [{h['title']}]({h['url']})" for h in hits) if hits else "- _(no results)_")
    )
    _dbg(False, "[YouTube] block_len:", len(block), "hits:", len(hits))
    return block, hits

# -------------------- New deterministic helpers (used by youtube_service) --------------------
BASE_URL = "https://www.googleapis.com/youtube/v3"

def _fields_search() -> str:
    return (
        "items("
        "id/videoId,"
        "snippet(title,channelTitle,channelId,publishedAt,description,liveBroadcastContent)"
        ")"
    )

def _fields_videos() -> str:
    return (
        "items("
        "id,"
        "contentDetails/duration,"
        "statistics/viewCount,"
        "status/privacyStatus,status/uploadStatus,"
        "snippet/liveBroadcastContent"
        ")"
    )

def search_list(
    *,
    q: str,
    max_results: int,
    order: str,
    region: str,
    published_after_iso: Optional[str],
    relevance_language: Optional[str],
    safe_search: Optional[str],
    debug: bool = False,
) -> Dict[str, Any]:
    """Deterministic call to search.list (type=video, part=snippet)."""
    from urllib.parse import urlencode

    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("YouTube API key not configured")

    params = {
        "key": api_key,
        "part": "snippet",
        "type": "video",
        "q": q,
        "maxResults": max_results,
        "order": order,
        "fields": _fields_search(),
    }
    if region:
        params["regionCode"] = region
    if published_after_iso:
        params["publishedAfter"] = published_after_iso
    if relevance_language:
        params["relevanceLanguage"] = relevance_language
    if safe_search:
        params["safeSearch"] = safe_search

    # mask key in debug URL
    dbg_params = dict(params)
    dbg_params["key"] = "***"
    _dbg(debug, f"[YT HTTP] GET {BASE_URL}/search?{urlencode(dbg_params)}")

    r = requests.get(f"{BASE_URL}/search", params=params, timeout=10)
    _dbg(debug, f"[YT HTTP] status={r.status_code}")
    if r.status_code != 200:
        raise RuntimeError(f"YouTube search error {r.status_code}: {r.text}")

    data = r.json() or {}
    items = data.get("items", []) or []
    first_ids = [((it.get("id") or {}).get("videoId")) for it in items][:5]
    _dbg(debug, f"[YT HTTP] search.items={len(items)} ids(sample)={first_ids}")
    return data

def videos_list(video_ids: List[str], debug: bool = False) -> Dict[str, Any]:
    """Deterministic call to videos.list to enrich ids with duration, views, and status."""
    from urllib.parse import urlencode

    if not video_ids:
        _dbg(debug, "[YT HTTP] videos.list skipped: no ids")
        return {"items": []}

    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("YouTube API key not configured")

    params = {
        "key": api_key,
        "part": "contentDetails,statistics,status,snippet",
        "id": ",".join(video_ids),
        "fields": _fields_videos(),
        "maxResults": len(video_ids),
    }

    # mask key in debug URL
    dbg_params = dict(params)
    dbg_params["key"] = "***"
    _dbg(debug, f"[YT HTTP] GET {BASE_URL}/videos?{urlencode(dbg_params)}")

    r = requests.get(f"{BASE_URL}/videos", params=params, timeout=10)
    _dbg(debug, f"[YT HTTP] status={r.status_code}")
    if r.status_code != 200:
        raise RuntimeError(f"YouTube videos error {r.status_code}: {r.text}")

    data = r.json() or {}
    _dbg(debug, f"[YT HTTP] videos.items={len(data.get('items', []) or [])}")
    return data

__all__ = [
    "search_youtube",
    "perform_youtube_search",
    "search_list",
    "videos_list",
]
