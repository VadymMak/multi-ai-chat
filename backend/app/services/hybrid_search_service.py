"""
Hybrid Search Service - Combines Semantic, Lexical (FTS), and Graph search.

This service implements the "Misha Brain" concept:
- Semantic (pgvector): Find files by meaning similarity
- Lexical (FTS): Find files by exact word matches  
- Graph (dependencies): Find related files via imports

The orchestrator combines results with configurable weights.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging

from app.services import vector_service

logger = logging.getLogger(__name__)


# ====================================================================
# CONFIGURATION
# ====================================================================

@dataclass
class HybridSearchConfig:
    """Configuration for hybrid search weights"""
    semantic_weight: float = 0.5   # pgvector similarity
    fts_weight: float = 0.3        # Full Text Search
    graph_weight: float = 0.2      # Dependencies
    
    # Search limits
    semantic_limit: int = 15
    fts_limit: int = 15
    graph_limit: int = 10


# Presets for different use cases
SEARCH_PRESETS = {
    "default": HybridSearchConfig(),
    "code": HybridSearchConfig(semantic_weight=0.4, fts_weight=0.3, graph_weight=0.3),
    "exact": HybridSearchConfig(semantic_weight=0.2, fts_weight=0.7, graph_weight=0.1),
    "related": HybridSearchConfig(semantic_weight=0.3, fts_weight=0.2, graph_weight=0.5),
}


# ====================================================================
# FTS SEARCH (NEW!)
# ====================================================================

def fts_search(
    query: str,
    project_id: int,
    db: Session,
    limit: int = 15
) -> List[Dict[str, Any]]:
    """
    Full Text Search using PostgreSQL tsvector.
    
    Finds files containing exact words from query.
    Uses ts_rank for relevance scoring.
    
    Args:
        query: Search query (words)
        project_id: Project ID
        db: Database session
        limit: Max results
        
    Returns:
        List of file dicts with score
    """
    try:
        # Convert query to tsquery format
        # "useState React hook" → "useState & React & hook"
        words = query.strip().split()
        if not words:
            return []
        
        # Filter out very short words and special characters
        words = [w for w in words if len(w) >= 2 and w.isalnum()]
        if not words:
            return []
        
        tsquery = " & ".join(words)
        
        result = db.execute(text("""
            SELECT 
                file_path,
                file_name,
                language,
                line_count,
                metadata,
                ts_rank(content_tsv, to_tsquery('english', :tsquery)) as score
            FROM file_embeddings
            WHERE project_id = :project_id
              AND content_tsv IS NOT NULL
              AND content_tsv @@ to_tsquery('english', :tsquery)
            ORDER BY score DESC
            LIMIT :limit
        """), {
            "project_id": project_id,
            "tsquery": tsquery,
            "limit": limit
        }).fetchall()
        
        files = []
        for row in result:
            files.append({
                "file_path": row.file_path,
                "file_name": row.file_name,
                "language": row.language,
                "line_count": row.line_count,
                "metadata": row.metadata or {},
                "score": float(row.score),
                "search_type": "fts"
            })
        
        logger.info(f"[FTS] '{query}' → {len(files)} files")
        return files
        
    except Exception as e:
        logger.error(f"[FTS] Search failed: {e}")
        return []


# ====================================================================
# SEMANTIC SEARCH (wrapper)
# ====================================================================

def semantic_search(
    query: str,
    project_id: int,
    db: Session,
    limit: int = 15
) -> List[Dict[str, Any]]:
    """
    Semantic search using pgvector cosine similarity.
    
    Finds files with similar meaning to query.
    """
    try:
        # Generate query embedding
        query_embedding = vector_service.create_embedding(query)
        
        result = db.execute(text("""
            SELECT 
                file_path,
                file_name,
                language,
                line_count,
                metadata,
                1 - (embedding <=> CAST(:embedding AS vector)) as score
            FROM file_embeddings
            WHERE project_id = :project_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """), {
            "project_id": project_id,
            "embedding": query_embedding,
            "limit": limit
        }).fetchall()
        
        files = []
        for row in result:
            files.append({
                "file_path": row.file_path,
                "file_name": row.file_name,
                "language": row.language,
                "line_count": row.line_count,
                "metadata": row.metadata or {},
                "score": float(row.score),
                "search_type": "semantic"
            })
        
        logger.info(f"[SEMANTIC] '{query[:30]}...' → {len(files)} files")
        return files
        
    except Exception as e:
        logger.error(f"[SEMANTIC] Search failed: {e}")
        return []


# ====================================================================
# GRAPH SEARCH (dependencies)
# ====================================================================

def graph_search(
    query: str,
    project_id: int,
    db: Session,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Graph-based search using file dependencies.
    
    Strategy:
    1. Find top files via semantic search
    2. Get files that import them (dependents)
    3. Get files they import (dependencies)
    
    This helps find related files that might not match the query directly.
    """
    try:
        # Step 1: Get top semantic matches (seed files)
        seed_files = semantic_search(query, project_id, db, limit=5)
        if not seed_files:
            return []
        
        seed_paths = [f["file_path"] for f in seed_files]
        
        # Step 2: Find files related via dependencies
        related_files = {}
        
        for seed_path in seed_paths:
            seed_score = next(
                (f["score"] for f in seed_files if f["file_path"] == seed_path), 
                0.5
            )
            
            # Get files that import this seed file (dependents)
            dependents = db.execute(text("""
                SELECT 
                    fd.source_file as file_path,
                    fe.file_name,
                    fe.language,
                    fe.line_count,
                    fe.metadata,
                    :seed_score * 0.8 as score
                FROM file_dependencies fd
                JOIN file_embeddings fe 
                    ON fe.project_id = fd.project_id 
                    AND fe.file_path = fd.source_file
                WHERE fd.project_id = :project_id
                  AND fd.target_file = :seed_path
                LIMIT 5
            """), {
                "project_id": project_id,
                "seed_path": seed_path,
                "seed_score": seed_score
            }).fetchall()
            
            for row in dependents:
                path = row.file_path
                if path not in related_files or related_files[path]["score"] < row.score:
                    related_files[path] = {
                        "file_path": path,
                        "file_name": row.file_name,
                        "language": row.language,
                        "line_count": row.line_count,
                        "metadata": row.metadata or {},
                        "score": float(row.score),
                        "search_type": "graph",
                        "relation": f"imports {seed_path}"
                    }
            
            # Get files that this seed imports (dependencies)
            dependencies = db.execute(text("""
                SELECT 
                    fd.target_file as file_path,
                    fe.file_name,
                    fe.language,
                    fe.line_count,
                    fe.metadata,
                    :seed_score * 0.6 as score
                FROM file_dependencies fd
                JOIN file_embeddings fe 
                    ON fe.project_id = fd.project_id 
                    AND fe.file_path = fd.target_file
                WHERE fd.project_id = :project_id
                  AND fd.source_file = :seed_path
                LIMIT 5
            """), {
                "project_id": project_id,
                "seed_path": seed_path,
                "seed_score": seed_score
            }).fetchall()
            
            for row in dependencies:
                path = row.file_path
                if path not in related_files or related_files[path]["score"] < row.score:
                    related_files[path] = {
                        "file_path": path,
                        "file_name": row.file_name,
                        "language": row.language,
                        "line_count": row.line_count,
                        "metadata": row.metadata or {},
                        "score": float(row.score),
                        "search_type": "graph",
                        "relation": f"imported by {seed_path}"
                    }
        
        # Remove seed files from results (they're already in semantic results)
        for seed_path in seed_paths:
            related_files.pop(seed_path, None)
        
        # Sort by score and limit
        files = sorted(
            related_files.values(), 
            key=lambda x: x["score"], 
            reverse=True
        )[:limit]
        
        logger.info(f"[GRAPH] '{query[:30]}...' → {len(files)} related files")
        return files
        
    except Exception as e:
        logger.error(f"[GRAPH] Search failed: {e}")
        return []


