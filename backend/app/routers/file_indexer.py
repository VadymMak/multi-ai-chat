# File: backend/app/routers/file_indexer.py
"""
File Indexer API - Index and search project files using pgvector

Endpoints:
- POST /index/{project_id} - Index all files from Git
- GET /search/{project_id} - Semantic search in files
- GET /stats/{project_id} - Get indexing statistics
- GET /file/{project_id}/{file_path} - Get indexed file content
- DELETE /index/{project_id} - Delete project index
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging
import hashlib
import json
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.memory.db import get_db
from app.memory.models import Project
from app.deps import get_current_user
from app.services.file_indexer import FileIndexer, SUPPORTED_EXTENSIONS, should_skip_file, extract_metadata
from app.services import vector_service
from datetime import datetime

from app.models import (
    IndexProjectResponse,
    SearchResult,
    SearchResponse,
    ProjectStats,
    FileContentResponse,
    LocalFile,
    IndexLocalFilesRequest,
    IndexLocalFilesResponse,
    ReindexFileRequest,
    ReindexFileResponse,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/file-indexer", tags=["file-indexer"])

# ====================================================================
# ENDPOINTS
# ====================================================================

@router.post("/index/{project_id}", response_model=IndexProjectResponse)
async def index_project(
    project_id: int,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Force reindex all files"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Index all files from project's Git repository.
    
    This is an async operation - indexing happens in background.
    Check /stats/{project_id} to monitor progress.
    
    Args:
        project_id: Project ID to index
        force: If true, reindex all files even if unchanged
    """
    logger.info(f"🔍 Index request for project {project_id} (force={force})")
    
    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    if not project.git_url:
        raise HTTPException(400, "Project has no Git URL. Link a repository first.")
    
    # Start background indexing
    background_tasks.add_task(
        _index_project_background,
        project_id=project_id,
        force_reindex=force
    )
    
    return IndexProjectResponse(
        success=True,
        project_id=project_id,
        message=f"Indexing started for {project.name}. Check /stats/{project_id} for progress."
    )


async def _index_project_background(project_id: int, force_reindex: bool):
    """Background task to index project"""
    from app.memory.db import SessionLocal
    
    db = SessionLocal()
    try:
        indexer = FileIndexer(db)
        stats = await indexer.index_project(project_id, force_reindex=force_reindex)
        logger.info(f"✅ Background indexing complete for project {project_id}: {stats}")
    except Exception as e:
        logger.exception(f"❌ Background indexing failed for project {project_id}: {e}")
    finally:
        db.close()


