# app/routers/youtube.py

from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel
from typing import List

from app.memory.db import get_db
from app.memory.manager import MemoryManager
from app.services.youtube_sevice import perform_youtube_search

router = APIRouter()

class YouTubeResult(BaseModel):
    title: str
    videoId: str
    url: str
    description: str

@router.get("/youtube/search", response_model=List[YouTubeResult])
def youtube_search(
    q: str = Query(..., description="YouTube search query"),
    role: str = Query(..., description="Memory role name or ID"),
    db=Depends(get_db)
):
    memory = MemoryManager(db=db)
    block, hits = perform_youtube_search(q, memory, role)
    return hits
