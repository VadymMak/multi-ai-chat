# File: app/routers/youtube.py
from __future__ import annotations

import json
import os
import re
import time
from typing import List, Optional, Union, Literal, Dict, Any, Tuple

import requests
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import settings
from app.services.youtube_service import search_videos  # deterministic search

# ----------------------------- Optional deps -----------------------------
# Transcript support
try:  # pragma: no cover
    from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled  # type: ignore
    _HAVE_YT_TRANSCRIPT = True
except Exception:  # pragma: no cover
    YouTubeTranscriptApi = None  # type: ignore
    TranscriptsDisabled = Exception  # type: ignore
    _HAVE_YT_TRANSCRIPT = False

# LLM summarizer
try:  # pragma: no cover
    from app.providers.factory import ask_model  # type: ignore
    _HAVE_ASK_MODEL = True
except Exception:  # pragma: no cover
    ask_model = None  # type: ignore
    _HAVE_ASK_MODEL = False

router = APIRouter(tags=["YouTube"])

# =========================================================================
#                                MICRO-CACHES
# =========================================================================

class _TTLCache:
    """Extremely small, in-proc TTL cache."""
    def __init__(self, ttl_seconds: int):
        self.ttl = max(1, int(ttl_seconds))
        self._store: Dict[Tuple[Any, ...], Tuple[float, Any]] = {}

    def get(self, key: Tuple[Any, ...]) -> Any:
        rec = self._store.get(key)
        if not rec:
            return None
        ts, val = rec
        if (time.time() - ts) > self.ttl:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: Tuple[Any, ...], val: Any) -> None:
        self._store[key] = (time.time(), val)

# Configurable TTLs (seconds)
_SUMMARY_TTL = int(getattr(settings, "YT_SUMMARY_TTL_SECONDS", 2 * 60 * 60))      # 2h
_TRANSCRIPT_TTL = int(getattr(settings, "YT_TRANSCRIPT_TTL_SECONDS", 12 * 60 * 60))  # 12h

_SUMMARY_CACHE = _TTLCache(_SUMMARY_TTL)
_TRANSCRIPT_CACHE = _TTLCache(_TRANSCRIPT_TTL)

def _effective_summary_model_key(model_key_override: Optional[str]) -> str:
    """
    Resolve which model key will be used so the summary cache key is stable.
    If LLM is not available, return 'heuristic'.
    """
    if not _HAVE_ASK_MODEL or ask_model is None:
        return "heuristic"
    return (
        model_key_override
        or getattr(settings, "YT_SUMMARY_MODEL_KEY", None)
        or getattr(settings, "DEFAULT_MODEL", None)
        or "gpt-4o-mini"
    )

# ----------------------------- Models (Search) -----------------------------

class YouTubeVideo(BaseModel):
    title: str
    videoId: str
    url: str  # canonical watch URL
    channelTitle: str
    channelId: str
    publishedAt: str  # ISO8601
    description: str
    duration: str     # ISO8601 PT...
    viewCount: int
    isLive: bool


class YouTubeSearchResponse(BaseModel):
    items: List[YouTubeVideo] = Field(default_factory=list)


