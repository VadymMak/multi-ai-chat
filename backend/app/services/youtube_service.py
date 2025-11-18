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


# --------------------------- SMART SEARCH WITH RELEVANCE SCORING ---------------------------

def _calculate_relevance_score(
    video: Dict[str, Any],
    query_keywords: List[str],
    trusted_channels: List[str]
) -> float:
    """
    Calculate relevance score for a video (0-100)
    
    Scoring breakdown:
    - Title match: 40 points max
    - Description match: 20 points max
    - Channel trust: 15 points max
    - View count: 10 points max
    - Recency: 10 points max
    - Duration: 5 points max
    """
    score = 0.0
    
    title = (video.get('title') or '').lower()
    description = (video.get('description') or '').lower()
    channel = (video.get('channelTitle') or '').lower()
    
    # 1. TITLE MATCHING (40 points max)
    title_matches = sum(1 for kw in query_keywords if kw in title)
    score += min(title_matches * 10, 40)
    
    # Bonus: exact query in title
    query_str = ' '.join(query_keywords)
    if query_str in title:
        score += 10
    
    # 2. DESCRIPTION MATCHING (20 points max)
    desc_matches = sum(1 for kw in query_keywords if kw in description)
    score += min(desc_matches * 5, 20)
    
    # 3. CHANNEL TRUST (15 points max)
    channel_match = any(tc in channel for tc in trusted_channels)
    if channel_match:
        score += 15
    
    # 4. VIEW COUNT (10 points max)
    view_count = int(video.get('viewCount') or 0)
    if view_count > 1000000:
        score += 10
    elif view_count > 100000:
        score += 7
    elif view_count > 10000:
        score += 4
    
    # 5. RECENCY (10 points max)
    published_at = video.get('publishedAt', '')
    if published_at:
        try:
            pub_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            days_old = (datetime.now(timezone.utc) - pub_date).days
            
            if days_old < 180:  # 6 months
                score += 10
            elif days_old < 365:  # 1 year
                score += 7
            elif days_old < 730:  # 2 years
                score += 4
        except Exception:
            pass
    
    # 6. DURATION (5 points max)
    # Prefer 5-60 minute videos (tutorials/explanations)
    duration_str = video.get('duration', '')
    if duration_str.startswith('PT'):
        try:
            import re
            # Parse ISO 8601 duration (e.g., PT15M30S)
            hours = re.search(r'(\d+)H', duration_str)
            minutes = re.search(r'(\d+)M', duration_str)
            
            total_minutes = 0
            if hours:
                total_minutes += int(hours.group(1)) * 60
            if minutes:
                total_minutes += int(minutes.group(1))
            
            # Optimal: 5-60 minutes
            if 5 <= total_minutes <= 60:
                score += 5
            elif 3 <= total_minutes <= 90:
                score += 3
        except Exception:
            pass
    
    return score


def _extract_query_keywords(query: str) -> List[str]:
    """
    Extract meaningful keywords from query
    """
    # Remove common stop words
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 
        'for', 'of', 'with', 'by', 'from', 'how', 'what', 'when', 'where',
        'is', 'are', 'was', 'were', 'be', 'been', 'being', 'i', 'you'
    }
    
    import re
    # Remove special characters
    clean_query = re.sub(r'[^\w\s]', ' ', query.lower())
    words = clean_query.split()
    
    # Keep only meaningful words (length > 2, not stop words)
    keywords = [w for w in words if len(w) > 2 and w not in stop_words]
    
    return keywords


def search_videos_smart(
    *,
    query: str,
    max_results: int = 5,
    min_score: float = 50.0,
    since_months: int = 24,
    channels: Optional[str] = None,
    order: Optional[str] = None,
    region: Optional[str] = None,
    debug: bool = False,
) -> List[Dict[str, Any]]:
    """
    Smart video search with relevance scoring
    
    Returns only videos with score >= min_score, sorted by relevance
    """
    # Expanded trusted channels list
    trusted_channels_default = [
        'reactconf', 'react conf', 'vercel', 'next.js',
        'jackherrington', 'jack herrington', 'theo', 't3', 't3.gg',
        'fireship', 'traversy media', 'web dev simplified',
        'academind', 'net ninja', 'programming with mosh',
        'freecodecamp', 'code with antonio', 'codevolution',
        'javascript mastery', 'coding train', 'fun fun function'
    ]
    
    # Add user-specified channels
    if channels:
        custom = [c.strip().lower() for c in channels.split(',') if c.strip()]
        trusted_channels_default.extend(custom)
    
    # Get MORE results than needed (we'll filter)
    search_limit = max_results * 4  # Get 20 to filter to 5
    
    if debug or getattr(settings, "YOUTUBE_DEBUG", False):
        print(f"[YouTube:smart] Fetching {search_limit} videos to filter to {max_results} (min_score={min_score})")
    
    # Use existing search_videos function
    raw_results = search_videos(
        query=query,
        max_results=search_limit,
        since_months=since_months,
        channels=None,  # We'll filter ourselves
        order=order or 'relevance',
        region=region,
        debug=debug
    )
    
    # Extract keywords from query
    query_keywords = _extract_query_keywords(query)
    
    if debug or getattr(settings, "YOUTUBE_DEBUG", False):
        print(f"[YouTube:smart] Query keywords: {query_keywords}")
    
    # Score all results
    scored_videos: List[Dict[str, Any]] = []
    for video in raw_results:
        score = _calculate_relevance_score(
            video, 
            query_keywords, 
            trusted_channels_default
        )
        
        if score >= min_score:
            video_with_score = dict(video)
            video_with_score['relevance_score'] = score
            scored_videos.append(video_with_score)
    
    # Sort by score (highest first)
    scored_videos.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
    
    # Return top N
    results = scored_videos[:max_results]
    
    if debug or getattr(settings, "YOUTUBE_DEBUG", False):
        print(f"[YouTube:smart] Scored {len(scored_videos)} videos >= {min_score}, returning top {len(results)}")
        for i, v in enumerate(results[:3], 1):
            print(f"  {i}. {v.get('title', '')[:50]}... (score: {v.get('relevance_score', 0):.1f})")
    
    return results


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
