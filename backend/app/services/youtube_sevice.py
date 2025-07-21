import os, json, re, time
from typing import Tuple, List
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from app.memory.manager import MemoryManager

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    raise RuntimeError("❌  YOUTUBE_API_KEY is missing from .env")

def perform_youtube_search(
    query: str, mem: MemoryManager, role_id: str
) -> Tuple[str, List[dict]]:
    """Return (block-for-LLM, top-3 hits). With context-aware filtering."""
    try:
        yt = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

        # Extract specific term from prompt
        search_match = re.search(r"search for(?: and provide)?(?: 3)?(?: valid)?(?: YouTube links)?(?: with titles and URLs)? specifically about ([\w\s]+)", query, re.IGNORECASE)
        search_query = search_match.group(1) if search_match else query.lower().strip()

        # Apply keyword filters
        if any(kw in query.lower() for kw in ("contactor", "wiring", "electrical", "220v")):
            search_query += " electrical engineering home system -tire -car"
        elif "replace" in query.lower() or "change" in query.lower():
            search_query += " tutorial -tire -car"
        else:
            search_query += " -tire -car"

        resp = yt.search().list(
            part="snippet",
            q=search_query,
            type="video",
            maxResults=10,
            videoCategoryId=27,  # Education/Tech
            order="date",
            publishedAfter="2024-01-01T00:00:00Z"
        ).execute()

        hits = [
            {
                "title": it["snippet"]["title"],
                "videoId": it["id"]["videoId"],
                "url": f"https://www.youtube.com/watch?v={it['id']['videoId']}",
                "description": it["snippet"]["description"][:200] if it["snippet"]["description"] else ""
            } for it in resp["items"]
            if not it["id"]["videoId"].startswith("s")  # Skip Shorts
        ][:3]

        if not hits:
            hits = [
                {
                    "title": "No specific results found",
                    "url": f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}",
                    "videoId": "fallback",
                    "description": f"Search YouTube for '{search_query}' manually."
                }
            ] * 3

        raw = f"YouTube search ({query}): {json.dumps(hits)}"
        mem.store_memory(role_id, mem.summarize_messages([raw]), raw)

        block = (
            f"\n\nYouTube search results for **{search_query}**:\n" +
            "\n".join(f"- {h['title']} — {h['url']}" for h in hits) +
            "\nPlease leverage these when crafting your answer."
        )
        print("[DEBUG] yt_block len:", len(block), "hits:", len(hits))
        return block, hits

    except HttpError as e:
        print("[DEBUG] YouTube API error:", e)
        return f"\n\nYouTube API Error: {str(e)}", []
    except Exception as e:
        print("[DEBUG] General YouTube error:", e)
        return "", []