@router.get(
    "/youtube/search",
    response_model=YouTubeSearchResponse,
    summary="YouTube Search (deterministic, verified links)",
    description=(
        "Deterministic YouTube search via Data API v3.\n"
        "- Returns canonical watch URLs.\n"
        "- Excludes live/ongoing streams.\n"
        "- Diagnostics are printed to logs when debug=1."
    ),
)
def youtube_search(
    # Canonical params
    query: Optional[str] = Query(None, description="Search query text"),
    max: int = Query(3, ge=1, le=10, description="Max results (1–10)"),
    since_months: int = Query(
        24, alias="sinceMonths", ge=0,
        description="Only videos within the last N months (0 = no filter)"
    ),
    channels: Optional[str] = Query(
        None, description="Comma-separated channel names/ids allowlist (optional)"
    ),
    order: Literal["relevance", "date"] = Query("relevance", description="Sort order"),
    region: str = Query("US", description="YouTube regionCode, e.g. US"),
    debug: bool = Query(False, description="If true, prints a diag line and a results line to server logs"),

    # Legacy aliases (kept for compatibility)
    q_alias: Optional[str] = Query(None, alias="q", description="Alias of 'query'"),
    max_results_alias: Optional[int] = Query(
        None, alias="max_results", ge=1, le=25, description="Legacy alias of 'max'"
    ),

    # Optional audit hints (accepted but unused here)
    role_id: Optional[int] = Query(None, description="Optional role id for audit/memory logging"),
    project_id: Optional[Union[int, str]] = Query(None, description="Optional project id for audit/memory logging"),
):
    """
    Returns: { "items": [YouTubeVideo, ...] }
    """
    # Resolve query
    q_final = (query or q_alias or "").strip()
    if not q_final:
        raise HTTPException(status_code=400, detail="Provide ?query= or ?q=")

    # Effective max (clamped to 10)
    eff_max = max_results_alias if max_results_alias is not None else max
    if eff_max > 10:
        eff_max = 10

    if not settings.YOUTUBE_API_KEY:
        raise HTTPException(status_code=503, detail="YouTube API key not configured")

    if debug or settings.YOUTUBE_DEBUG:
        since_tag = f"{since_months}m" if since_months else "0m"
        hosts = ",".join(settings.PIPED_HOSTS) if getattr(settings, "PIPED_HOSTS", []) else "-"
        print(
            f"[router:yt v5] q='{q_final}' max={eff_max} since={since_tag} "
            f"order={order} region={region} channels={channels or '-'} "
            f"safe={getattr(settings, 'YOUTUBE_SAFESEARCH', None)} piped_disabled={getattr(settings, 'PIPED_DISABLE', None)} hosts={hosts}"
        )

    try:
        items_raw = search_videos(
            query=q_final,
            max_results=eff_max,
            since_months=since_months,
            channels=channels,
            order=order,
            region=region,
            debug=debug,
        )
    except Exception as e:
        print(f"[router:yt v5] service error: {e}")
        raise HTTPException(status_code=500, detail="YouTube search failed")

    items = [
        YouTubeVideo(
            title=it.get("title", ""),
            videoId=it.get("videoId", ""),
            url=it.get("url", ""),
            channelTitle=it.get("channelTitle", ""),
            channelId=it.get("channelId", ""),
            publishedAt=it.get("publishedAt", ""),
            description=it.get("description", ""),
            duration=it.get("duration", ""),
            viewCount=int(it.get("viewCount", 0) or 0),
            isLive=bool(it.get("isLive", False)),
        )
        for it in (items_raw or [])
    ]

    if debug or settings.YOUTUBE_DEBUG:
        print(f"[router:yt v5] returning {len(items)} item(s)")

    return YouTubeSearchResponse(items=items)

# ----------------------------- Models (Summarize) -----------------------------

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

class YouTubeSummarizeRequest(BaseModel):
    videoId: Optional[str] = Field(default=None, description="11-char YouTube video id")
    url: Optional[str] = Field(default=None, description="YouTube URL (we will extract id)")
    lang: Optional[str] = Field(default="en", description="Preferred transcript language")
    max_chars: int = Field(default=12000, ge=1000, le=60000, description="Max transcript/description chars to summarize")
    model_key: Optional[str] = Field(default=None, description="Optional MODEL_REGISTRY key for summarization")
    debug: bool = Field(default=False, description="Emit debug logs to the server console")


class YouTubeSummaryResponse(BaseModel):
    videoId: str
    url: str
    summary: str
    bullets: List[str] = Field(default_factory=list)
    chapters: List[Dict[str, Any]] = Field(default_factory=list)  # [{title, time}]

# ----------------------------- Helpers (Summarize) -----------------------------

