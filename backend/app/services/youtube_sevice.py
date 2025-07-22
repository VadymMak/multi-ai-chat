# app/services/youtube_sevice.py
import os
import json
import re
from typing import Tuple, List, Dict, Optional, Union

try:
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.errors import HttpError  # type: ignore
    _HAVE_GOOGLE_API = True
except Exception:
    # Degrade gracefully if the library isn't installed
    build = None  # type: ignore
    HttpError = Exception  # type: ignore
    _HAVE_GOOGLE_API = False

from app.memory.manager import MemoryManager


def _extract_keywords(text: str, max_length: int = 120) -> str:
    """Clean text and return a space-separated keyword string."""
    text = (text or "").strip()
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
    words = text.split()
    stop = {"the", "and", "for", "with", "a", "an", "in", "to", "of", "by", "on"}
    keywords = [w for w in words if len(w) > 2 and w.lower() not in stop]
    return " ".join(keywords[:max_length]).strip()


def _build_search_query(original: str) -> str:
    """Apply simple heuristics to refine search query."""
    cleaned = _extract_keywords(original.lower())
    if not cleaned:
        return "technology tutorial"

    if any(k in cleaned for k in ("gpu", "nvidia", "ai")):
        return f"{cleaned} GPU AI benchmark 2025"
    if any(k in cleaned for k in ("monitor", "screen")):
        return f"{cleaned} developer monitor reviews 2025"
    if any(k in cleaned for k in ("compare", "price", "model")):
        return f"{cleaned} updated comparison 2025"
    if any(k in cleaned for k in ("contactor", "electrical", "220v")):
        return f"{cleaned} electrical wiring tutorial"
    if "dell" in cleaned:
        return f"{cleaned} dell hardware repair guide"
    return f"{cleaned} technology tutorial"


def _search_youtube_api(api_key: str, query: str, max_results: int = 10) -> List[Dict[str, str]]:
    """Call the YouTube Data API and return normalized hits."""
    if not _HAVE_GOOGLE_API or build is None:
        print("[YouTube] googleapiclient not installed; skipping API call.")
        return []

    yt = build("youtube", "v3", developerKey=api_key)
    print(f"[YouTube] Searching for: '{query}'")
    resp = yt.search().list(
        part="snippet",
        q=query,
        type="video",
        maxResults=max_results,
        videoCategoryId="27",  # Technology category
        order="relevance",
        publishedAfter="2023-01-01T00:00:00Z",
        safeSearch="none",
    ).execute()

    items = resp.get("items", []) or []
    hits: List[Dict[str, str]] = []
    for it in items:
        vid = ((it.get("id") or {}).get("videoId") or "").strip()
        if not vid:
            continue
        # Filter obvious garbage IDs (very rare)
        if vid.startswith("s"):
            continue
        snip = it.get("snippet") or {}
        title = (snip.get("title") or "").strip()
        desc = (snip.get("description") or "").strip()
        hits.append({
            "title": title,
            "videoId": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "description": desc[:200]
        })
    return hits


def perform_youtube_search(
    query: str,
    mem: MemoryManager,
    role_id: Union[int, str],
    project_id: Union[int, str],
) -> Tuple[str, List[dict]]:
    """
    Perform a YouTube search, optionally retry on no results, and store findings in memory.
    Returns a Markdown block and structured list of search results.
    """
    try:
        api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        if not api_key:
            print("[YouTube] YOUTUBE_API_KEY missing; skipping search.")
            return "\n\nℹ️ YouTube search not configured.", []

        # Build query & try search
        search_query = _build_search_query(query or "")
        hits = _search_youtube_api(api_key, search_query)[:3]

        # Retry with fallback if no hits
        if not hits:
            fallback_query = _extract_keywords(query or "")
            if fallback_query and fallback_query != search_query:
                hits = _search_youtube_api(api_key, fallback_query)[:3]
                search_query = fallback_query

        if not hits:
            print("[YouTube] No relevant results. Returning fallback link.")
            hits = [{
                "title": "No relevant YouTube results found",
                "videoId": "fallback",
                "url": f"https://www.youtube.com/results?search_query={(search_query or 'technology').replace(' ', '+')}",
                "description": f"Try this query manually: '{search_query}'"
            }]

        # Best-effort memory/audit (won’t fail the request if these error)
        try:
            raw = f"YouTube search ({query}): {json.dumps(hits, indent=2)}"
            summary = mem.summarize_messages([raw])
            mem.store_memory(
                project_id=str(project_id),
                role_id=int(role_id),
                summary=summary,
                raw_text=raw
            )
            try:
                mem.insert_audit_log(str(project_id), int(role_id), None, "youtube", "search", search_query[:300])
            except Exception:
                pass
        except Exception as e:
            print("[YouTube] Memory logging failed:", e)

        block = (
            f"\n\n▶️ **YouTube search results for:** `{search_query}`\n"
            + "\n".join(f"- [{h['title']}]({h['url']})" for h in hits)
        )

        print("[YouTube] block_len:", len(block), "hits:", len(hits))
        return block, hits

    except HttpError as e:
        print("[YouTube API Error]", e)
        return "\n\n⚠️ YouTube API error.", []

    except Exception as e:
        print("[YouTube] General error:", e)
        return "\n\n⚠️ YouTube search failed.", []
