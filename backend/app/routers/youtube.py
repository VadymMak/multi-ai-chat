# app/routers/youtube.py
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Union
from sqlalchemy.orm import Session

from app.memory.db import get_db
from app.memory.manager import MemoryManager
from app.services.youtube_sevice import perform_youtube_search  # (typo matches project)

router = APIRouter(tags=["YouTube"])

class YouTubeResult(BaseModel):
    title: str
    videoId: str
    url: str
    description: str

@router.get("/youtube/search", response_model=List[YouTubeResult])
def youtube_search(
    q: str = Query(..., description="YouTube search query"),
    role_id: int = Query(..., description="Role ID for memory logging"),
    project_id: Union[int, str] = Query(..., description="Project ID for memory logging"),
    db: Session = Depends(get_db),
):
    try:
        memory = MemoryManager(db)
        block, hits = perform_youtube_search(str(q), memory, int(role_id), str(project_id))
        return hits  # matches YouTubeResult
    except HTTPException:
        raise
    except Exception as e:
        print(f"[YouTube route error] {e}")
        raise HTTPException(status_code=500, detail="YouTube search failed")