def _dbg(enabled: bool, *a: Any) -> None:
    if enabled or getattr(settings, "YOUTUBE_DEBUG", False):
        print(*a)

def _canon_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"

def _extract_video_id(input_value: Optional[str]) -> Optional[str]:
    s = (input_value or "").strip()
    if not s:
        return None
    if _YT_ID_RE.fullmatch(s):
        return s
    try:
        from urllib.parse import urlparse, parse_qs
        u = urlparse(s)
        if "youtu.be" in (u.netloc or ""):
            seg = (u.path or "/").strip("/").split("/")[0]
            return seg[:11] if seg else None
        if (u.path or "").startswith("/shorts/"):
            seg = (u.path or "/").split("/shorts/")[1].split("/")[0]
            return seg[:11] if seg else None
        q = parse_qs(u.query or "")
        vid = (q.get("v") or [None])[0]
        if vid and _YT_ID_RE.fullmatch(vid):
            return vid
    except Exception:
        pass
    m = re.search(r"[A-Za-z0-9_-]{11}", s)
    return m.group(0) if m else None

def _join_transcript_entries(entries: List[dict]) -> str:
    parts: List[str] = []
    for e in entries or []:
        txt = (e.get("text") or "").replace("\n", " ").strip()
        if txt:
            parts.append(txt)
    return " ".join(parts)

def _fetch_transcript_text(video_id: str, lang: str, debug: bool) -> str:
    # Transcript micro-cache
    ck = (video_id, (lang or "en").lower())
    cached = _TRANSCRIPT_CACHE.get(ck)
    if isinstance(cached, str):
        _dbg(debug, "[router:yt summarize] transcript cache=HIT")
        return cached

    if not _HAVE_YT_TRANSCRIPT or YouTubeTranscriptApi is None:
        _dbg(debug, "[router:yt summarize] youtube_transcript_api not installed.")
        _TRANSCRIPT_CACHE.set(ck, "")  # negative cache
        return ""
    try:
        langs = [lang] if lang else []
        if "-" in lang:
            langs.append(lang.split("-")[0])
        langs += ["en", "en-US", "en-GB"]
        entries = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)  # type: ignore
        text = _join_transcript_entries(entries)
        _dbg(debug, f"[router:yt summarize] transcript entries={len(entries)}")
        _TRANSCRIPT_CACHE.set(ck, text)
        return text
    except TranscriptsDisabled:  # type: ignore
        _dbg(debug, "[router:yt summarize] transcripts disabled")
    except Exception as e:
        _dbg(debug, f"[router:yt summarize] transcript fetch failed: {e}")
    _TRANSCRIPT_CACHE.set(ck, "")  # negative cache
    return ""

def _fetch_snippet_description(video_id: str, debug: bool) -> Tuple[str, str]:
    api_key = (getattr(settings, "YOUTUBE_API_KEY", "") or os.getenv("YOUTUBE_API_KEY", "")).strip()
    if not api_key:
        return "", ""
    params = {
        "key": api_key,
        "part": "snippet",
        "id": video_id,
        "fields": "items(snippet(title,description))",
        "maxResults": 1,
    }
    r = requests.get("https://www.googleapis.com/youtube/v3/videos", params=params, timeout=10)
    _dbg(debug, f"[router:yt summarize] vids.snippet GET {r.url} status={r.status_code}")
    if r.status_code != 200:
        return "", ""
    data = r.json() or {}
    items = data.get("items", []) or []
    if not items:
        return "", ""
    sn = (items[0] or {}).get("snippet") or {}
    return (sn.get("title") or ""), (sn.get("description") or "")

_URL_RE = re.compile(r"https?://\S+")
_HASHTAG_RE = re.compile(r"(?:^|\s)(#[\w-]+)")
_EMOJI_RE = re.compile(
    "["  # common emoji ranges
    "\U0001F300-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "]+",
    flags=re.UNICODE,
)

