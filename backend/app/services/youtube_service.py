# app/services/youtube_service.py
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime, timedelta, timezone
import time

from app.config.settings import settings
from app.services.youtube_http import search_list, videos_list

__SVC_VERSION__ = "yt-svc v4"

# --------------------------- tiny TTL cache ---------------------------
class _TTLCache:
    """Very small in-proc TTL cache (default 6h) to save quota."""
    def __init__(self, ttl_seconds: int = 6 * 60 * 60):
        self.ttl = ttl_seconds
        self._store: Dict[Tuple, Tuple[float, Any]] = {}

    def get(self, key: Tuple) -> Any:
        rec = self._store.get(key)
        if not rec:
            return None
        ts, val = rec
        if (time.time() - ts) > self.ttl:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: Tuple, val: Any) -> None:
        self._store[key] = (time.time(), val)

_cache = _TTLCache()

# --------------------------- helpers ---------------------------
def _iso_published_after(since_months: int) -> Optional[str]:
    """Convert months → ISO8601 timestamp (approximate months as 30 days)."""
    if since_months and since_months > 0:
        days = int(since_months * 30)
        dt = datetime.now(timezone.utc) - timedelta(days=days)
        return dt.isoformat().replace("+00:00", "Z")
    return None

def _to_int(val: Any) -> int:
    try:
        return int(val)
    except Exception:
        return 0

def _normalize(
    search_items: List[Dict[str, Any]],
    video_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Map raw API payloads to our stable schema, preserving search order."""
    by_id = {v.get("id"): v for v in video_items}
    out: List[Dict[str, Any]] = []
    for s in search_items:
        sid = s.get("id") or {}
        vid = sid.get("videoId")
        if not vid:
            continue

        v = by_id.get(vid, {})
        # live flag (prefer videos.list; fallback to search.list snippet)
        live_flag = (
            ((v.get("snippet") or {}).get("liveBroadcastContent"))
            or ((s.get("snippet") or {}).get("liveBroadcastContent"))
            or "none"
        )
        # Filter out live/upcoming only; privacy/upload status are unreliable with API-key auth
        if live_flag and live_flag != "none":
            continue

        sn = s.get("snippet") or {}
        out.append({
            "title": sn.get("title") or "",
            "videoId": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "channelTitle": sn.get("channelTitle") or "",
            "channelId": sn.get("channelId") or "",
            "publishedAt": sn.get("publishedAt") or "",
            "description": sn.get("description") or "",
            "duration": ((v.get("contentDetails") or {}).get("duration") or ""),
            "viewCount": _to_int((v.get("statistics") or {}).get("viewCount")),
            "isLive": False,
        })

    # De-dup by videoId while preserving order
    seen: Set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for it in out:
        if it["videoId"] in seen:
            continue
        seen.add(it["videoId"])
        deduped.append(it)
    return deduped

def _apply_channel_allowlist(
    items: List[Dict[str, Any]],
    channels_csv: Optional[str],
) -> List[Dict[str, Any]]:
    """Keep only items whose channelId matches, or channelTitle contains, given filters."""
    if not channels_csv:
        return items
    raw = [c.strip() for c in channels_csv.split(",") if c.strip()]
    if not raw:
        return items
    ids = {c for c in raw if c.startswith("UC")}  # common channelId pattern
    names = {c.lower() for c in raw if not c.startswith("UC")}
    filtered: List[Dict[str, Any]] = []
    for it in items:
        cid = (it.get("channelId") or "").strip()
        name = (it.get("channelTitle") or "").strip().lower()
        if cid and cid in ids:
            filtered.append(it); continue
        if any(n in name for n in names):
            filtered.append(it); continue
    return filtered

# --------------------------- public API ---------------------------
def search_videos(
    *,
    query: str,
    max_results: int = 3,
    since_months: int = 24,
    channels: Optional[str] = None,
    order: Optional[str] = None,   # "relevance" | "date"
    region: Optional[str] = None,  # e.g., "US"
    debug: bool = False,
) -> List[Dict[str, Any]]:
    """
    Deterministic search:
    1) search.list → collect IDs
    2) videos.list → enrich
    3) filter (non-live)
    4) normalize → schema used by routers/youtube.py
    5) optional allowlist filter by channels
    """
    if not settings.YOUTUBE_API_KEY:
        raise RuntimeError("YouTube API key not configured")

    eff_order = order or getattr(settings, "YOUTUBE_ORDER", "relevance")
    eff_region = region or getattr(settings, "YOUTUBE_REGION_CODE", "")
    published_after = _iso_published_after(since_months)

    # entry banner (versioned)
    if debug or getattr(settings, "YOUTUBE_DEBUG", False):
        print(f"[YouTube:{__SVC_VERSION__}] query='{query}' max={max_results} since={since_months}m order={eff_order} region={eff_region or '-'}")

    cache_key = (query, max_results, since_months, channels or "", eff_order, eff_region)
    cached = _cache.get(cache_key)
    cache_hit = cached is not None

    if cache_hit:
        items = cached
        if debug or getattr(settings, "YOUTUBE_DEBUG", False):
            print(f"[YouTube:{__SVC_VERSION__}] cache HIT for key={cache_key}")
    else:
        s_json = search_list(
            q=query,
            max_results=max_results,
            order=eff_order,
            region=eff_region,
            published_after_iso=published_after,
            relevance_language=None,
            safe_search=getattr(settings, "YOUTUBE_SAFESEARCH", "moderate"),
            debug=debug or getattr(settings, "YOUTUBE_DEBUG", False),
        )
        s_items = s_json.get("items", []) or []
        ids = [
            (it.get("id") or {}).get("videoId")
            for it in s_items
            if (it.get("id") or {}).get("videoId")
        ]
        if debug or getattr(settings, "YOUTUBE_DEBUG", False):
            print(f"[YouTube:{__SVC_VERSION__}] search.list items={len(s_items)} ids(sample)={ids[:5]}")

        v_json = videos_list(ids, debug=debug or getattr(settings, "YOUTUBE_DEBUG", False))
        v_items = v_json.get("items", []) or []
        if debug or getattr(settings, "YOUTUBE_DEBUG", False):
            print(f"[YouTube:{__SVC_VERSION__}] videos.list items={len(v_items)}")

        items = _normalize(s_items, v_items)
        if debug or getattr(settings, "YOUTUBE_DEBUG", False):
            print(f"[YouTube:{__SVC_VERSION__}] normalized={len(items)} (pre-filter)")

        items = _apply_channel_allowlist(items, channels)
        items = items[:max_results]  # enforce post-filter cap
        _cache.set(cache_key, items)

    # diagnostics (final)
    if debug or getattr(settings, "YOUTUBE_DEBUG", False):
        key_flag = "yes"
        hosts = ",".join(getattr(settings, "PIPED_HOSTS", [])) if getattr(settings, "PIPED_HOSTS", ()) else "-"
        since_tag = f"{since_months}m" if since_months else "0m"
        allowlisted = len(getattr(settings, "YOUTUBE_CHANNEL_ALLOWLIST", []))
        print(
            f"[YouTube:diag {__SVC_VERSION__}] key={key_flag} region={eff_region or '-'} order={eff_order} "
            f"safe={getattr(settings, 'YOUTUBE_SAFESEARCH', 'moderate')} since={since_tag} "
            f"allowlisted={allowlisted} piped_disabled={getattr(settings, 'PIPED_DISABLE', True)} hosts={hosts}"
        )
        print(f"[YouTube] results={len(items)} cache={'HIT' if cache_hit else 'MISS'}")

    return items