# ====================================================================
# HYBRID SEARCH ORCHESTRATOR
# ====================================================================

def hybrid_search(
    query: str,
    project_id: int,
    db: Session,
    config: Optional[HybridSearchConfig] = None,
    preset: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Hybrid search combining semantic, FTS, and graph search.
    
    Args:
        query: Search query
        project_id: Project ID
        db: Database session
        config: Custom weight configuration
        preset: Use preset config ("default", "code", "exact", "related")
        limit: Max results to return
        
    Returns:
        List of files with combined scores, sorted by relevance
    """
    # Get configuration
    if preset and preset in SEARCH_PRESETS:
        config = SEARCH_PRESETS[preset]
    elif config is None:
        config = SEARCH_PRESETS["default"]
    
    logger.info(f"🔍 [HYBRID] query='{query[:50]}...' project={project_id}")
    logger.info(f"🔍 [HYBRID] weights: semantic={config.semantic_weight}, fts={config.fts_weight}, graph={config.graph_weight}")
    
    # Run all searches
    semantic_results = semantic_search(query, project_id, db, config.semantic_limit)
    fts_results = fts_search(query, project_id, db, config.fts_limit)
    graph_results = graph_search(query, project_id, db, config.graph_limit)
    
    # Combine results with weighted scores
    combined = {}  # file_path -> combined info
    
    # Process semantic results
    for f in semantic_results:
        path = f["file_path"]
        weighted_score = f["score"] * config.semantic_weight
        
        if path not in combined:
            combined[path] = {
                **f,
                "combined_score": weighted_score,
                "sources": ["semantic"],
                "scores": {"semantic": f["score"]}
            }
        else:
            combined[path]["combined_score"] += weighted_score
            combined[path]["sources"].append("semantic")
            combined[path]["scores"]["semantic"] = f["score"]
    
    # Process FTS results
    for f in fts_results:
        path = f["file_path"]
        # Normalize FTS score (usually 0-1 but can be higher)
        normalized_score = min(f["score"], 1.0)
        weighted_score = normalized_score * config.fts_weight
        
        if path not in combined:
            combined[path] = {
                **f,
                "combined_score": weighted_score,
                "sources": ["fts"],
                "scores": {"fts": normalized_score}
            }
        else:
            combined[path]["combined_score"] += weighted_score
            combined[path]["sources"].append("fts")
            combined[path]["scores"]["fts"] = normalized_score
    
    # Process graph results
    for f in graph_results:
        path = f["file_path"]
        weighted_score = f["score"] * config.graph_weight
        
        if path not in combined:
            combined[path] = {
                **f,
                "combined_score": weighted_score,
                "sources": ["graph"],
                "scores": {"graph": f["score"]}
            }
        else:
            combined[path]["combined_score"] += weighted_score
            combined[path]["sources"].append("graph")
            combined[path]["scores"]["graph"] = f["score"]
            # Keep relation info if from graph
            if "relation" in f:
                combined[path]["relation"] = f["relation"]
    
    # Sort by combined score
    results = sorted(
        combined.values(),
        key=lambda x: x["combined_score"],
        reverse=True
    )[:limit]
    
    # Log summary
    logger.info(f"✅ [HYBRID] Results: {len(results)} files")
    for i, r in enumerate(results[:5], 1):
        sources = "+".join(r["sources"])
        logger.info(f"   {i}. {r['file_path']} ({r['combined_score']:.3f}) [{sources}]")
    
    return results


# ====================================================================
# CONVENIENCE FUNCTIONS
# ====================================================================

async def hybrid_search_async(
    query: str,
    project_id: int,
    db: Session,
    preset: str = "default",
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Async wrapper for hybrid_search"""
    return hybrid_search(query, project_id, db, preset=preset, limit=limit)


def get_search_presets() -> Dict[str, HybridSearchConfig]:
    """Get available search presets"""
    return SEARCH_PRESETS