def _clean_description(text: str) -> str:
    """
    Remove URLs, hashtags, common CTA/social lines, and emojis. Normalize whitespace.
    """
    if not text:
        return ""
    t = _URL_RE.sub(" ", text)
    t = _HASHTAG_RE.sub(" ", t)
    noise = [
        "subscribe", "like and subscribe", "follow me", "twitter:", "instagram:",
        "facebook:", "linkedin:", "join this channel", "patreon", "sponsor", "coupon",
        "promo code", "merch", "sign up", "join my course", "use code", "discord", "newsletter",
        "business inquiries", "affiliat", "support the channel"
    ]
    lines = [l for l in t.splitlines() if l.strip()]
    kept: List[str] = []
    for ln in lines:
        ln_l = ln.lower()
        if any(w in ln_l for w in noise):
            continue
        kept.append(ln)
    t = " ".join(kept)
    t = _EMOJI_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

_CHAPTER_RE = re.compile(
    r"(?mi)^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—:]?\s*(.+?)\s*$"
)

def _extract_chapters(text: str) -> List[Dict[str, str]]:
    """
    Heuristic chapter extraction from description lines: "00:00 Intro".
    """
    if not text:
        return []
    chapters: List[Dict[str, str]] = []
    for m in _CHAPTER_RE.finditer(text):
        timecode = m.group(1).strip()
        title = m.group(2).strip()
        if title:
            chapters.append({"time": timecode, "title": title})
    # Deduplicate by time
    seen = set()
    out: List[Dict[str, str]] = []
    for ch in chapters:
        if ch["time"] in seen:
            continue
        seen.add(ch["time"])
        out.append(ch)
    return out[:30]

def _heuristic_summarize(text: str, title_fallback: str = "") -> Tuple[str, List[str]]:
    t = (text or "").strip()
    if not t:
        return (f"This video provides an overview of {title_fallback or 'the topic'}.", [])
    t = re.sub(r"\s+", " ", t).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]
    summary = " ".join(sentences[:3])
    if summary and not summary.endswith((".", "!", "?")):
        summary += "."
    bullets = [s.rstrip(".") for s in sentences[3:12]][:8]
    return summary, bullets

def _maybe_llm_summarize(
    text: str,
    title: str,
    model_key_override: Optional[str],
    lang: Optional[str],
    debug: bool
) -> Optional[Dict[str, Any]]:
    """
    Ask the configured LLM to produce a STRICT JSON summary in the requested language.
    """
    if not _HAVE_ASK_MODEL or ask_model is None:
        return None

    target_lang = (lang or "en").strip()
    model_key = _effective_summary_model_key(model_key_override)

    system_prompt = (
        "You are a meticulous technical summarizer. "
        f"Write ALL content in {target_lang}. "
        "Return STRICT JSON only—no prefixes, no code fences."
    )

    user_prompt = (
        "Given text from a YouTube transcript or description, produce STRICT JSON with keys:\n"
        "summary: 1 concise paragraph (no links/CTAs/hashtags/emoji)\n"
        "bullets: 6-10 short bullets (no links/CTAs/hashtags/emoji)\n"
        "chapters: array of objects {\"title\": string, \"time\": \"mm:ss\"} if obvious; else an empty array\n\n"
        f"Video title: {title}\n\n"
        f"Text (truncated):\n{text[:12000]}\n\n"
        "Output language: " + target_lang + "\n"
        "Return JSON ONLY."
    )

    try:
        raw = ask_model(
            [{"role": "user", "content": user_prompt}],
            model_key=model_key,
            system_prompt=system_prompt,
        )  # type: ignore

        out = (raw or "").strip()
        # Strip code fences if present
        if out.startswith("```"):
            out = out.strip("`").strip()
            brace = out.find("{")
            if brace > 0:
                out = out[brace:]

        try:
            return json.loads(out)
        except Exception:
            m = re.search(r"\{[\s\S]+\}", out)
            if m:
                return json.loads(m.group(0))
    except Exception as e:
        _dbg(debug, f"[router:yt summarize] LLM error: {e}")
    return None

