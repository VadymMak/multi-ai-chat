import os
import requests
from urllib.parse import urlencode

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

def search_youtube(query: str, max_results: int = 3):
    if not YOUTUBE_API_KEY:
        raise EnvironmentError("Missing YOUTUBE_API_KEY in environment")

    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "key": YOUTUBE_API_KEY
    }

    response = requests.get(f"{YOUTUBE_SEARCH_URL}?{urlencode(params)}")
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("items", []):
        video_id = item["id"]["videoId"]
        title = item["snippet"]["title"]
        thumbnail = item["snippet"]["thumbnails"]["default"]["url"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        results.append({
            "title": title,
            "url": video_url,
            "thumbnail": thumbnail
        })

    return results
