"""
Request and Response models for File Indexer API
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any


# ====================================================================
# FILE INDEXER MODELS
# ====================================================================

class IndexProjectResponse(BaseModel):
    """Response from indexing request"""
    success: bool
    project_id: int
    message: str
    stats: Optional[Dict[str, Any]] = None


class SearchResult(BaseModel):
    """Single search result"""
    id: int
    file_path: str
    file_name: str
    language: Optional[str]
    line_count: int
    similarity: float
    metadata: Dict[str, Any]


class SearchResponse(BaseModel):
    """Response from search request"""
    project_id: int
    query: str
    results: List[SearchResult]
    total_results: int


class ProjectStats(BaseModel):
    """Project indexing statistics"""
    project_id: int
    total_files: int
    languages: int
    total_lines: int
    total_size_kb: float
    last_indexed: Optional[str]
    by_language: Dict[str, int]


class FileContentResponse(BaseModel):
    """Response with file content"""
    project_id: int
    file_path: str
    content: str
    language: Optional[str]
    line_count: int


class LocalFile(BaseModel):
    """Single file from local filesystem"""
    path: str
    content: str


class IndexLocalFilesRequest(BaseModel):
    """Request to index local files"""
    project_id: int
    files: List[LocalFile]


class IndexLocalFilesResponse(BaseModel):
    """Response from local indexing"""
    success: bool
    project_id: int
    indexed: int
    skipped: int
    errors: int
    message: str


# ====================================================================
# NEW: INCREMENTAL RE-INDEXING MODELS
# ====================================================================

class ReindexFileRequest(BaseModel):
    """Request to re-index a single file (incremental update)"""
    project_id: int
    file_path: str
    content: str


class ReindexFileResponse(BaseModel):
    """Response from single file re-indexing"""
    success: bool
    project_id: int
    file_path: str
    message: str
    embedding_id: Optional[int] = None