"""
MCP (Model Context Protocol) server for multi-ai-chat.

Exposes 8 tools over Streamable HTTP transport so Claude Desktop / Claude Code
can query the backend.

Client endpoint: https://ion.up.railway.app/mcp
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy import text

from app.memory.db import SessionLocal
from app.memory.manager import MemoryManager
from app.services.file_indexer import FileIndexer
from app.services.smart_context import build_smart_context

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# MCP Server instance
# ─────────────────────────────────────────────────────────────────
mcp = FastMCP(
    "multi-ai-chat-mcp",
    json_response=True,
    host="0.0.0.0",
)


# ─────────────────────────────────────────────────────────────────
# Helper – open a short-lived DB session
# ─────────────────────────────────────────────────────────────────
def _open_db():
    """Return a new SQLAlchemy Session. Caller is responsible for closing it."""
    return SessionLocal()


# ─────────────────────────────────────────────────────────────────
# Tool 1 — search_project_files
# ─────────────────────────────────────────────────────────────────
async def _tool_search_project_files(args: Dict[str, Any]) -> Any:
    project_id: int = int(args["project_id"])
    query: str = str(args["query"])
    limit: int = int(args.get("limit", 5))
    language: Optional[str] = args.get("language")

    db = _open_db()
    try:
        indexer = FileIndexer(db)
        results: List[Dict[str, Any]] = await indexer.search_files(
            project_id=project_id,
            query=query,
            limit=limit,
            language=language,
            db=db,
        )
        for r in results:
            raw_meta = r.get("metadata")
            if isinstance(raw_meta, str):
                try:
                    r["metadata"] = json.loads(raw_meta)
                except Exception:
                    r["metadata"] = {}
        return results
    except Exception as exc:
        logger.error("search_project_files error: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 2 — get_file_content
# ─────────────────────────────────────────────────────────────────
async def _tool_get_file_content(args: Dict[str, Any]) -> Any:
    project_id: int = int(args["project_id"])
    file_path: str = str(args["file_path"])

    db = _open_db()
    try:
        row = db.execute(
            text("""
                SELECT content, language, line_count, metadata
                FROM file_embeddings
                WHERE project_id = :project_id
                  AND file_path   = :file_path
                LIMIT 1
            """),
            {"project_id": project_id, "file_path": file_path},
        ).fetchone()

        if row is None:
            return {"error": f"File not found: {file_path!r} in project {project_id}"}

        metadata: Any = row.metadata
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}

        return {
            "content": row.content,
            "language": row.language,
            "line_count": row.line_count,
            "metadata": metadata,
        }
    except Exception as exc:
        logger.error("get_file_content error: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 3 — get_file_dependencies
# ─────────────────────────────────────────────────────────────────
async def _tool_get_file_dependencies(args: Dict[str, Any]) -> Any:
    project_id: int = int(args["project_id"])
    file_path: Optional[str] = args.get("file_path")

    db = _open_db()
    try:
        if file_path:
            rows = db.execute(
                text("""
                    SELECT source_file, target_file, dependency_type, imports_what
                    FROM file_dependencies
                    WHERE project_id = :project_id
                      AND source_file = :file_path
                    ORDER BY target_file
                """),
                {"project_id": project_id, "file_path": file_path},
            ).fetchall()
        else:
            rows = db.execute(
                text("""
                    SELECT source_file, target_file, dependency_type, imports_what
                    FROM file_dependencies
                    WHERE project_id = :project_id
                    ORDER BY source_file, target_file
                """),
                {"project_id": project_id},
            ).fetchall()

        return [
            {
                "source_file": r.source_file,
                "target_file": r.target_file,
                "dependency_type": r.dependency_type,
                "imports_what": json.loads(r.imports_what) if r.imports_what else [],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.error("get_file_dependencies error: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 4 — search_conversation_memory
# ─────────────────────────────────────────────────────────────────
async def _tool_search_conversation_memory(args: Dict[str, Any]) -> Any:
    project_id: str = str(args["project_id"])
    query: str = str(args["query"])
    limit: int = int(args.get("limit", 5))
    role_id: Optional[int] = int(args["role_id"]) if args.get(
        "role_id") is not None else None

    db = _open_db()
    try:
        from app.services.vector_service import create_embedding
        query_embedding: List[float] = create_embedding(query)

        role_clause = "AND role_id = :role_id" if role_id is not None else ""
        params: Dict[str, Any] = {
            "query_embedding": query_embedding,
            "project_id": project_id,
            "limit": limit,
        }
        if role_id is not None:
            params["role_id"] = role_id

        rows = db.execute(
            text(f"""
                SELECT raw_text, summary, timestamp, is_summary,
                       1 - (embedding <=> CAST(:query_embedding AS vector)) AS similarity
                FROM memory_entries
                WHERE project_id = :project_id
                  AND embedding IS NOT NULL
                  AND deleted = FALSE
                  {role_clause}
                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                LIMIT :limit
            """),
            params,
        ).fetchall()

        return [
            {
                "raw_text": r.raw_text,
                "summary": r.summary,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "is_summary": r.is_summary,
                "similarity": float(r.similarity),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.error("search_conversation_memory error: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 5 — list_canon_items
# ─────────────────────────────────────────────────────────────────
async def _tool_list_canon_items(args: Dict[str, Any]) -> Any:
    project_id: str = str(args["project_id"])
    item_type: Optional[str] = args.get("type")
    is_active: bool = bool(args.get("is_active", True))

    db = _open_db()
    try:
        type_clause = "AND type = :item_type" if item_type else ""
        params: Dict[str, Any] = {
            "project_id": project_id, "is_active": is_active}
        if item_type:
            params["item_type"] = item_type

        rows = db.execute(
            text(f"""
                SELECT id, type, title, body, tags, created_at
                FROM canon_items
                WHERE project_id = :project_id
                  AND is_active  = :is_active
                  {type_clause}
                ORDER BY created_at DESC
            """),
            params,
        ).fetchall()

        results: List[Dict[str, Any]] = []
        for r in rows:
            tags: Any = r.tags
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = []
            results.append(
                {
                    "id": r.id,
                    "type": r.type,
                    "title": r.title,
                    "body": r.body,
                    "tags": tags,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return results
    except Exception as exc:
        logger.error("list_canon_items error: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 6 — get_project_stats
# ─────────────────────────────────────────────────────────────────
async def _tool_get_project_stats(args: Dict[str, Any]) -> Any:
    project_id: int = int(args["project_id"])

    db = _open_db()
    try:
        indexer = FileIndexer(db)
        stats: Dict[str, Any] = await indexer.get_project_stats(project_id)
        return stats
    except Exception as exc:
        logger.error("get_project_stats error: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 7 — get_file_versions
# ─────────────────────────────────────────────────────────────────
async def _tool_get_file_versions(args: Dict[str, Any]) -> Any:
    project_id: int = int(args["project_id"])
    file_path: str = str(args["file_path"])

    db = _open_db()
    try:
        rows = db.execute(
            text("""
                SELECT fv.version_number, fv.change_type, fv.change_source,
                       fv.change_message, fv.ai_model, fv.created_at
                FROM file_versions fv
                JOIN file_embeddings fe ON fe.id = fv.file_id
                WHERE fe.project_id = :project_id
                  AND fe.file_path  = :file_path
                ORDER BY fv.version_number ASC
            """),
            {"project_id": project_id, "file_path": file_path},
        ).fetchall()

        return [
            {
                "version_number": r.version_number,
                "change_type": r.change_type,
                "change_source": r.change_source,
                "change_message": r.change_message,
                "ai_model": r.ai_model,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.error("get_file_versions error: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 8 — build_context_for_query
# ─────────────────────────────────────────────────────────────────
async def _tool_build_context_for_query(args: Dict[str, Any]) -> Any:
    raw_pid: Any = args["project_id"]
    query: str = str(args["query"])
    role_id: int = int(args.get("role_id", 0))

    try:
        project_id_int: int = int(raw_pid)
    except (ValueError, TypeError):
        return {"error": f"project_id must be numeric, got: {raw_pid!r}"}

    db = _open_db()
    try:
        memory = MemoryManager(db)
        context: str = await build_smart_context(
            project_id=project_id_int,
            role_id=role_id,
            query=query,
            session_id="",
            db=db,
            memory=memory,
        )
        return {"context": context}
    except Exception as exc:
        logger.error("build_context_for_query error: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# @mcp.tool() wrappers
# ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def search_project_files(
    project_id: int, query: str, limit: int = 5, language: Optional[str] = None
) -> str:
    result = await _tool_search_project_files(
        {"project_id": project_id, "query": query,
            "limit": limit, "language": language}
    )
    return json.dumps(result, default=str, ensure_ascii=False)


@mcp.tool()
async def get_file_content(project_id: int, file_path: str) -> str:
    result = await _tool_get_file_content({"project_id": project_id, "file_path": file_path})
    return json.dumps(result, default=str, ensure_ascii=False)


@mcp.tool()
async def get_file_dependencies(project_id: int, file_path: Optional[str] = None) -> str:
    result = await _tool_get_file_dependencies({"project_id": project_id, "file_path": file_path})
    return json.dumps(result, default=str, ensure_ascii=False)


@mcp.tool()
async def search_conversation_memory(
    project_id: str, query: str, limit: int = 5, role_id: Optional[int] = None
) -> str:
    result = await _tool_search_conversation_memory(
        {"project_id": project_id, "query": query,
            "limit": limit, "role_id": role_id}
    )
    return json.dumps(result, default=str, ensure_ascii=False)


@mcp.tool()
async def list_canon_items(
    project_id: str, type: Optional[str] = None, is_active: bool = True
) -> str:
    result = await _tool_list_canon_items(
        {"project_id": project_id, "type": type, "is_active": is_active}
    )
    return json.dumps(result, default=str, ensure_ascii=False)


@mcp.tool()
async def get_project_stats(project_id: int) -> str:
    result = await _tool_get_project_stats({"project_id": project_id})
    return json.dumps(result, default=str, ensure_ascii=False)


@mcp.tool()
async def get_file_versions(project_id: int, file_path: str) -> str:
    result = await _tool_get_file_versions({"project_id": project_id, "file_path": file_path})
    return json.dumps(result, default=str, ensure_ascii=False)


@mcp.tool()
async def build_context_for_query(
    project_id: str, query: str, role_id: int = 0
) -> str:
    result = await _tool_build_context_for_query(
        {"project_id": project_id, "query": query, "role_id": role_id}
    )
    return json.dumps(result, default=str, ensure_ascii=False)


@mcp.tool()
async def get_active_project(folder_identifier: str) -> str:
    """
    Find a project by its VSCode folder identifier.
    Returns project_id, name, git_url and file stats.
    Use this at the start of every session to identify
    which project the user is working on.

    Args:
        folder_identifier: The VSCode workspace folder identifier (e.g. 'my-project').
    """
    db = _open_db()
    try:
        row = db.execute(
            text("""
                SELECT id, name, git_url, files_count, indexed_at
                FROM projects
                WHERE folder_identifier = :folder_identifier
                LIMIT 1
            """),
            {"folder_identifier": folder_identifier},
        ).fetchone()

        if row is None:
            row = db.execute(
                text("""
                    SELECT id, name, git_url, files_count, indexed_at
                    FROM projects
                    WHERE name ILIKE :pattern
                    LIMIT 1
                """),
                {"pattern": f"%{folder_identifier}%"},
            ).fetchone()

        if row is None:
            return json.dumps(
                {"found": False, "folder_identifier": folder_identifier},
                default=str,
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "found": True,
                "project_id": row[0],
                "name": row[1],
                "git_url": row[2],
                "files_count": row[3],
                "last_indexed": row[4].isoformat() if row[4] else None,
            },
            default=str,
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error("get_active_project error: %s", exc)
        return json.dumps({"error": str(exc), "found": False}, ensure_ascii=False)
    finally:
        db.close()


__all__ = ["mcp"]
