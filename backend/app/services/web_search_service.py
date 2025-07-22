import re
import wikipedia
from typing import List

def clean_query(query: str, max_length: int = 180) -> str:
    """
    Removes special characters and trims the query to a max length.
    """
    query = re.sub(r"[^a-zA-Z0-9\s]", "", query)
    return query.strip()[:max_length]


def extract_keywords_fallback(query: str) -> str:
    """
    Fallback keyword extraction. If no keywords match, return trimmed cleaned query.
    """
    domain_terms = {
        "logarithm", "log", "ln", "base", "e", "math", "mathematics",
        "function", "exponent", "natural", "definition", "properties",
        "compound", "interest", "population", "modeling", "growth", "calculus",
        "physics", "finance", "derivative", "integral", "science", "biology",
        "rate", "decay", "frontend", "accessibility", "design", "web",
        "contactor", "motor", "electrical", "relay", "voltage",
        "ai", "gpu", "nvidia", "model", "architecture", "comparison", "transformer",
        "language", "openai", "claude", "chatbot", "multimodal"
    }

    words = query.lower().split()
    keywords = [word for word in words if word in domain_terms]
    fallback = " ".join(keywords[:6])

    if not fallback:
        fallback = clean_query(query, max_length=80)
        print(f"[Web] No matching domain keywords. Fallback to cleaned: '{fallback}'")
    else:
        print(f"[Web] Fallback keyword query: '{fallback}'")

    return fallback


def perform_web_search(query: str, max_results: int = 3) -> List[dict]:
    """
    Performs a Wikipedia search and returns up to `max_results` relevant page summaries.
    Falls back to keyword-based search if initial query fails.
    """
    try:
        cleaned_query = clean_query(query)
        print(f"[Web] Cleaned query: '{cleaned_query}'")

        # First search attempt
        page_titles = wikipedia.search(cleaned_query, results=max_results)
        search_query = cleaned_query

        # Fallback #1: keyword-based
        if not page_titles:
            fallback_query = extract_keywords_fallback(query)
            page_titles = wikipedia.search(fallback_query, results=max_results)
            search_query = fallback_query

        # Fallback #2: remove voltage units like 220V
        if not page_titles and re.search(r"\b\d+V\b", query):
            stripped_query = re.sub(r"\b\d+V\b", "", query).strip()
            print(f"[Web] Retrying stripped query: '{stripped_query}'")
            page_titles = wikipedia.search(stripped_query, results=max_results)
            search_query = stripped_query

        results = []
        for title in page_titles:
            try:
                page = wikipedia.page(title)
                results.append({
                    "title": page.title,
                    "url": page.url,
                    "snippet": page.summary[:300].strip() + "..."
                })
            except (wikipedia.exceptions.DisambiguationError, wikipedia.exceptions.PageError):
                continue

        # ✅ Final fallback: return Google search query
        if not results:
            print("[Web] ❗ No readable pages found. Returning fallback search link.")
            return [{
                "title": "No relevant web articles found",
                "snippet": "Try searching this query manually:",
                "url": f"https://www.google.com/search?q={search_query.replace(' ', '+')}"
            }]

        return results

    except Exception as e:
        print(f"[Wikipedia Web Search Error] {e} | Query: {query}")
        return [{
            "title": "Wikipedia search error",
            "url": "https://en.wikipedia.org/",
            "snippet": "An error occurred during the web search. Try again later or search manually on Wikipedia."
        }]