@router.post("/index-sync/{project_id}", response_model=IndexProjectResponse)
async def index_project_sync(
    project_id: int,
    force: bool = Query(False, description="Force reindex all files"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Index project files SYNCHRONOUSLY (waits for completion).
    
    Use this for small projects or when you need immediate results.
    For large projects, use /index/{project_id} instead.
    """
    logger.info(f"🔍 Sync index request for project {project_id}")
    
    # Verify project
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    if not project.git_url:
        raise HTTPException(400, "Project has no Git URL")
    
    try:
        indexer = FileIndexer(db)
        stats = await indexer.index_project(project_id, force_reindex=force)
        
        return IndexProjectResponse(
            success=True,
            project_id=project_id,
            message=f"Indexed {stats['indexed']} files",
            stats=stats
        )
    except Exception as e:
        logger.exception(f"Indexing failed: {e}")
        raise HTTPException(500, f"Indexing failed: {str(e)}")


@router.get("/search/{project_id}", response_model=SearchResponse)
async def search_files(
    project_id: int,
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(5, ge=1, le=20, description="Max results"),
    language: Optional[str] = Query(None, description="Filter by language"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Search files by semantic similarity.
    
    Examples:
    - q="authentication" → finds auth-related files
    - q="error handling" → finds error handler files
    - q="API client" → finds API-related code
    
    Args:
        project_id: Project ID to search in
        q: Search query
        limit: Maximum number of results (1-20)
        language: Filter by language (e.g., "typescript", "python")
    """
    logger.info(f"🔍 Search: project={project_id}, query='{q}', limit={limit}")
    
    # Verify project access
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    try:
        indexer = FileIndexer(db)
        results = await indexer.search_files(
            project_id=project_id,
            query=q,
            limit=limit,
            language=language
        )
        
        return SearchResponse(
            project_id=project_id,
            query=q,
            results=[SearchResult(**r) for r in results],
            total_results=len(results)
        )
    except Exception as e:
        logger.exception(f"Search failed: {e}")
        raise HTTPException(500, f"Search failed: {str(e)}")


@router.get("/stats/{project_id}", response_model=ProjectStats)
async def get_project_stats(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get indexing statistics for a project.
    
    Returns:
    - Total indexed files
    - Number of languages
    - Total lines of code
    - Last indexed time
    - Files by language breakdown
    """
    # Verify project access
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    try:
        indexer = FileIndexer(db)
        stats = await indexer.get_project_stats(project_id)
        
        return ProjectStats(
            project_id=project_id,
            **stats
        )
    except Exception as e:
        logger.exception(f"Failed to get stats: {e}")
        raise HTTPException(500, f"Failed to get stats: {str(e)}")


@router.get("/file/{project_id}/{file_path:path}", response_model=FileContentResponse)
async def get_file_content(
    project_id: int,
    file_path: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get content of an indexed file.
    
    Args:
        project_id: Project ID
        file_path: Full file path (e.g., "src/extension.ts")
    """
    # Verify project access
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    try:
        indexer = FileIndexer(db)
        content = await indexer.get_file_content(project_id, file_path)
        
        if content is None:
            raise HTTPException(404, f"File not indexed: {file_path}")
        
        # Get file info
        from sqlalchemy import text
        file_info = db.execute(text("""
            SELECT language, line_count
            FROM file_embeddings
            WHERE project_id = :project_id AND file_path = :file_path
        """), {"project_id": project_id, "file_path": file_path}).fetchone()
        
        return FileContentResponse(
            project_id=project_id,
            file_path=file_path,
            content=content,
            language=file_info[0] if file_info else None,
            line_count=file_info[1] if file_info else 0
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get file: {e}")
        raise HTTPException(500, f"Failed to get file: {str(e)}")


@router.delete("/index/{project_id}")
async def delete_project_index(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete all indexed files for a project.
    
    Use this when:
    - Changing Git repository
    - Project is deleted
    - Need to fully reindex
    """
    # Verify project access
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    try:
        indexer = FileIndexer(db)
        deleted_count = await indexer.delete_project_index(project_id)
        
        return {
            "success": True,
            "project_id": project_id,
            "deleted_files": deleted_count,
            "message": f"Deleted {deleted_count} indexed files"
        }
    except Exception as e:
        logger.exception(f"Failed to delete index: {e}")
        raise HTTPException(500, f"Failed to delete index: {str(e)}")
    
# ====================================================================
# LOCAL FILES INDEXING (for VS Code Extension)
# ====================================================================

@router.post("/index-local", response_model=IndexLocalFilesResponse)
async def index_local_files(
    request: IndexLocalFilesRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Index files from local filesystem (sent by VS Code Extension).
    
    This endpoint does NOT require git_url - files are sent directly.
    
    Args:
        project_id: Project ID
        files: List of files with path and content
    """
    logger.info(f"📂 Local index request: project={request.project_id}, files={len(request.files)}")
    
    # Verify project access
    project = db.query(Project).filter(
        Project.id == request.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    # Index files
    stats = {"indexed": 0, "skipped": 0, "errors": 0}
    
    for file_data in request.files:
        try:
            # Get language from extension
            language = None
            for ext, lang in SUPPORTED_EXTENSIONS.items():
                if file_data.path.endswith(ext):
                    language = lang
                    break
            
            if not language:
                stats["skipped"] += 1
                continue
            
            # Skip files matching skip patterns
            if should_skip_file(file_data.path):
                stats["skipped"] += 1
                continue
            
            # Compute hash
            content_hash = hashlib.sha256(file_data.content.encode("utf-8")).hexdigest()
            
            # Check if unchanged
            existing = db.execute(text("""
                SELECT content_hash FROM file_embeddings
                WHERE project_id = :project_id AND file_path = :file_path
            """), {"project_id": request.project_id, "file_path": file_data.path}).fetchone()
            
            if existing and existing[0] == content_hash:
                stats["skipped"] += 1
                continue
            
            # Extract metadata
            metadata = extract_metadata(file_data.content, language)
            
            # Generate embedding
            embedding_text = f"""
File: {file_data.path}
Language: {language}
Classes: {', '.join(metadata.get('classes', []))}
Functions: {', '.join(metadata.get('functions', []))}
Imports: {', '.join(metadata.get('imports', []))}

{file_data.content[:8000]}
""".strip()
            
            embedding = vector_service.create_embedding(embedding_text)
            
            # File info
            file_name = file_data.path.split("/")[-1].split("\\")[-1]
            line_count = file_data.content.count("\n") + 1
            file_size = len(file_data.content.encode("utf-8"))
            
            # Upsert
            db.execute(text("""
                INSERT INTO file_embeddings 
                (project_id, file_path, file_name, language, content, content_hash,
                 file_size, line_count, embedding, metadata, indexed_at, updated_at)
                VALUES 
                (:project_id, :file_path, :file_name, :language, :content, :content_hash,
                 :file_size, :line_count, :embedding, :metadata, :now, :now)
                ON CONFLICT (project_id, file_path) 
                DO UPDATE SET
                    content = EXCLUDED.content,
                    content_hash = EXCLUDED.content_hash,
                    file_size = EXCLUDED.file_size,
                    line_count = EXCLUDED.line_count,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    updated_at = EXCLUDED.updated_at
            """), {
                "project_id": request.project_id,
                "file_path": file_data.path,
                "file_name": file_name,
                "language": language,
                "content": file_data.content,
                "content_hash": content_hash,
                "file_size": file_size,
                "line_count": line_count,
                "embedding": embedding,
                "metadata": json.dumps(metadata),
                "now": datetime.utcnow()
            })
            db.commit()
            
            stats["indexed"] += 1
            logger.debug(f"  ✅ {file_data.path}")
            
        except Exception as e:
            stats["errors"] += 1
            logger.error(f"  ❌ {file_data.path}: {e}")
    
    logger.info(f"✅ Local indexing complete: {stats}")

    # ✅ UPDATE PROJECT STATUS (NEW)
    if stats["indexed"] > 0:
        # Get total files count
        total_files = db.execute(text("""
            SELECT COUNT(*) FROM file_embeddings
            WHERE project_id = :project_id
        """), {"project_id": request.project_id}).scalar()
        
        # Update project
        db.execute(text("""
            UPDATE projects 
            SET indexed_at = :now, files_count = :count
            WHERE id = :project_id
        """), {
            "now": datetime.utcnow(),
            "count": total_files,
            "project_id": request.project_id
        })
        db.commit()
        logger.info(f"  📊 Updated project status: {total_files} files indexed")
    
    return IndexLocalFilesResponse(
        success=True,
        project_id=request.project_id,
        indexed=stats["indexed"],
        skipped=stats["skipped"],
        errors=stats["errors"],
        message=f"Indexed {stats['indexed']} files, skipped {stats['skipped']}, errors {stats['errors']}"
    )


@router.get("/find-related/{project_id}")
async def find_related_files(
    project_id: int,
    file_path: str = Query(..., description="Current file path"),
    limit: int = Query(5, ge=1, le=10),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Find files related to a specific file.
    
    Uses the file's embedding to find similar files.
    Useful for understanding dependencies and related code.
    
    Args:
        project_id: Project ID
        file_path: Path of the file to find related files for
        limit: Max results
    """
    # Verify project access
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    try:
        from sqlalchemy import text
        
        # Get embedding of target file
        result = db.execute(text("""
            SELECT embedding FROM file_embeddings
            WHERE project_id = :project_id AND file_path = :file_path
        """), {"project_id": project_id, "file_path": file_path}).fetchone()
        
        if not result or not result[0]:
            raise HTTPException(404, f"File not indexed: {file_path}")
        
        # Convert embedding to PostgreSQL vector string format
        # This avoids the :: conflict with SQLAlchemy parameters
        target_embedding = result[0]
        if isinstance(target_embedding, str):
            embedding_str = target_embedding
        else:
            # It's a list/array from pgvector
            embedding_str = "[" + ",".join(str(x) for x in target_embedding) + "]"
        
        # Find similar files (excluding the target file)
        # Embed vector directly in SQL to avoid :param::vector syntax conflict
        sql = f"""
            SELECT 
                file_path, file_name, language, line_count,
                1 - (embedding <=> '{embedding_str}'::vector) AS similarity
            FROM file_embeddings
            WHERE project_id = :project_id
              AND file_path != :file_path
              AND embedding IS NOT NULL
            ORDER BY embedding <=> '{embedding_str}'::vector
            LIMIT :limit
        """
        
        related = db.execute(text(sql), {
            "project_id": project_id,
            "file_path": file_path,
            "limit": limit
        }).fetchall()
        
        return {
            "project_id": project_id,
            "source_file": file_path,
            "related_files": [
                {
                    "file_path": r[0],
                    "file_name": r[1],
                    "language": r[2],
                    "line_count": r[3],
                    "similarity": round(r[4], 4)
                }
                for r in related
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to find related files: {e}")
        raise HTTPException(500, f"Failed: {str(e)}")
    

# ====================================================================
# INCREMENTAL RE-INDEXING (NEW)
# ====================================================================

@router.post("/reindex-file", response_model=ReindexFileResponse)
async def reindex_single_file(
    request: ReindexFileRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Re-index a single file (incremental update).
    
    Much faster than full re-index!
    Used by VS Code Extension when file changes are detected.
    
    Args:
        project_id: Project ID
        file_path: File path (relative to project root)
        content: New file content
    """
    logger.info(f"🔄 Re-index file: project={request.project_id}, path={request.file_path}")
    
    # Verify project access
    project = db.query(Project).filter(
        Project.id == request.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    try:
        # Get language from extension
        language = None
        for ext, lang in SUPPORTED_EXTENSIONS.items():
            if request.file_path.endswith(ext):
                language = lang
                break
        
        if not language:
            raise HTTPException(400, f"Unsupported file type: {request.file_path}")
        
        # Compute hash
        content_hash = hashlib.sha256(request.content.encode("utf-8")).hexdigest()
        
        # Extract metadata
        metadata = extract_metadata(request.content, language)
        
        # Generate embedding
        embedding_text = f"""
File: {request.file_path}
Language: {language}
Classes: {', '.join(metadata.get('classes', []))}
Functions: {', '.join(metadata.get('functions', []))}
Imports: {', '.join(metadata.get('imports', []))}

{request.content[:8000]}
""".strip()
        
        embedding = vector_service.create_embedding(embedding_text)
        
        # File info
        file_name = request.file_path.split("/")[-1].split("\\")[-1]
        line_count = request.content.count("\n") + 1
        file_size = len(request.content.encode("utf-8"))
        
        # Check if file exists
        existing = db.execute(text("""
            SELECT id FROM file_embeddings
            WHERE project_id = :project_id AND file_path = :file_path
        """), {"project_id": request.project_id, "file_path": request.file_path}).fetchone()
        
        if existing:
            # Update existing
            db.execute(text("""
                UPDATE file_embeddings SET
                    content = :content,
                    content_hash = :content_hash,
                    file_size = :file_size,
                    line_count = :line_count,
                    embedding = :embedding,
                    metadata = :metadata,
                    updated_at = :now
                WHERE project_id = :project_id AND file_path = :file_path
            """), {
                "content": request.content,
                "content_hash": content_hash,
                "file_size": file_size,
                "line_count": line_count,
                "embedding": embedding,
                "metadata": json.dumps(metadata),
                "now": datetime.utcnow(),
                "project_id": request.project_id,
                "file_path": request.file_path
            })
            embedding_id = existing[0]
            logger.info(f"  ✅ Updated: {request.file_path}")
        else:
            # Insert new
            result = db.execute(text("""
                INSERT INTO file_embeddings 
                (project_id, file_path, file_name, language, content, content_hash,
                 file_size, line_count, embedding, metadata, indexed_at, updated_at)
                VALUES 
                (:project_id, :file_path, :file_name, :language, :content, :content_hash,
                 :file_size, :line_count, :embedding, :metadata, :now, :now)
                RETURNING id
            """), {
                "project_id": request.project_id,
                "file_path": request.file_path,
                "file_name": file_name,
                "language": language,
                "content": request.content,
                "content_hash": content_hash,
                "file_size": file_size,
                "line_count": line_count,
                "embedding": embedding,
                "metadata": json.dumps(metadata),
                "now": datetime.utcnow()
            })
            embedding_id = result.fetchone()[0]
            logger.info(f"  ✅ Inserted: {request.file_path}")
        
        db.commit()
        
        # ✅ UPDATE PROJECT indexed_at (NEW)
        db.execute(text("""
            UPDATE projects 
            SET indexed_at = :now
            WHERE id = :project_id
        """), {
            "now": datetime.utcnow(),
            "project_id": request.project_id
        })
        db.commit()
        
        return ReindexFileResponse(
            success=True,
            project_id=request.project_id,
            file_path=request.file_path,
            message="File re-indexed successfully",
            embedding_id=embedding_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to re-index file: {e}")
        raise HTTPException(500, f"Re-indexing failed: {str(e)}")