# ----------------------------- Endpoint (Summarize) -----------------------------

@router.post(
    "/youtube/summarize",
    response_model=YouTubeSummaryResponse,
    summary="Summarize a YouTube video (transcript → summary, bullets, optional chapters)",
    description=(
        "Fetches transcript when available (no OAuth), falls back to video description. "
        "If an LLM is configured, produces structured summary; otherwise uses a clean heuristic. "
        "We also try to extract chapters from timestamps in descriptions."
    ),
)
def youtube_summarize(payload: YouTubeSummarizeRequest):
    video_id = _extract_video_id(payload.videoId) or _extract_video_id(payload.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Provide a valid videoId or url")

    debug = bool(payload.debug)
    watch_url = _canon_watch_url(video_id)
    eff_model_key = _effective_summary_model_key(payload.model_key)
    max_chars = int(payload.max_chars)

    _dbg(debug, f"[router:yt summarize] videoId={video_id} lang={payload.lang} max_chars={max_chars} model={eff_model_key}")

    # --------------------- SUMMARY CACHE: check early ---------------------
    summ_ck: Tuple[Any, ...] = (video_id, (payload.lang or "en").lower(), max_chars, eff_model_key)
    cached_summary = _SUMMARY_CACHE.get(summ_ck)
    if isinstance(cached_summary, dict):
        _dbg(debug, "[router:yt summarize] summary cache=HIT")
        # Ensure required fields exist
        return YouTubeSummaryResponse(**{
            "videoId": cached_summary.get("videoId", video_id),
            "url": cached_summary.get("url", watch_url),
            "summary": cached_summary.get("summary", ""),
            "bullets": cached_summary.get("bullets", []) or [],
            "chapters": cached_summary.get("chapters", []) or [],
        })

    # 1) Transcript first (with its own micro-cache)
    transcript_text = _fetch_transcript_text(video_id, payload.lang or "en", debug)

    # 2) Fallback to snippet (title/description)
    title, description = _fetch_snippet_description(video_id, debug)
    desc_clean = _clean_description(description)
    chapters_guess = _extract_chapters(description) if description else []

    base_text = (transcript_text or desc_clean or "").strip()
    if not base_text:
        resp = YouTubeSummaryResponse(
            videoId=video_id,
            url=watch_url,
            summary=f"Sorry—no transcript or description could be retrieved for this video{(' (' + title + ')') if title else ''}.",
            bullets=[],
            chapters=[],
        )
        # Cache the negative-ish result briefly as well
        _SUMMARY_CACHE.set(summ_ck, resp.dict())
        return resp

    # 3) Truncate
    if len(base_text) > max_chars:
        base_text = base_text[: max_chars]
        _dbg(debug, f"[router:yt summarize] text truncated to {max_chars} chars")

    # 4) LLM or heuristic (now we try LLM for transcript OR description)
    llm = _maybe_llm_summarize(
        base_text,
        title or "",
        payload.model_key,
        payload.lang or "en",
        debug,
    )
    if isinstance(llm, dict) and "summary" in llm:
        resp = YouTubeSummaryResponse(
            videoId=video_id,
            url=watch_url,
            summary=str(llm.get("summary") or "").strip() or f"Summary of '{title or 'the video'}'.",
            bullets=[str(x).strip() for x in (llm.get("bullets") or []) if str(x).strip()],
            chapters=[c for c in (llm.get("chapters") or chapters_guess) if isinstance(c, dict)],
        )
        _SUMMARY_CACHE.set(summ_ck, resp.dict())
        return resp

    # Heuristic fallback
    summary, bullets = _heuristic_summarize(base_text, title_fallback=title or "")
    resp = YouTubeSummaryResponse(
        videoId=video_id,
        url=watch_url,
        summary=summary,
        bullets=bullets,
        chapters=chapters_guess,
    )
    _SUMMARY_CACHE.set(summ_ck, resp.dict())
    return resp
