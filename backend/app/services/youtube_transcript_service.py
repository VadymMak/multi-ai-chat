# File: app/services/youtube_transcript_service.py
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple
import re
import os

from app.config.settings import settings
from app.providers.factory import ask_model

# Optional dependency (no OAuth needed)
try:
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled  # type: ignore
    _HAVE_YT_TRANSCRIPT = True
except Exception:
    _HAVE_YT_TRANSCRIPT = False
    NoTranscriptFound = Exception  # type: ignore
    TranscriptsDisabled = Exception  # type: ignore

# tiny util reused in frontend/backend
_YT_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")

def extract_video_id(url_or_id: str) -> Optional[str]:
    s = (url_or_id or "").strip()
    if not s:
        return None
    if len(s) >= 11 and _YT_ID_RE.fullmatch(s[-11:] or ""):
        return s[-11:]
    try:
        from urllib.parse import urlparse, parse_qs
        u = urlparse(s)
        if "youtu.be" in u.netloc:
            seg = (u.path or "/").strip("/").split("/")[0]
            return seg[:11] if _YT_ID_RE.fullmatch(seg[:11] or "") else None
        if "/shorts/" in u.path:
            seg = u.path.split("/shorts/")[1].split("/")[0]
            return seg[:11] if _YT_ID_RE.fullmatch(seg[:11] or "") else None
        qv = parse_qs(u.query).get("v", [""])[0]
        return qv[:11] if _YT_ID_RE.fullmatch(qv[:11] or "") else None
    except Exception:
        m = _YT_ID_RE.search(s)
        return m.group(0) if m else None


def fetch_transcript_text(video_id: str, languages: Optional[List[str]] = None) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Returns (full_text, segments). Each segment ~ {'text','start','duration'}.
    Raises RuntimeError with a friendly message if unavailable.
    """
    if not _HAVE_YT_TRANSCRIPT:
        raise RuntimeError(
            "Transcript library not installed. Run: pip install youtube-transcript-api"
        )

    langs = languages or ["en", "en-US", "en-GB", "en-AU", "en-CA"]
    try:
        # auto-generated captions are included by default
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
    except (NoTranscriptFound, TranscriptsDisabled) as e:
        raise RuntimeError(f"No transcript available for video {video_id}: {e}")
    except Exception as e:
        raise RuntimeError(f"Transcript fetch failed for {video_id}: {e}")

    # Build a readable single blob
    parts: List[str] = []
    for seg in transcript:
        t = (seg.get("text") or "").replace("\n", " ").strip()
        if t:
            parts.append(t)
    full_text = " ".join(parts)
    return full_text, transcript


def _chunk_text(s: str, max_chars: int = 4000) -> List[str]:
    s = s.strip()
    if len(s) <= max_chars:
        return [s]
    # split by sentence-ish boundaries
    chunks: List[str] = []
    cur: List[str] = []
    total = 0
    for sent in re.split(r"(?<=[.!?])\s+", s):
        if total + len(sent) + 1 > max_chars and cur:
            chunks.append(" ".join(cur))
            cur = [sent]
            total = len(sent) + 1
        else:
            cur.append(sent)
            total += len(sent) + 1
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def summarize_transcript_with_llm(
    *,
    video_id: str,
    transcript_text: str,
    style: str = "auto",
    model_key: Optional[str] = None,
    provider: str = "openai",
) -> str:
    """
    Map-reduce summarization to stay under context limits.
    style: auto|bullets|chapters|qa
    """
    mk = model_key or getattr(settings, "DEFAULT_MODEL", "gpt-4o-mini")
    chunks = _chunk_text(transcript_text, max_chars=int(getattr(settings, "YT_SUMMARY_CHUNK_CHARS", 3500)))

    map_instr = (
        "Summarize this part of a YouTube video transcript as concise bullet points. "
        "Preserve any concrete numbers, APIs, function names. Avoid fluff."
        if style in {"auto", "bullets"} else
        "Produce a time-ordered outline of key sections. Use short headings with 1–2 lines each."
        if style == "chapters" else
        "Extract a compact Q&A: list likely viewer questions and brief answers from the content."
        if style == "qa" else
        "Summarize concisely."
    )

    partials: List[str] = []
    for i, ch in enumerate(chunks, 1):
        prompt = f"{map_instr}\n\n[TRANSCRIPT PART {i}/{len(chunks)}]\n{ch}"
        partial = ask_model([{"role": "user", "content": prompt}], model_key=mk)
        partials.append(partial.strip())

    reduce_prompt = (
        "Merge the following partial summaries into a single, non-repetitive summary.\n"
        "Return ~10–14 bullet points with crisp phrasing. Do not include raw URLs.\n\n"
        + "\n\n---\n\n".join(partials)
    )

    if style == "chapters":
        reduce_prompt = (
            "Merge the partial outlines into a single chaptered outline. "
            "Return 6–12 sections, each with a short title and 1–2 lines of detail. "
            "Do not fabricate timestamps.\n\n" + "\n\n---\n\n".join(partials)
        )
    elif style == "qa":
        reduce_prompt = (
            "Merge the partial Q&A into a single Q&A list (6–10 items). "
            "Questions should be natural; answers concise and accurate.\n\n"
            + "\n\n---\n\n".join(partials)
        )

    final_summary = ask_model([{"role": "user", "content": reduce_prompt}], model_key=mk)
    return final_summary.strip()
