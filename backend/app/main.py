from __future__ import annotations
import asyncio, os, json, time, random, re
from typing import List, Literal, Tuple

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude
from app.memory.db import init_db, get_db
from app.memory.manager import MemoryManager

# Load .env at the very start from the current directory
load_dotenv()  # Assumes .env is in the backend directory

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    raise RuntimeError("❌  YOUTUBE_API_KEY is missing from .env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("❌  OPENAI_API_KEY is missing from .env")

init_db()
app = FastAPI(title="Multi-AI Chat Backend")

# Add logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    request_body = await request.json() if request.headers.get("content-type") == "application/json" else "No body"
    print(f"[DEBUG] [{timestamp}] Request: {request.method} {request.url.path} - Body: {request_body}")
    response = await call_next(request)
    print(f"[DEBUG] [{timestamp}] Response: {response.status_code} for {request.url.path}")
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://multi-ai-chat.onrender.com", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Provider = Literal["openai", "anthropic", "all"]

# ──────────────────────── schema ────────────────────────
class PromptRequest(BaseModel):
    question: str
    provider: Provider
    role_id: str = "default"

class AiResponse(BaseModel):
    provider: str
    answer: str
    details: List[dict]
    youtube_results: List[dict] | None = None

class AiToAiTurnRequest(BaseModel):
    messages: List[dict]
    turn: int
    role_id: str = "default"

# ─────────────────────── helpers ────────────────────────
def validate_messages(msgs: List[dict]) -> List[dict]:
    clean = [m for m in msgs if m.get("content", "").strip()
             and "[Claude Error]" not in m.get("content", "")]
    return clean or [{"role": "user", "content": "Start conversation"}]

async def claude_with_retry(msgs: list[dict], retries: int = 2) -> str:
    for attempt in range(retries + 1):
        ans = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ask_claude(messages=msgs)
        )
        if "[Claude Error]" not in ans or "overloaded" not in ans.lower():
            return ans
        if attempt < retries:
            wait_time = 1.5 + attempt * random.uniform(0.5, 1.5)
            print(f"[DEBUG] Claude retry {attempt + 1}/{retries + 1}, waiting {wait_time}s")
            await asyncio.sleep(wait_time)
    print("[DEBUG] Max retries reached for Claude, returning last attempt")
    return ans

