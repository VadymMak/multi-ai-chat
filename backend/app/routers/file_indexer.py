# File: backend/app/routers/file_indexer.py
"""
File Indexer API - Index and search project files using pgvector

Endpoints:
- POST /index/{project_id} - Index all files from Git
- GET /search/{project_id} - Semantic search in files
- GET /stats/{project_id} - Get indexing statistics (includes dependencies!)
- GET /file/{project_id}/{file_path} - Get indexed file content
- DELETE /index/{project_id} - Delete project index
- POST /index-local - Index local files (saves dependencies!)
- GET /dependencies/{project_id}/{file_path} - Get file dependencies (NEW!)
- GET /dependents/{project_id}/{file_path} - Get file dependents (NEW!)
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
from app.services.file_indexer import (
    FileIndexer, 
    SUPPORTED_EXTENSIONS, 
    should_skip_file, 
    extract_metadata,
    save_file_dependencies,  # NEW!
)
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


@router.get("/stats/{project_id}")
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
    - Dependencies statistics (NEW!)
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
        
        return {
            "project_id": project_id,
            **stats
        }
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
# NEW: DEPENDENCY ENDPOINTS (Phase 2)
# ====================================================================

@router.get("/dependencies/{project_id}/{file_path:path}")
async def get_file_dependencies(
    project_id: int,
    file_path: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all files that this file imports (outgoing dependencies).
    
    Example: /dependencies/18/backend/app/routers/vscode.py
    Returns: [vector_service.py, memory/models.py, ...]
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
        deps = await indexer.get_file_dependencies(project_id, file_path)
        
        return {
            "project_id": project_id,
            "file_path": file_path,
            "dependencies": deps,
            "count": len(deps)
        }
    except Exception as e:
        logger.exception(f"Failed to get dependencies: {e}")
        raise HTTPException(500, f"Failed: {str(e)}")


@router.get("/dependents/{project_id}/{file_path:path}")
async def get_file_dependents(
    project_id: int,
    file_path: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all files that import this file (incoming dependencies).
    
    Example: /dependents/18/backend/app/services/vector_service.py
    Returns: [vscode.py, file_indexer.py, ...] - files that use vector_service
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
        deps = await indexer.get_file_dependents(project_id, file_path)
        
        return {
            "project_id": project_id,
            "file_path": file_path,
            "dependents": deps,
            "count": len(deps)
        }
    except Exception as e:
        logger.exception(f"Failed to get dependents: {e}")
        raise HTTPException(500, f"Failed: {str(e)}")


# ====================================================================
# LOCAL FILES INDEXING (for VS Code Extension) - UPDATED WITH DEPENDENCIES
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
    NOW ALSO SAVES FILE DEPENDENCIES!
    
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
    stats = {"indexed": 0, "skipped": 0, "errors": 0, "dependencies_saved": 0}
    
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
            
            # Upsert file_embeddings
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
            
            # ============================================================
            # NEW: SAVE FILE DEPENDENCIES
            # ============================================================
            if metadata.get("imports"):
                deps_count = save_file_dependencies(
                    project_id=request.project_id,
                    source_file=file_data.path,
                    imports=metadata["imports"],
                    language=language,
                    db=db
                )
                stats["dependencies_saved"] += deps_count
            # ============================================================
            
            db.commit()
            
            stats["indexed"] += 1
            logger.debug(f"  ✅ {file_data.path}")
            
        except Exception as e:
            stats["errors"] += 1
            logger.error(f"  ❌ {file_data.path}: {e}")
    
    logger.info(f"✅ Local indexing complete: {stats}")

    # ✅ UPDATE PROJECT STATUS
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
        logger.info(f"  📊 Updated project status: {total_files} files, {stats['dependencies_saved']} deps")
    
    return IndexLocalFilesResponse(
        success=True,
        project_id=request.project_id,
        indexed=stats["indexed"],
        skipped=stats["skipped"],
        errors=stats["errors"],
        message=f"Indexed {stats['indexed']} files ({stats['dependencies_saved']} deps), skipped {stats['skipped']}, errors {stats['errors']}"
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
        # Get embedding of target file
        result = db.execute(text("""
            SELECT embedding FROM file_embeddings
            WHERE project_id = :project_id AND file_path = :file_path
        """), {"project_id": project_id, "file_path": file_path}).fetchone()
        
        if not result or not result[0]:
            raise HTTPException(404, f"File not indexed: {file_path}")
        
        # Convert embedding to PostgreSQL vector string format
        target_embedding = result[0]
        if isinstance(target_embedding, str):
            embedding_str = target_embedding
        else:
            embedding_str = "[" + ",".join(str(x) for x in target_embedding) + "]"
        
        # Find similar files (excluding the target file)
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
# INCREMENTAL RE-INDEXING - UPDATED WITH DEPENDENCIES
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
    NOW ALSO UPDATES FILE DEPENDENCIES!
    
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
        
        # ============================================================
        # NEW: UPDATE FILE DEPENDENCIES
        # ============================================================
        deps_count = 0
        if metadata.get("imports"):
            deps_count = save_file_dependencies(
                project_id=request.project_id,
                source_file=request.file_path,
                imports=metadata["imports"],
                language=language,
                db=db
            )
            logger.info(f"  💾 Updated {deps_count} dependencies")
        # ============================================================
        
        db.commit()
        
        # UPDATE PROJECT indexed_at
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
            message=f"File re-indexed successfully ({deps_count} deps)",
            embedding_id=embedding_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to re-index file: {e}")
        raise HTTPException(500, f"Re-indexing failed: {str(e)}")
    
# ====================================================================
# DEPENDENCY GRAPH FOR VISUALIZATION (Phase 1.8)
# ====================================================================

@router.get("/dependency-graph/{project_id}")
async def get_dependency_graph(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get full dependency graph for visualization.
    
    Returns:
    - nodes: All files with metadata
    - edges: All import relationships
    - tree: Formatted tree string for AI context
    - stats: Summary statistics
    
    Used by:
    - Web App (React Flow visualization)
    - VS Code Extension (Mermaid diagram)
    - AI Context (replaces print_tree.py!)
    """
    # Verify project access
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    try:
        # 1. Get all files (nodes)
        files_result = db.execute(text("""
            SELECT 
                id, file_path, file_name, language, 
                line_count, file_size, metadata
            FROM file_embeddings
            WHERE project_id = :project_id
            ORDER BY file_path
        """), {"project_id": project_id}).fetchall()
        
        nodes = []
        file_paths = set()
        
        for row in files_result:
            file_path = row[1]
            file_paths.add(file_path)
            
            # Determine node type based on path
            node_type = "file"
            if "/components/" in file_path or "/pages/" in file_path:
                node_type = "component"
            elif "/services/" in file_path or "/api/" in file_path:
                node_type = "service"
            elif "/utils/" in file_path or "/helpers/" in file_path:
                node_type = "utility"
            elif "/models/" in file_path or "/types/" in file_path:
                node_type = "model"
            elif "/routers/" in file_path or "/routes/" in file_path:
                node_type = "router"
            
            nodes.append({
                "id": str(row[0]),
                "file_path": file_path,
                "label": row[2],  # file_name
                "language": row[3],
                "line_count": row[4] or 0,
                "file_size": row[5] or 0,
                "type": node_type,
                "metadata": row[6] if row[6] else {}
            })
        
        # 2. Get all dependencies (edges)
        deps_result = db.execute(text("""
            SELECT 
                fd.source_file, fd.target_file, fd.dependency_type,
                fe_source.id as source_id, fe_target.id as target_id
            FROM file_dependencies fd
            LEFT JOIN file_embeddings fe_source 
                ON fe_source.project_id = fd.project_id 
                AND fe_source.file_path = fd.source_file
            LEFT JOIN file_embeddings fe_target 
                ON fe_target.project_id = fd.project_id 
                AND fe_target.file_path = fd.target_file
            WHERE fd.project_id = :project_id
            ORDER BY fd.source_file
        """), {"project_id": project_id}).fetchall()
        
        edges = []
        for row in deps_result:
            if row[3] and row[4]:  # Both source and target exist
                edges.append({
                    "source": str(row[3]),
                    "target": str(row[4]),
                    "source_path": row[0],
                    "target_path": row[1],
                    "type": row[2] or "import"
                })
        
        # 3. Build tree string for AI context
        tree_lines = [f"Project: {project.name}", ""]
        
        # Group files by directory
        dirs = {}
        for node in nodes:
            parts = node["file_path"].split("/")
            if len(parts) > 1:
                dir_path = "/".join(parts[:-1])
            else:
                dir_path = "."
            
            if dir_path not in dirs:
                dirs[dir_path] = []
            dirs[dir_path].append(node)
        
        # Build tree
        for dir_path in sorted(dirs.keys()):
            tree_lines.append(f"📁 {dir_path}/")
            for node in sorted(dirs[dir_path], key=lambda x: x["label"]):
                deps_count = len([e for e in edges if e["source_path"] == node["file_path"]])
                tree_lines.append(f"  ├── {node['label']} ({node['language']}, {node['line_count']} lines, {deps_count} imports)")
        
        tree_string = "\n".join(tree_lines)
        
        # 4. Calculate stats
        stats = {
            "total_files": len(nodes),
            "total_dependencies": len(edges),
            "languages": list(set(n["language"] for n in nodes if n["language"])),
            "total_lines": sum(n["line_count"] for n in nodes),
        }
        
        logger.info(f"📊 Dependency graph: {stats['total_files']} nodes, {stats['total_dependencies']} edges")
        
        return {
            "project_id": project_id,
            "project_name": project.name,
            "nodes": nodes,
            "edges": edges,
            "tree": tree_string,
            "stats": stats
        }
        
    except Exception as e:
        logger.exception(f"Failed to get dependency graph: {e}")
        raise HTTPException(500, f"Failed: {str(e)}")