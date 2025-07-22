import os
import json
import re
from typing import Tuple, List
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from app.memory.manager import MemoryManager

# Load API key
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    raise RuntimeError("❌ YOUTUBE_API_KEY is missing from .env")


def extract_keywords(text: str, max_length: int = 120) -> str:
    """
    Clean the input text and return space-separated keyword string for better search accuracy.
    """
    text = re.sub(r"[^a-zA-Z0-9\s]", "", text)
    words = text.split()
    stopwords = {"the", "and", "for", "with", "a", "an", "in", "to", "of", "by", "on"}
    keywords = [word for word in words if len(word) > 2 and word.lower() not in stopwords]
    return " ".join(keywords[:max_length]).strip()


def build_search_query(original: str) -> str:
    """
    Apply contextual logic to refine YouTube search query.
    """
    cleaned = extract_keywords(original.lower())

    if "gpu" in cleaned or "nvidia" in cleaned or "ai" in cleaned:
        return f"{cleaned} GPU AI benchmark 2025"
    elif "monitor" in cleaned or "screen" in cleaned:
        return f"{cleaned} developer monitor reviews 2025"
    elif "compare" in cleaned or "price" in cleaned or "model" in cleaned:
        return f"{cleaned} updated comparison 2025"
    elif "contactor" in cleaned or "electrical" in cleaned or "220v" in cleaned:
        return f"{cleaned} electrical wiring tutorial"
    elif "dell" in cleaned:
        return f"{cleaned} dell hardware repair guide"
    else:
        return f"{cleaned} technology tutorial"


def search_youtube(query: str, max_results: int = 10) -> List[dict]:
    """
    Execute YouTube search via Google API and return video metadata.
    """
    yt = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    print(f"[YouTube] Searching for: '{query}'")
    response = yt.search().list(
        part="snippet",
        q=query,
        type="video",
        maxResults=max_results,
        videoCategoryId=27,  # Technology category
        order="relevance",
        publishedAfter="2023-01-01T00:00:00Z"
    ).execute()

    return [
        {
            "title": item["snippet"]["title"],
            "videoId": item["id"]["videoId"],
            "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
            "description": item["snippet"].get("description", "")[:200]
        }
        for item in response.get("items", [])
        if item["id"].get("videoId") and not item["id"]["videoId"].startswith("s")
    ]


def perform_youtube_search(
    query: str,
    mem: MemoryManager,
    role_id: str,
    project_id: str
) -> Tuple[str, List[dict]]:
    """
    Perform a YouTube search, optionally retry on no results, and store the findings in memory.
    Returns a Markdown block and structured list of search results.
    """
    try:
        search_query = build_search_query(query)
        hits = search_youtube(search_query)[:3]

        # Retry with fallback if no hits
        if not hits:
            fallback_query = extract_keywords(query)
            hits = search_youtube(fallback_query)[:3]
            search_query = fallback_query

        if not hits:
            print("[YouTube] ❗ No relevant results. Returning fallback link.")
            hits = [{
                "title": "No relevant YouTube results found",
                "videoId": "fallback",
                "url": f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}",
                "description": f"Try this query manually: '{search_query}'"
            }]

        # Log to memory
        raw = f"YouTube search ({query}): {json.dumps(hits, indent=2)}"
        summary = mem.summarize_messages([raw])
        mem.store_memory(
            project_id=project_id,
            role_id=role_id,
            summary=summary,
            raw_text=raw
        )

        block = (
            f"\n\n▶️ **YouTube search results for:** `{search_query}`\n" +
            "\n".join(f"- [{h['title']}]({h['url']})" for h in hits)
        )

        print("[DEBUG] YouTube block len:", len(block), "hits:", len(hits))
        return block, hits

    except HttpError as e:
        print("[YouTube API Error]", e)
        return "\n\n⚠️ YouTube API error.", []

    except Exception as e:
        print("[General YouTube error]", e)
        return "\n\n⚠️ YouTube search failed.", []