async def perform_youtube_search(
    query: str, mem: MemoryManager, role_id: str
) -> Tuple[str, List[dict]]:
    """Return (block-for-LLM, top-3 hits). With context-aware filtering."""
    try:
        yt = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        
        # Extract specific search term from prompt using regex
        search_match = re.search(r"search for(?: and provide)?(?: 3)?(?: valid)?(?: YouTube links)?(?: with titles and URLs)? specifically about ([\w\s]+)", query, re.IGNORECASE)
        search_query = search_match.group(1) if search_match else query.lower().strip()

        # Refine query with additional context if needed
        if any(kw in query.lower() for kw in ("contactor", "wiring", "electrical", "220v")):
            search_query = f"{search_query} electrical engineering home system -tire -car"
        elif "replace" in query.lower() or "change" in query.lower():
            search_query = f"{search_query} tutorial -tire -car"
        else:
            search_query = f"{search_query} -tire -car"  # General filter to exclude car-related content

        resp = yt.search().list(
            part="snippet",
            q=search_query,
            type="video",
            maxResults=10,
            videoCategoryId=27,  # Education/Tech
            order="date",  # Prioritize recent
            publishedAfter="2024-01-01T00:00:00Z"  # Limit to 2024 onwards
        ).execute()

        hits = [
            {
                "title": it["snippet"]["title"],
                "videoId": it["id"]["videoId"],
                "url": f"https://www.youtube.com/watch?v={it['id']['videoId']}",
                "description": it["snippet"]["description"][:200] if it["snippet"]["description"] else ""
            } for it in resp["items"]
            if not it["id"]["videoId"].startswith("s")  # Exclude shorts
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

def _log(mem: MemoryManager, role: str, q: str, a: str, model: str):
    raw = f"User: {q}\n{model.capitalize()}: {a}"
    mem.store_memory(role, mem.summarize_messages([raw]), raw)

# ───────────────────────── routes ────────────────────────
@app.post("/ask", response_model=AiResponse)
async def ask(req: PromptRequest, db: Session = Depends(get_db)):
    mem = MemoryManager(db)
    context = mem.retrieve_messages(req.role_id, limit=6)

    wants_yt = any(k in req.question.lower() for k in
                   ("youtube", "video", "link"))
    yt_block, yt_hits = await perform_youtube_search(
        req.question, mem, req.role_id) if wants_yt else ("", [])

    history = [{"role": "system", "content": "You are a helpful assistant."},
               *context,
               {"role": "user", "content": req.question}]
    if yt_block or wants_yt:
        history.append({"role": "user", "content": yt_block})

    loop = asyncio.get_event_loop()

    if req.provider == "openai":
        ans = await loop.run_in_executor(None,
                                         lambda: ask_openai(messages=history))
        _log(mem, req.role_id, req.question, ans, "openai")
        return AiResponse(provider="openai",
                          answer=ans,
                          details=[{"model": "openai", "answer": ans}],
                          youtube_results=yt_hits)

    if req.provider == "anthropic":
        ans = await claude_with_retry(validate_messages(history))
        _log(mem, req.role_id, req.question, ans, "anthropic")
        return AiResponse(provider="anthropic",
                          answer=ans,
                          details=[{"model": "anthropic", "answer": ans}],
                          youtube_results=yt_hits)

    if req.provider == "all":
        o_task = loop.run_in_executor(None,
                                      lambda: ask_openai(messages=history))
        c_task = claude_with_retry(validate_messages(history))
        o_ans, c_ans = await asyncio.gather(o_task, c_task)

        combo_prompt = (
            f"Combine these into one accurate answer to '{req.question}' "
            f"(use any YouTube info if available):\n\nOpenAI: {o_ans}\n\nAnthropic: {c_ans}"
        )
        final = await loop.run_in_executor(
            None, lambda: ask_openai(messages=[{"role": "user", "content": combo_prompt}],
                                     model="gpt-4o")
        )

        if wants_yt and yt_hits:
            yt_appendix = "\n\n**YouTube Links (for reference, verify relevance):**\n" + \
                          "\n".join(f"- {h['title']}: {h['url']}" for h in yt_hits) + \
                          "\n*Note: These are provided for informational purposes; ensure content is reliable before acting.*"
            final += yt_appendix
            print("[DEBUG] Appended YouTube links:", yt_appendix)

        _log(mem, req.role_id, req.question, final, "final")

        return AiResponse(provider="all",
                          answer=final,
                          details=[{"model": "openai", "answer": o_ans},
                                   {"model": "anthropic", "answer": c_ans}],
                          youtube_results=yt_hits)

    raise HTTPException(400, "Unknown provider")

@app.post("/ask-ai-to-ai", response_model=AiResponse)
async def ask_ai_to_ai(req: PromptRequest, db: Session = Depends(get_db)):
    mem = MemoryManager(db)
    context = mem.retrieve_messages(req.role_id, limit=6)

    wants = any(w in req.question.lower()
                for w in ("youtube", "video", "link", "tutorial"))
    yt_block, yt_hits = await perform_youtube_search(
        req.question, mem, req.role_id) if wants else ("", [])

    base = [{"role": "system", "content":
             "You are a helpful assistant providing accurate and concise answers."},
            *context,
            {"role": "user", "content": req.question}]
    if yt_block or wants:
        base.append({"role": "user", "content": yt_block})

    loop = asyncio.get_event_loop()
    o_task = loop.run_in_executor(None, lambda: ask_openai(messages=base))
    c_task = claude_with_retry(validate_messages(base))
    o_ans, c_ans = await asyncio.gather(o_task, c_task)

    mixer = (
        f"Combine the following into the best single answer to '{req.question}'. "
        f"Use YouTube info if available:\n\nOpenAI: {o_ans}\n\nAnthropic: {c_ans}"
    )
    final = await loop.run_in_executor(
        None, lambda: ask_openai(messages=[{"role": "user", "content": mixer}],
                                 model="gpt-4o")
    )

    if wants and yt_hits:
        yt_appendix = "\n\n**YouTube Links (for reference, verify relevance):**\n" + \
                      "\n".join(f"- {h['title']}: {h['url']}" for h in yt_hits) + \
                      "\n*Note: These are provided for informational purposes; ensure content is reliable before acting.*"
        final += yt_appendix
        print("[DEBUG] Appended YouTube links:", yt_appendix)

    _log(mem, req.role_id, req.question, final, "final")

    return AiResponse(provider="all",
                      answer=final,
                      details=[{"model": "openai", "answer": o_ans},
                               {"model": "anthropic", "answer": c_ans}],
                      youtube_results=yt_hits)

@app.post("/ask-ai-to-ai-turn")
async def ask_ai_to_ai_turn(req: AiToAiTurnRequest, db: Session = Depends(get_db)):
    if not req.messages:
        raise HTTPException(400, "History empty")

    mem = MemoryManager(db)
    loop = asyncio.get_event_loop()
    last = req.messages[-1]["answer"].strip()

    if req.turn == 0:
        ctx = mem.retrieve_messages(req.role_id, limit=6)
        h = ctx + [{"role": "user", "content": last}]
        ans = await loop.run_in_executor(None, lambda: ask_openai(messages=h))
        req.messages.append({"model": "openai", "answer": ans})
        _log(mem, req.role_id, last, ans, "openai")
        next_t = 1
    else:
        clean = [{"role": "user" if m["model"] == "openai" else "assistant",
                  "content": m["answer"].strip()}
                 for m in req.messages
                 if m["answer"].strip() and "[Claude Error]" not in m["answer"]]
        ans = await claude_with_retry(validate_messages(clean))
        req.messages.append({"model": "anthropic", "answer": ans})
        _log(mem, req.role_id, last, ans, "anthropic")
        next_t = 0

    raw = "\n".join(f"{m['model']}: {m['answer']}" for m in req.messages)
    mem.store_memory(req.role_id, mem.summarize_messages([raw]), raw)

    return {"conversation": req.messages, "next_turn": next_t}