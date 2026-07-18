"""
MCP (Model Context Protocol) server for multi-ai-chat.

Exposes 8 tools over Streamable HTTP transport so Claude Desktop / Claude Code
can query the backend.

Client endpoint: https://ion.up.railway.app/mcp
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from mcp.server.fastmcp import FastMCP
from sqlalchemy import text

from app.memory.db import SessionLocal
from app.memory.manager import MemoryManager
from app.services.file_indexer import FileIndexer
from app.services.smart_context import build_smart_context
from app.utils.tracking import bump_access_bg

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# MCP Server instance
# ─────────────────────────────────────────────────────────────────
mcp = FastMCP(
    "multi-ai-chat-mcp",
    json_response=True,
    stateless_http=True,
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
                "imports_what": r.imports_what or [],
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
                SELECT id, raw_text, summary, timestamp, is_summary,
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

        hit_ids = [r.id for r in rows]
        bump_access_bg(SessionLocal, "memory_entries", hit_ids)

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

        bump_access_bg(SessionLocal, "canon_items", [r.id for r in rows])

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
def _resolve_project_id(db, folder_identifier: str) -> Optional[int]:
    """Look up project_id from a VSCode folder identifier (exact or fuzzy match)."""
    row = db.execute(
        text("""
            SELECT id FROM projects
            WHERE folder_identifier = :folder_identifier
            LIMIT 1
        """),
        {"folder_identifier": folder_identifier},
    ).fetchone()
    if row is None:
        row = db.execute(
            text("""
                SELECT id FROM projects
                WHERE name ILIKE :pattern
                LIMIT 1
            """),
            {"pattern": f"%{folder_identifier}%"},
        ).fetchone()
    return int(row[0]) if row else None


async def _tool_build_context_for_query(args: Dict[str, Any]) -> Any:
    raw_pid: Any = args.get("project_id")
    folder_id: Optional[str] = args.get("folder_identifier")
    query: str = str(args["query"])
    role_id: int = int(args.get("role_id", 0))

    if raw_pid in (None, "", 0, "0") and not folder_id:
        return {"error": "either project_id or folder_identifier is required"}

    db = _open_db()
    try:
        project_id_int: Optional[int] = None
        if raw_pid not in (None, "", 0, "0"):
            try:
                project_id_int = int(raw_pid)
            except (ValueError, TypeError):
                return {"error": f"project_id must be numeric, got: {raw_pid!r}"}

        if project_id_int is None and folder_id:
            project_id_int = _resolve_project_id(db, folder_id)
            if project_id_int is None:
                return {"error": f"no project matched folder_identifier={folder_id!r}"}

        memory = MemoryManager(db)
        context: str = await build_smart_context(
            project_id=project_id_int,
            role_id=role_id,
            query=query,
            session_id="",
            db=db,
            memory=memory,
        )
        return {"context": context, "project_id": project_id_int}
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
    query: str,
    project_id: Optional[str] = None,
    folder_identifier: Optional[str] = None,
    role_id: int = 0,
) -> str:
    """
    Build smart context (recent conversation, file matches, summaries) for a
    user query against a project.

    Pass either `project_id` (numeric) or `folder_identifier` (VSCode workspace
    folder name). If only the folder identifier is given, the project is
    resolved internally — no separate get_active_project call needed.

    Args:
        query: The user's question or task description.
        project_id: Numeric project id (optional if folder_identifier is given).
        folder_identifier: VSCode workspace folder name (optional if project_id is given).
        role_id: Optional role id to scope the context (0 = none).
    """
    result = await _tool_build_context_for_query(
        {
            "project_id": project_id,
            "folder_identifier": folder_identifier,
            "query": query,
            "role_id": role_id,
        }
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


@mcp.tool()
async def ensure_project_indexed(git_url: str, project_name: str) -> str:
    """
    Ensures a project exists in the database and is indexed.
    Call this automatically when starting work on any project.

    Steps:
    1. Check if project exists by git_url
    2. If not exists — create it automatically
    3. Check if project has indexed files (files_count > 0)
    4. If not indexed — trigger full indexing
    5. Return status with project_id

    Args:
        git_url: GitHub repository URL (e.g. https://github.com/owner/repo).
        project_name: Human-readable project name used when creating a new record.
    """
    # Normalize: strip scheme, trailing slash, .git suffix
    normalized = (
        git_url.strip()
        .rstrip("/")
        .replace("https://", "")
        .replace("http://", "")
        .replace(".git", "")
    )

    db = _open_db()
    try:
        # 1. Look up existing project
        row = db.execute(
            text("""
                SELECT id, name, files_count
                FROM projects
                WHERE git_url LIKE :pattern
                LIMIT 1
            """),
            {"pattern": f"%{normalized}%"},
        ).fetchone()

        if row:
            project_id: int = row[0]
            name: str = row[1]
            files_count: int = row[2] or 0
            created = False
        else:
            # 2. Create project (user_id=1 — superuser / service account)
            result = db.execute(
                text("""
                    INSERT INTO projects (name, git_url, user_id)
                    VALUES (:name, :git_url, 1)
                    RETURNING id
                """),
                {"name": project_name, "git_url": git_url.strip()},
            )
            db.commit()
            project_id = result.fetchone()[0]
            name = project_name
            files_count = 0
            created = True

        # 3. Trigger indexing if no files yet
        status: str
        if files_count > 0:
            status = "already_indexed"
        else:
            backend_url = os.getenv(
                "BACKEND_URL", "http://localhost:8080").rstrip("/")
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        f"{backend_url}/api/file-indexer/index/{project_id}",
                        headers={"Authorization": "Bearer internal"},
                    )
                    resp.raise_for_status()
                status = "created_and_indexing" if created else "indexing_started"
            except Exception as http_exc:
                logger.error(
                    "ensure_project_indexed: trigger failed: %s", http_exc)
                status = "created_trigger_failed" if created else "trigger_failed"

        return json.dumps(
            {
                "project_id": project_id,
                "name": name,
                "status": status,
                "files_count": files_count,
            },
            default=str,
            ensure_ascii=False,
        )

    except Exception as exc:
        db.rollback()
        logger.error("ensure_project_indexed error: %s", exc)
        return json.dumps({"error": str(exc), "found": False}, ensure_ascii=False)
    finally:
        db.close()


@mcp.tool()
async def hybrid_search_files(
    project_id: int,
    query: str,
    mode: str = "hybrid",
    limit: int = 5,
) -> str:
    """
    Search project files using hybrid mode (semantic + FTS + graph).
    mode options: "semantic", "fts", "hybrid"
    Use "hybrid" for best results combining all search methods.
    Use "fts" for exact identifier search (function names, class names).
    """
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxODA2NDkxNTc2fQ.oBu_Vg9wW34TE1LUlYpwB3v9uPNjKuIMXcQu_S6k-8o"

    # ✅ FIX: использовать BACKEND_URL из env, не localhost
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8080").rstrip("/")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{backend_url}/api/file-indexer/search/{project_id}",
                params={"q": query, "mode": mode, "limit": limit},
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            return resp.text
    except Exception as exc:
        logger.error("hybrid_search_files error: %s", exc)
        return json.dumps({"error": str(exc), "project_id": project_id, "query": query, "results": [], "total_results": 0})


# ─────────────────────────────────────────────────────────────────
# Tool 12 — get_developer_patterns
# ─────────────────────────────────────────────────────────────────
async def _tool_get_developer_patterns(
    query: str,
    project_id: Optional[int],
) -> Any:
    from app.services.vector_service import create_embedding

    db = _open_db()
    try:
        # ── 1. Fetch entities (all projects or one) ──────────────
        if project_id is not None:
            rows = db.execute(
                text("""
                    SELECT ke.name, ke.entity_type, ke.description,
                           ke.source_file, p.name AS project_name
                    FROM knowledge_entities ke
                    JOIN projects p ON p.id = ke.project_id
                    WHERE ke.project_id = :project_id
                    ORDER BY ke.entity_type, ke.name
                """),
                {"project_id": project_id},
            ).fetchall()
        else:
            # Semantic search across ALL projects
            try:
                query_embedding = create_embedding(query)
                rows = db.execute(
                    text("""
                        SELECT ke.name, ke.entity_type, ke.description,
                               ke.source_file, p.name AS project_name
                        FROM knowledge_entities ke
                        JOIN projects p ON p.id = ke.project_id
                        WHERE ke.embedding IS NOT NULL
                        ORDER BY ke.embedding <=> CAST(:embedding AS vector),
                                 ke.entity_type, ke.name
                        LIMIT 100
                    """),
                    {"embedding": query_embedding},
                ).fetchall()
            except Exception:
                # Fallback: return all without semantic ranking
                rows = db.execute(
                    text("""
                        SELECT ke.name, ke.entity_type, ke.description,
                               ke.source_file, p.name AS project_name
                        FROM knowledge_entities ke
                        JOIN projects p ON p.id = ke.project_id
                        ORDER BY ke.entity_type, ke.name
                        LIMIT 100
                    """),
                ).fetchall()

        if not rows:
            return {
                "query": query,
                "projects_searched": 0,
                "patterns": {},
                "message": "No knowledge entities found. Run extract_from_project first.",
            }

        # ── 2. Group by project → entity_type ───────────────────
        # entity_type → plural key used in output
        TYPE_KEY = {
            "framework":              "frameworks",
            "library":                "libraries",
            "pattern":                "patterns",
            "architectural_decision": "architectural_decisions",
            "component":              "components",
            "style_approach":         "style_approaches",
        }

        patterns: Dict[str, Any] = {}
        projects_seen: set = set()

        for r in rows:
            proj = r.project_name
            projects_seen.add(proj)
            if proj not in patterns:
                patterns[proj] = {}

            bucket = TYPE_KEY.get(r.entity_type, r.entity_type)
            if bucket not in patterns[proj]:
                patterns[proj][bucket] = []

            patterns[proj][bucket].append({
                "name": r.name,
                "description": r.description,
                "source_file": r.source_file,
            })

        return {
            "query": query,
            "projects_searched": len(projects_seen),
            "patterns": patterns,
        }

    except Exception as exc:
        logger.error("get_developer_patterns error: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


@mcp.tool()
async def get_developer_patterns(
    query: str,
    project_id: Optional[int] = None,
) -> str:
    """
    Search developer patterns across all projects.
    Use when user says:
    - "Начинаю новый проект"
    - "Как я обычно делаю X?"
    - "Что я использовал раньше?"
    - "Найди похожий код"

    If project_id is None — searches ALL projects.
    Returns frameworks, libraries, patterns, components
    that match the query.
    """
    result = await _tool_get_developer_patterns(query=query, project_id=project_id)
    return json.dumps(result, default=str, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────
# Tool 13 — save_session_summary
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def save_session_summary(
    project_id: int,
    content: str,
    topics: List[str] = [],
) -> str:
    """
    Save current session summary to brain for future reference.

    Call this when the conversation is getting long or at the end of a
    work session. The summary is stored in canon_items as SESSION_SUMMARY
    and will be retrieved automatically in future sessions via
    build_context_for_query.

    Args:
        project_id: ID of the current project.
        content: Text describing what was discussed/decided this session.
        topics: List of main topics (e.g. ["auth", "migration", "FastAPI"]).
    """
    from datetime import datetime, timezone
    db = _open_db()
    try:
        now = datetime.now(timezone.utc)
        title = f"Session {now.strftime('%Y-%m-%d %H:%M')}"
        terms = " ".join(topics)[:1000] if topics else None
        tags_json = json.dumps(topics) if topics else None

        row = db.execute(
            text("""
                INSERT INTO canon_items
                    (project_id, project_id_int, role_id, type, title, body, tags, terms, created_at, is_active)
                VALUES
                    (:project_id, :project_id_int, NULL, 'SESSION_SUMMARY', :title, :body, cast(:tags AS jsonb), :terms, :created_at, TRUE)
                RETURNING id
            """),
            {
                "project_id": str(project_id),
                "project_id_int": project_id,
                "title": title[:256],
                "body": content[:8000],
                "tags": tags_json,
                "terms": terms,
                "created_at": now,
            },
        ).fetchone()
        db.commit()

        summary_id = row[0] if row else None
        logger.info("save_session_summary: saved id=%s project=%s", summary_id, project_id)
        return json.dumps(
            {"saved": True, "summary_id": summary_id, "title": title},
            ensure_ascii=False,
        )
    except Exception as exc:
        db.rollback()
        logger.error("save_session_summary error: %s", exc)
        return json.dumps({"error": str(exc), "saved": False}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 14 — get_session_summaries
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_session_summaries(
    project_id: int,
    limit: int = 5,
) -> str:
    """
    Get recent session summaries for a project.

    Returns the last N saved sessions with their dates and content.
    Use this to recall what was worked on in previous sessions.

    Args:
        project_id: ID of the project.
        limit: How many recent sessions to return (default 5, max 50).
    """
    db = _open_db()
    try:
        rows = db.execute(
            text("""
                SELECT id, title, body, tags, created_at
                FROM canon_items
                WHERE project_id = :project_id
                  AND type = 'SESSION_SUMMARY'
                  AND is_active = TRUE
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"project_id": str(project_id), "limit": max(1, min(limit, 50))},
        ).fetchall()

        if not rows:
            return "No session summaries found for this project"

        result = f"Last {len(rows)} sessions:\n\n"
        for r in rows:
            date = r.created_at.strftime("%Y-%m-%d") if r.created_at else ""
            body_preview = (r.body or "")[:300]
            result += f"**{r.title}** ({date})\n"
            result += f"{body_preview}{'...' if len(r.body or '') > 300 else ''}\n\n"

        return result
    except Exception as exc:
        logger.error("get_session_summaries error: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 15 — search_session_memory
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def search_session_memory(
    project_id: int,
    query: str,
    limit: int = 3,
) -> str:
    """
    Search past session summaries by topic or keyword.

    Fetches up to 20 recent summaries and filters them by keyword match
    in title or body. Use when you need to recall a specific past decision
    or piece of work.

    Args:
        project_id: ID of the project.
        query: Keyword or phrase to search for.
        limit: Max number of matching sessions to return (default 3).
    """
    db = _open_db()
    try:
        rows = db.execute(
            text("""
                SELECT id, title, body, tags, created_at
                FROM canon_items
                WHERE project_id = :project_id
                  AND type = 'SESSION_SUMMARY'
                  AND is_active = TRUE
                ORDER BY created_at DESC
                LIMIT 20
            """),
            {"project_id": str(project_id)},
        ).fetchall()

        query_lower = query.lower()
        relevant = [
            r for r in rows
            if query_lower in (r.body or "").lower()
            or query_lower in (r.title or "").lower()
        ][:limit]

        if not relevant:
            return json.dumps(
                {"found": 0, "message": f"No sessions found matching: {query}"},
                ensure_ascii=False,
            )

        result = f"Found {len(relevant)} relevant sessions:\n\n"
        for r in relevant:
            body_preview = (r.body or "")[:400]
            result += f"**{r.title}**\n{body_preview}\n\n"

        return result
    except Exception as exc:
        logger.error("search_session_memory error: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Local-indexing helpers
# ─────────────────────────────────────────────────────────────────
_INDEXABLE_EXTENSIONS = {".ts", ".tsx", ".js", ".py", ".json", ".css", ".md"}
_SKIP_DIR_NAMES = {"node_modules", ".git", "dist", "build"}
# Hardcoded JWT for user_id=1 (matches hybrid_search_files pattern).
_INTERNAL_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxODA2NDkxNTc2fQ.oBu_Vg9wW34TE1LUlYpwB3v9uPNjKuIMXcQu_S6k-8o"
_MAX_FILE_BYTES = 1_000_000  # 1 MB per file — skip larger blobs


def _backend_url() -> str:
    return os.getenv("BACKEND_URL", "http://localhost:8080").rstrip("/")


def _webhook_url() -> str:
    return f"{_backend_url()}/api/webhooks/github"


def _collect_local_files(directory_path: str) -> List[Dict[str, str]]:
    """Walk directory_path and collect indexable files as [{path, content}]."""
    root = Path(directory_path).resolve()
    if not root.is_dir():
        raise ValueError(f"directory_path is not a directory: {directory_path}")

    collected: List[Dict[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # Skip if any parent directory is in the skip list.
        if any(part in _SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in _INDEXABLE_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root).as_posix()
        collected.append({"path": rel, "content": content})
    return collected


async def _post_index_local(project_id: int, files: List[Dict[str, str]]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{_backend_url()}/api/file-indexer/index-local",
            json={"project_id": project_id, "files": files},
            headers={"Authorization": f"Bearer {_INTERNAL_TOKEN}"},
        )
        resp.raise_for_status()
        return resp.json()


# ─────────────────────────────────────────────────────────────────
# Tool 16 — index_local_project
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def index_local_project(project_id: int, directory_path: str) -> str:
    """
    Index files from a local directory into an existing project.

    Walks `directory_path` recursively, picks up files with extensions
    .ts, .tsx, .js, .py, .json, .css, .md, skipping node_modules, .git,
    dist, build, and POSTs them to /api/file-indexer/index-local.

    Args:
        project_id: ID of the target project.
        directory_path: Absolute path to the directory to scan.
    """
    try:
        files = _collect_local_files(directory_path)
    except Exception as exc:
        logger.error("index_local_project: collect failed: %s", exc)
        return json.dumps({"error": str(exc), "indexed_files_count": 0}, ensure_ascii=False)

    if not files:
        return json.dumps(
            {"indexed_files_count": 0, "message": "No indexable files found"},
            ensure_ascii=False,
        )

    try:
        result = await _post_index_local(project_id, files)
        return json.dumps(
            {
                "project_id": project_id,
                "directory_path": directory_path,
                "files_sent": len(files),
                "indexed_files_count": result.get("indexed", 0),
                "skipped": result.get("skipped", 0),
                "errors": result.get("errors", 0),
                "message": result.get("message"),
            },
            default=str,
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error("index_local_project: HTTP failed: %s", exc)
        return json.dumps(
            {"error": str(exc), "files_sent": len(files), "indexed_files_count": 0},
            ensure_ascii=False,
        )


# ─────────────────────────────────────────────────────────────────
# Tool 17 — create_project_with_index
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def create_project_with_index(
    name: str,
    directory_path: str,
    git_url: Optional[str] = None,
) -> str:
    """
    Create a new project and immediately index files from a local directory.

    Steps:
    1. Insert a project row (user_id=1) with optional git_url.
    2. Walk directory_path and POST files to /api/file-indexer/index-local.
    3. Write .smartcontext.json into directory_path with project_id and webhook_url.

    Args:
        name: Human-readable project name.
        directory_path: Absolute path to the directory to scan and tag.
        git_url: Optional GitHub repository URL.
    """
    db = _open_db()
    try:
        if git_url:
            row = db.execute(
                text("""
                    INSERT INTO projects (name, git_url, user_id)
                    VALUES (:name, :git_url, 1)
                    RETURNING id
                """),
                {"name": name, "git_url": git_url.strip()},
            ).fetchone()
        else:
            row = db.execute(
                text("""
                    INSERT INTO projects (name, user_id)
                    VALUES (:name, 1)
                    RETURNING id
                """),
                {"name": name},
            ).fetchone()
        db.commit()
        project_id = int(row[0])
    except Exception as exc:
        db.rollback()
        logger.error("create_project_with_index: insert failed: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()

    # Index files
    indexed_files_count = 0
    indexing_error: Optional[str] = None
    try:
        files = _collect_local_files(directory_path)
        if files:
            result = await _post_index_local(project_id, files)
            indexed_files_count = int(result.get("indexed", 0))
    except Exception as exc:
        logger.error("create_project_with_index: indexing failed: %s", exc)
        indexing_error = str(exc)

    webhook_url = _webhook_url()

    # Write .smartcontext.json
    smartcontext_error: Optional[str] = None
    try:
        marker_path = Path(directory_path) / ".smartcontext.json"
        marker_path.write_text(
            json.dumps(
                {
                    "project_id": project_id,
                    "name": name,
                    "git_url": git_url,
                    "webhook_url": webhook_url,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.error("create_project_with_index: marker write failed: %s", exc)
        smartcontext_error = str(exc)

    return json.dumps(
        {
            "project_id": project_id,
            "webhook_url": webhook_url,
            "indexed_files_count": indexed_files_count,
            "indexing_error": indexing_error,
            "smartcontext_error": smartcontext_error,
        },
        default=str,
        ensure_ascii=False,
    )


# ─────────────────────────────────────────────────────────────────
# Tool 18 — get_index_status
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_index_status(project_id: int) -> str:
    """
    Return indexing status for a project: total_files, languages,
    last_indexed timestamp, and the GitHub webhook URL to configure.

    Args:
        project_id: ID of the project.
    """
    db = _open_db()
    try:
        proj = db.execute(
            text("""
                SELECT files_count, indexed_at
                FROM projects
                WHERE id = :project_id
                LIMIT 1
            """),
            {"project_id": project_id},
        ).fetchone()

        if proj is None:
            return json.dumps(
                {"error": f"Project not found: {project_id}"},
                ensure_ascii=False,
            )

        lang_rows = db.execute(
            text("""
                SELECT language, COUNT(*) AS cnt
                FROM file_embeddings
                WHERE project_id = :project_id
                GROUP BY language
                ORDER BY cnt DESC
            """),
            {"project_id": project_id},
        ).fetchall()

        languages = {r.language or "unknown": int(r.cnt) for r in lang_rows}
        total_files = int(proj.files_count or sum(languages.values()))

        return json.dumps(
            {
                "project_id": project_id,
                "total_files": total_files,
                "languages": languages,
                "last_indexed": proj.indexed_at.isoformat() if proj.indexed_at else None,
                "webhook_url": _webhook_url(),
            },
            default=str,
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error("get_index_status error: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 19 — get_usage_stats
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_usage_stats(project_id: int, days: int = 30) -> str:
    """
    Get Claude Code usage stats for a project.

    Returns total requests, token counts, cost in USD, cache savings,
    and how many requests used Brain context, over the last `days`.

    Args:
        project_id: ID of the project.
        days: Look-back window in days (default 30, max 365).
    """
    from datetime import datetime, timedelta
    days = max(1, min(int(days), 365))
    since = datetime.utcnow() - timedelta(days=days)

    db = _open_db()
    try:
        totals = db.execute(
            text("""
                SELECT
                    COUNT(*) AS req,
                    COALESCE(SUM(input_tokens), 0)         AS in_t,
                    COALESCE(SUM(output_tokens), 0)        AS out_t,
                    COALESCE(SUM(cache_creation_tokens),0) AS cc_t,
                    COALESCE(SUM(cache_read_tokens), 0)    AS cr_t,
                    COALESCE(SUM(total_tokens), 0)         AS tot_t,
                    COALESCE(SUM(cost_usd), 0)             AS cost,
                    COALESCE(SUM(cache_savings_usd), 0)    AS savings,
                    COALESCE(SUM(CASE WHEN used_brain_context THEN 1 ELSE 0 END), 0) AS brain_req
                FROM claude_usage_logs
                WHERE project_id = :project_id AND timestamp >= :since
            """),
            {"project_id": project_id, "since": since},
        ).fetchone()

        # Session-level rollup: a session counts as "brain-assisted" if ANY
        # assistant turn within it called a Brain tool. Per-call counts (above)
        # under-report by ~10x because a single user turn produces many
        # assistant turns but only one calls Brain.
        sess = db.execute(
            text("""
                SELECT
                    COUNT(*)                                AS sessions,
                    COALESCE(SUM(CASE WHEN used_brain THEN 1 ELSE 0 END), 0) AS brain_sessions
                FROM (
                    SELECT
                        COALESCE(session_id, message_id) AS sid,
                        BOOL_OR(used_brain_context)      AS used_brain
                    FROM claude_usage_logs
                    WHERE project_id = :project_id AND timestamp >= :since
                    GROUP BY COALESCE(session_id, message_id)
                ) s
            """),
            {"project_id": project_id, "since": since},
        ).fetchone()

        rows = db.execute(
            text("""
                SELECT model,
                       COUNT(*) AS req,
                       COALESCE(SUM(cost_usd), 0) AS cost
                FROM claude_usage_logs
                WHERE project_id = :project_id AND timestamp >= :since
                GROUP BY model
                ORDER BY cost DESC
            """),
            {"project_id": project_id, "since": since},
        ).fetchall()

        total_sessions = int(sess.sessions or 0)
        brain_sessions = int(sess.brain_sessions or 0)
        brain_session_pct = round(brain_sessions / total_sessions * 100.0, 2) if total_sessions else 0.0

        return json.dumps(
            {
                "project_id": project_id,
                "days": days,
                "request_count": int(totals.req or 0),
                "input_tokens": int(totals.in_t or 0),
                "output_tokens": int(totals.out_t or 0),
                "cache_creation_tokens": int(totals.cc_t or 0),
                "cache_read_tokens": int(totals.cr_t or 0),
                "total_tokens": int(totals.tot_t or 0),
                "cost_usd": round(float(totals.cost or 0.0), 4),
                "cache_savings_usd": round(float(totals.savings or 0.0), 4),
                "brain_assisted_requests": int(totals.brain_req or 0),
                "total_sessions": total_sessions,
                "brain_assisted_sessions": brain_sessions,
                "brain_usage_pct_sessions": brain_session_pct,
                "by_model": [
                    {
                        "model": r.model,
                        "requests": int(r.req or 0),
                        "cost_usd": round(float(r.cost or 0.0), 4),
                    }
                    for r in rows
                ],
            },
            default=str,
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error("get_usage_stats error: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 20 — get_total_cost
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_total_cost(days: int = 30) -> str:
    """
    Total Claude Code cost across all projects over the last `days`.

    Args:
        days: Look-back window in days (default 30, max 365).
    """
    from datetime import datetime, timedelta
    days = max(1, min(int(days), 365))
    since = datetime.utcnow() - timedelta(days=days)

    db = _open_db()
    try:
        totals = db.execute(
            text("""
                SELECT
                    COUNT(*) AS req,
                    COALESCE(SUM(total_tokens), 0) AS tot_t,
                    COALESCE(SUM(cost_usd), 0)     AS cost,
                    COALESCE(SUM(cache_savings_usd), 0) AS savings
                FROM claude_usage_logs
                WHERE timestamp >= :since
            """),
            {"since": since},
        ).fetchone()

        per_project = db.execute(
            text("""
                SELECT project_id,
                       MAX(project_name) AS project_name,
                       COUNT(*) AS req,
                       COALESCE(SUM(cost_usd), 0) AS cost
                FROM claude_usage_logs
                WHERE timestamp >= :since
                GROUP BY project_id
                ORDER BY cost DESC
                LIMIT 20
            """),
            {"since": since},
        ).fetchall()

        return json.dumps(
            {
                "days": days,
                "total_requests": int(totals.req or 0),
                "total_tokens": int(totals.tot_t or 0),
                "total_cost_usd": round(float(totals.cost or 0.0), 4),
                "total_cache_savings_usd": round(float(totals.savings or 0.0), 4),
                "top_projects": [
                    {
                        "project_id": r.project_id,
                        "project_name": r.project_name,
                        "requests": int(r.req or 0),
                        "cost_usd": round(float(r.cost or 0.0), 4),
                    }
                    for r in per_project
                ],
            },
            default=str,
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error("get_total_cost error: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 21 — get_cache_efficiency
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_cache_efficiency(days: int = 30) -> str:
    """
    How much prompt caching has saved over the last `days`.

    Returns the cache hit ratio (cache_read_tokens / all input-side tokens),
    total cache savings in USD, and what total cost would have been without
    caching.

    Args:
        days: Look-back window in days (default 30, max 365).
    """
    from datetime import datetime, timedelta
    days = max(1, min(int(days), 365))
    since = datetime.utcnow() - timedelta(days=days)

    db = _open_db()
    try:
        row = db.execute(
            text("""
                SELECT
                    COALESCE(SUM(input_tokens), 0)         AS in_t,
                    COALESCE(SUM(cache_creation_tokens),0) AS cc_t,
                    COALESCE(SUM(cache_read_tokens), 0)    AS cr_t,
                    COALESCE(SUM(cost_usd), 0)             AS cost,
                    COALESCE(SUM(cost_without_cache_usd),0) AS cost_no_cache,
                    COALESCE(SUM(cache_savings_usd), 0)    AS savings
                FROM claude_usage_logs
                WHERE timestamp >= :since
            """),
            {"since": since},
        ).fetchone()

        in_t = int(row.in_t or 0)
        cc_t = int(row.cc_t or 0)
        cr_t = int(row.cr_t or 0)
        denom = in_t + cc_t + cr_t
        hit_ratio = (cr_t / denom) if denom else 0.0
        cost = float(row.cost or 0.0)
        cost_no_cache = float(row.cost_no_cache or 0.0)
        savings = float(row.savings or 0.0)
        savings_pct = (savings / cost_no_cache * 100.0) if cost_no_cache else 0.0

        return json.dumps(
            {
                "days": days,
                "input_tokens": in_t,
                "cache_creation_tokens": cc_t,
                "cache_read_tokens": cr_t,
                "cache_hit_ratio": round(hit_ratio, 4),
                "actual_cost_usd": round(cost, 4),
                "cost_without_cache_usd": round(cost_no_cache, 4),
                "savings_usd": round(savings, 4),
                "savings_pct": round(savings_pct, 2),
            },
            default=str,
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error("get_cache_efficiency error: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 22 — sync_usage_logs
# ─────────────────────────────────────────────────────────────────
def _load_usage_parser():
    """Load backend/scripts/claude_usage_parser.py as a module."""
    import importlib.util
    import sys
    parser_path = (
        Path(__file__).resolve().parent.parent / "scripts" / "claude_usage_parser.py"
    )
    spec = importlib.util.spec_from_file_location("claude_usage_parser", parser_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load parser at {parser_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod.__name__] = mod
    spec.loader.exec_module(mod)
    return mod


@mcp.tool()
async def sync_usage_logs(
    logs_path: Optional[str] = None,
    since_days: int = 7,
) -> str:
    """
    Parse Claude Code JSONL usage logs and insert them into claude_usage_logs.

    Reads ~/.claude/projects/*/*.jsonl (or `logs_path` if provided), extracts
    assistant `usage` blocks, applies Opus/Sonnet/Haiku 4 pricing (with cache
    discount/premium), and upserts rows into the analytics tables.

    Args:
        logs_path: Optional path to the Claude projects directory.
            Defaults to ~/.claude/projects/. The path is expanded for ~ and env
            vars and may be relative.
        since_days: Only ingest records from the last N days (default 7,
            max 365). Use a large value (e.g. 365) for a full backfill.

    Returns a JSON summary: files_scanned, records_parsed, inserted, skipped,
    total_cost_usd over the synced window, and brain_usage_pct.
    """
    from datetime import date, datetime, timedelta

    since_days = max(1, min(int(since_days), 365))
    since = (datetime.utcnow().date() - timedelta(days=since_days))

    root: Optional[Path] = None
    if logs_path:
        expanded = os.path.expanduser(os.path.expandvars(str(logs_path)))
        root = Path(expanded).resolve()

    db = _open_db()
    try:
        parser = _load_usage_parser()
        result = parser.sync_usage(db, root=root, since=since)

        # Compute summary stats over the window we just synced.
        since_ts = datetime.combine(since, datetime.min.time())
        window = db.execute(
            text("""
                SELECT
                    COUNT(*) AS req,
                    COALESCE(SUM(cost_usd), 0) AS cost,
                    COALESCE(SUM(CASE WHEN used_brain_context THEN 1 ELSE 0 END), 0) AS brain_req
                FROM claude_usage_logs
                WHERE timestamp >= :since
            """),
            {"since": since_ts},
        ).fetchone()

        # Session-level rollup (a session is brain-assisted if any turn in it called Brain).
        sess = db.execute(
            text("""
                SELECT
                    COUNT(*) AS sessions,
                    COALESCE(SUM(CASE WHEN used_brain THEN 1 ELSE 0 END), 0) AS brain_sessions
                FROM (
                    SELECT COALESCE(session_id, message_id) AS sid,
                           BOOL_OR(used_brain_context)      AS used_brain
                    FROM claude_usage_logs
                    WHERE timestamp >= :since
                    GROUP BY COALESCE(session_id, message_id)
                ) s
            """),
            {"since": since_ts},
        ).fetchone()

        total_req = int(window.req or 0)
        total_cost = float(window.cost or 0.0)
        brain_req = int(window.brain_req or 0)
        brain_pct = round((brain_req / total_req * 100.0), 2) if total_req else 0.0
        total_sessions = int(sess.sessions or 0)
        brain_sessions = int(sess.brain_sessions or 0)
        brain_sess_pct = round(brain_sessions / total_sessions * 100.0, 2) if total_sessions else 0.0

        return json.dumps(
            {
                "status": "ok",
                "root": result.get("root"),
                "since": since.isoformat(),
                "since_days": since_days,
                "files_scanned": result.get("files_scanned", 0),
                "records_parsed": result.get("records_parsed", 0),
                "inserted": result.get("inserted", 0),
                "skipped": result.get("skipped", 0),
                "daily_stat_rows": result.get("daily_stat_rows", 0),
                "window_request_count": total_req,
                "window_total_cost_usd": round(total_cost, 4),
                "window_brain_assisted_count": brain_req,
                "window_brain_usage_pct": brain_pct,
                "window_total_sessions": total_sessions,
                "window_brain_assisted_sessions": brain_sessions,
                "window_brain_usage_pct_sessions": brain_sess_pct,
            },
            default=str,
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("sync_usage_logs error:")
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 23 — upload_local_usage
#
# Self-contained: reads ~/.claude/projects/*.jsonl on the local machine,
# parses assistant turns inline (no dependency on backend/scripts/), and
# POSTs records to /api/usage/sync on Railway. Designed to run in a Claude
# Code MCP context where this file is loaded but the broader backend is not.
# ─────────────────────────────────────────────────────────────────
DEFAULT_USAGE_SYNC_URL = (
    "https://multi-ai-chat-production.up.railway.app/api/usage/sync"
)

# Pricing in USD per token, mirroring backend/scripts/claude_usage_parser.py.
_USAGE_PRICING = {
    "opus":   {"input": 15.00 / 1_000_000, "output": 75.00 / 1_000_000},
    "sonnet": {"input":  3.00 / 1_000_000, "output": 15.00 / 1_000_000},
    "haiku":  {"input":  0.25 / 1_000_000, "output":  1.25 / 1_000_000},
}
_CACHE_READ_DISCOUNT = 0.10
_CACHE_WRITE_PREMIUM = 1.25

_BRAIN_TOOL_NAMES = {
    "search_project_files", "get_file_content", "hybrid_search_files",
    "build_context_for_query", "get_active_project", "get_project_stats",
    "get_index_status", "get_developer_patterns", "get_file_dependencies",
    "get_file_versions", "list_canon_items", "save_session_summary",
    "get_session_summaries", "search_session_memory",
    "search_conversation_memory", "ensure_project_indexed",
    "create_project_with_index", "index_local_project",
    "upload_local_usage",
    # Skills library — startup checklist + reusable workflow snippets
    "get_skill", "list_skills", "save_skill",
    "brain_help",
}


def _detect_model_family(model: str) -> str:
    m = (model or "").lower()
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return "sonnet"


def _calc_usage_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation: int,
    cache_read: int,
) -> tuple:
    p = _USAGE_PRICING[_detect_model_family(model)]
    in_price, out_price = p["input"], p["output"]
    actual = (
        input_tokens * in_price
        + output_tokens * out_price
        + cache_creation * in_price * _CACHE_WRITE_PREMIUM
        + cache_read * in_price * _CACHE_READ_DISCOUNT
    )
    no_cache = (
        (input_tokens + cache_creation + cache_read) * in_price
        + output_tokens * out_price
    )
    return actual, no_cache, max(0.0, no_cache - actual)


def _parse_jsonl_for_usage(
    path: Path,
    since_date,
) -> List[Dict[str, Any]]:
    """Parse one JSONL file, returning records as POST-ready dicts."""
    encoded = path.parent.name
    decoded = encoded.replace("--", "/").replace("-", "/")
    out: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message") or {}
                usage = msg.get("usage") or {}
                if not usage:
                    continue

                model = msg.get("model") or obj.get("model") or "unknown"
                input_tokens = int(usage.get("input_tokens") or 0)
                output_tokens = int(usage.get("output_tokens") or 0)
                cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
                cache_read = int(usage.get("cache_read_input_tokens") or 0)
                if input_tokens + output_tokens + cache_creation + cache_read == 0:
                    continue

                ts_raw = obj.get("timestamp") or msg.get("created_at")
                try:
                    ts = (datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                          if ts_raw else datetime.now(timezone.utc))
                except Exception:
                    ts = datetime.now(timezone.utc)

                if since_date and ts.date() < since_date:
                    continue

                brain_tools: List[str] = []
                content = msg.get("content") or []
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            name = (block.get("name") or "").split("__")[-1]
                            if name in _BRAIN_TOOL_NAMES:
                                brain_tools.append(name)

                actual, no_cache, savings = _calc_usage_cost(
                    model, input_tokens, output_tokens, cache_creation, cache_read,
                )

                out.append({
                    "session_id": obj.get("sessionId") or obj.get("session_id"),
                    "message_id": msg.get("id"),
                    "request_id": obj.get("requestId") or obj.get("request_id"),
                    "timestamp": ts.isoformat(),
                    "model": model,
                    "project_path": decoded,
                    "project_name": encoded,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_creation_tokens": cache_creation,
                    "cache_read_tokens": cache_read,
                    "total_tokens": (input_tokens + output_tokens
                                     + cache_creation + cache_read),
                    "cost_usd": actual,
                    "cost_without_cache_usd": no_cache,
                    "cache_savings_usd": savings,
                    "used_brain_context": bool(brain_tools),
                    "brain_tools_called": brain_tools,
                    "had_retry": bool(obj.get("isApiErrorMessage")),
                    "raw_jsonl_path": str(path),
                })
    except Exception as exc:
        logger.warning("upload_local_usage: failed to parse %s: %s", path, exc)
    return out


@mcp.tool()
async def upload_local_usage(since_days: int = 30) -> str:
    """
    Upload Claude Code usage logs from THIS machine to the Railway backend.

    Reads JSONL files from ~/.claude/projects/ on the local filesystem (where
    Claude Code stores its conversation logs), parses assistant turns that
    carry a `usage` block inline, applies Claude 4.x pricing, and POSTs the
    records to /api/usage/sync on Railway in batches of 50.

    Self-contained: does not import claude_usage_parser, so it works when the
    MCP tool runs in a Claude Code context that doesn't have the backend repo
    on disk. Override the destination with USAGE_SYNC_URL / USAGE_SYNC_TOKEN
    env vars.

    Args:
        since_days: Only upload records from the last N days (default 30,
            max 365).

    Returns a JSON summary: files_scanned, records_found, inserted, skipped,
    total_cost_usd.
    """
    from datetime import timedelta

    since_days = max(1, min(int(since_days), 365))
    since_date = datetime.utcnow().date() - timedelta(days=since_days)

    sync_url = os.getenv("USAGE_SYNC_URL", DEFAULT_USAGE_SYNC_URL)
    token = os.getenv("USAGE_SYNC_TOKEN", _INTERNAL_TOKEN)

    root = Path.home() / ".claude" / "projects"
    if not root.exists():
        return json.dumps(
            {
                "error": f"Claude Code logs directory not found: {root}",
                "files_scanned": 0,
                "records_found": 0,
                "inserted": 0,
                "skipped": 0,
                "total_cost_usd": 0.0,
            },
            ensure_ascii=False,
        )

    files_scanned = 0
    payloads: List[Dict[str, Any]] = []
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            files_scanned += 1
            payloads.extend(_parse_jsonl_for_usage(jsonl, since_date))

    total_cost = sum(float(p.get("cost_usd") or 0.0) for p in payloads)

    if not payloads:
        return json.dumps(
            {
                "files_scanned": files_scanned,
                "records_found": 0,
                "inserted": 0,
                "skipped": 0,
                "total_cost_usd": 0.0,
                "root": str(root),
                "since_days": since_days,
            },
            ensure_ascii=False,
        )

    inserted = 0
    skipped = 0
    batch_size = 50
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for i in range(0, len(payloads), batch_size):
                batch = payloads[i:i + batch_size]
                resp = await client.post(
                    sync_url,
                    json={"records": batch},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json() if resp.content else {}
                inserted += int(data.get("inserted", 0) or 0)
                skipped += int(data.get("skipped", 0) or 0)
    except Exception as exc:
        logger.error("upload_local_usage: POST failed: %s", exc)
        return json.dumps(
            {
                "error": str(exc),
                "files_scanned": files_scanned,
                "records_found": len(payloads),
                "inserted": inserted,
                "skipped": skipped,
                "total_cost_usd": round(total_cost, 4),
                "url": sync_url,
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "files_scanned": files_scanned,
            "records_found": len(payloads),
            "inserted": inserted,
            "skipped": skipped,
            "total_cost_usd": round(total_cost, 4),
            "url": sync_url,
            "root": str(root),
            "since_days": since_days,
        },
        default=str,
        ensure_ascii=False,
    )


# ─────────────────────────────────────────────────────────────────
# Tool 24 — sync_projects_to_claude_md
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def sync_projects_to_claude_md() -> str:
    """
    Fetch all projects from DB and return a formatted markdown table
    ready to paste into ~/.claude/CLAUDE.md.

    Use this to keep the projects table in your global CLAUDE.md up to date.
    Copy the returned table and replace the ## 👤 Мои проекты section.
    """
    db = _open_db()
    try:
        rows = db.execute(
            text("""
                SELECT id, name, description, files_count
                FROM projects
                ORDER BY id
            """),
        ).fetchall()

        lines = [
            "| id | Название | Описание | Файлов |",
            "|----|----------|----------|--------|",
        ]
        for r in rows:
            desc = (r.description or "").replace("|", "\\|").strip()
            lines.append(f"| {r.id} | {r.name} | {desc} | {r.files_count or 0} |")

        table = "\n".join(lines)
        hint = (
            "\n\nPaste this table under ## 👤 Мои проекты in ~/.claude/CLAUDE.md\n"
            "Or run: python backend/scripts/update_claude_md.py"
        )
        return table + hint
    except Exception as exc:
        logger.error("sync_projects_to_claude_md error: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 25 — setup_local_sync
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def setup_local_sync(
    scripts_dir: Optional[str] = None,
    python_path: Optional[str] = None,
) -> str:
    """
    Set up hourly automated sync tasks on the local machine.

    Creates two recurring tasks:
      • BrainSync     — uploads Claude Code usage logs to Railway
      • BrainUpdateMD — refreshes the projects table in ~/.claude/CLAUDE.md

    On macOS: adds crontab entries (runs every hour at :00).
    On Windows: registers Task Scheduler tasks via PowerShell.
    On Linux/server: returns ready-to-paste commands for the user to run locally.

    Args:
        scripts_dir: Absolute path to backend/scripts/. Auto-detected from
            this file's location if omitted.
        python_path: Python executable to use in the tasks. Defaults to the
            interpreter that is currently running this code.
    """
    import platform
    import subprocess
    import sys

    system = platform.system()  # "Darwin", "Windows", "Linux"

    # ── Resolve paths ────────────────────────────────────────────
    py = python_path or sys.executable
    scripts_root = Path(scripts_dir).resolve() if scripts_dir else (
        Path(__file__).resolve().parent.parent / "scripts"
    )
    upload_script = str(scripts_root / "upload_usage_to_railway.py")
    update_md_script = str(scripts_root / "update_claude_md.py")

    # ── macOS — crontab ──────────────────────────────────────────
    if system == "Darwin":
        brain_sync_entry = f"0 * * * * {py} {upload_script}"
        update_md_entry  = f"0 * * * * {py} {update_md_script}"

        try:
            result = subprocess.run(
                ["crontab", "-l"], capture_output=True, text=True
            )
            existing = result.stdout if result.returncode == 0 else ""
        except Exception as exc:
            return f"ERROR reading crontab: {exc}"

        added: list[str] = []
        new_crontab = existing.rstrip("\n")
        for entry, label in [
            (brain_sync_entry, "BrainSync"),
            (update_md_entry,  "BrainUpdateMD"),
        ]:
            if entry not in existing:
                new_crontab += f"\n{entry}"
                added.append(label)

        if not added:
            return (
                "✅ Both cron jobs already exist:\n"
                f"  {brain_sync_entry}\n"
                f"  {update_md_entry}"
            )

        try:
            subprocess.run(
                ["crontab", "-"],
                input=new_crontab + "\n",
                text=True,
                check=True,
            )
        except Exception as exc:
            return f"ERROR writing crontab: {exc}"

        return (
            f"✅ Added {len(added)} cron job(s) on macOS:\n"
            + "\n".join(
                f"  {'BrainSync' if 'upload' in e else 'BrainUpdateMD'}: {e}"
                for e in [brain_sync_entry, update_md_entry]
                if any(label in added for label in ["BrainSync", "BrainUpdateMD"])
            )
            + "\n\nRuns every hour. Verify with: crontab -l"
        )

    # ── Windows — Task Scheduler via PowerShell ──────────────────
    if system == "Windows":
        results: list[str] = []
        tasks = [
            ("BrainSync",     upload_script),
            ("BrainUpdateMD", update_md_script),
        ]
        for task_name, script_path in tasks:
            ps_cmd = (
                f'$a = New-ScheduledTaskAction -Execute "{py}" -Argument "{script_path}"; '
                f'$t = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 1) '
                f'-Once -At "00:00"; '
                f'Register-ScheduledTask -TaskName "{task_name}" -Action $a -Trigger $t '
                f'-RunLevel Highest -Force'
            )
            try:
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True, text=True,
                )
                if proc.returncode == 0:
                    results.append(f"✅ {task_name}: registered")
                else:
                    results.append(f"❌ {task_name}: {proc.stderr.strip()}")
            except Exception as exc:
                results.append(f"❌ {task_name}: {exc}")

        return "Task Scheduler setup (Windows):\n" + "\n".join(results)

    # ── Linux / Railway server — return instructions ──────────────
    cron_lines = [
        f"0 * * * * {py} {upload_script}",
        f"0 * * * * {py} {update_md_script}",
    ]
    return (
        "ℹ️  Running on Linux/server — cannot modify local machine crontab.\n\n"
        "Run these commands on YOUR local machine:\n\n"
        "# 1. Open your crontab:\n"
        "crontab -e\n\n"
        "# 2. Add these two lines:\n"
        + "\n".join(cron_lines)
        + "\n\n"
        "# Or on Windows, open PowerShell as Admin and run:\n"
        + "\n".join(
            f'Register-ScheduledTask -TaskName "{name}" '
            f'-Action (New-ScheduledTaskAction -Execute "python" -Argument "{script}") '
            f'-Trigger (New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 1) -Once -At "00:00") '
            f'-Force'
            for name, script in [("BrainSync", upload_script), ("BrainUpdateMD", update_md_script)]
        )
    )


# ─────────────────────────────────────────────────────────────────
# Tool 26 — setup_prompt_hook
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def setup_prompt_hook(
    scope: str = "user",
    script_path: Optional[str] = None,
    python_path: Optional[str] = None,
) -> str:
    """
    Install a Claude Code UserPromptSubmit hook that nudges Brain MCP usage on
    every user prompt.

    Writes (or merges into) `.claude/settings.json` so each user prompt
    triggers `brain_context_hook.py`, which prints a short system reminder
    telling Claude to call `build_context_for_query` for the active project
    folder. Lifts brain_usage_pct close to 100% without relying on
    CLAUDE.md instruction compliance.

    Args:
        scope: 'user' (default) writes to ~/.claude/settings.json,
            'project' writes to <cwd>/.claude/settings.json.
        script_path: Absolute path to brain_context_hook.py. Auto-detects the
            bundled script under backend/scripts/ if omitted.
        python_path: Python interpreter to invoke. Defaults to the one
            currently running this code (sys.executable).
    """
    import sys as _sys

    if scope not in ("user", "project"):
        return f"ERROR: scope must be 'user' or 'project', got {scope!r}"

    py = python_path or _sys.executable
    hook_script = (
        Path(script_path).resolve() if script_path
        else (Path(__file__).resolve().parent.parent / "scripts" / "brain_context_hook.py")
    )
    if not hook_script.exists():
        return f"ERROR: hook script not found at {hook_script}"

    target = (
        Path.home() / ".claude" / "settings.json" if scope == "user"
        else Path.cwd() / ".claude" / "settings.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    existing: Dict[str, Any] = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except Exception as exc:
            return f"ERROR: failed to parse existing {target}: {exc}"

    hooks = existing.setdefault("hooks", {})
    submit_hooks = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(submit_hooks, list):
        return f"ERROR: hooks.UserPromptSubmit in {target} is not a list"

    command = f'"{py}" "{hook_script}"'

    for entry in submit_hooks:
        if not isinstance(entry, dict):
            continue
        for h in entry.get("hooks") or []:
            if (
                isinstance(h, dict)
                and h.get("type") == "command"
                and "brain_context_hook" in (h.get("command") or "")
            ):
                return (
                    f"✅ Brain hook already installed in {target}\n"
                    f"   Command: {h.get('command')}"
                )

    submit_hooks.append({
        "hooks": [{"type": "command", "command": command}],
    })

    target.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return (
        f"✅ Installed Brain UserPromptSubmit hook in {target}\n"
        f"   Command: {command}\n"
        f"   Restart Claude Code (or open a new session) for it to take effect."
    )


# ─────────────────────────────────────────────────────────────────
# Tool 27 — brain_help
# ─────────────────────────────────────────────────────────────────
_BRAIN_HELP_SECTIONS: Dict[str, List[tuple]] = {
    "files": [
        ("Index this project",       "ensure_project_indexed",   "index files from git"),
        ("Index status",             "get_index_status",         "check indexing status"),
        ("Search files about X",     "search_project_files",     "semantic search"),
        ("Show dependencies for X",  "get_file_dependencies",    "import graph"),
        ("Get file content X",       "get_file_content",         "read file from brain"),
    ],
    "search": [
        ("Find code related to X",   "hybrid_search_files",      "semantic + FTS + graph"),
        ("Build context for X",      "build_context_for_query",  "smart context builder"),
        ("Search conversations",     "search_conversation_memory", "search chat history"),
    ],
    "analytics": [
        ("Sync usage logs",          "sync_usage_logs",          "parse JSONL and sync to brain"),
        ("Upload local usage",       "upload_local_usage",       "sync Claude Code logs from this machine to Brain"),
        ("Show usage report",        "get_usage_stats",          "cost, tokens, brain usage %"),
        ("Total cost",               "get_total_cost",           "spending summary"),
        ("Cache efficiency",         "get_cache_efficiency",     "cache hit rate and savings"),
        ("Setup local auto-sync",    "setup_local_sync",         "add hourly cron/Task Scheduler jobs for BrainSync + BrainUpdateMD"),
        ("Setup Brain prompt hook",  "setup_prompt_hook",        "install UserPromptSubmit hook so Brain is nudged on every prompt"),
    ],
    "memory": [
        ("Save session summary",     "save_session_summary",     "save current session"),
        ("Show summaries",           "get_session_summaries",    "list saved summaries"),
        ("List canon items",         "list_canon_items",         "important project elements"),
        ("Developer patterns",       "get_developer_patterns",   "coding patterns"),
    ],
    "skills": [
        ("Get skill",                "get_skill",                "load skill content by name"),
        ("List skills",              "list_skills",              "list available skills (optional category)"),
        ("Save skill",               "save_skill",               "create or update a skill"),
    ],
    "setup": [
        ("Project stats",            "get_project_stats",          "files, languages, size"),
        ("Active project",           "get_active_project",         "current project info"),
        ("Sync projects to CLAUDE.md", "sync_projects_to_claude_md", "get updated projects table for ~/.claude/CLAUDE.md"),
    ],
    "help": [
        ("help",                     "brain_help",               "show this help"),
    ],
}

_BRAIN_HELP_HEADERS: Dict[str, str] = {
    "files":     "📁 FILES & INDEXING",
    "search":    "🔍 SEARCH & CONTEXT",
    "analytics": "📊 ANALYTICS",
    "memory":    "💾 MEMORY",
    "skills":    "🎯 SKILLS",
    "setup":     "⚙️ PROJECT",
    "help":      "❓ HELP",
}


def _format_brain_help(category: str) -> str:
    cat = (category or "all").strip().lower()
    if cat not in _BRAIN_HELP_SECTIONS and cat != "all":
        valid = ", ".join(["all", *_BRAIN_HELP_SECTIONS.keys()])
        return f"Unknown category '{category}'. Valid: {valid}"

    sections = list(_BRAIN_HELP_SECTIONS.keys()) if cat == "all" else [cat]

    # Compute column widths once across all rows so columns align.
    rows = [r for s in sections for r in _BRAIN_HELP_SECTIONS[s]]
    phrase_w = max((len(r[0]) for r in rows), default=0)
    tool_w = max((len(r[1]) for r in rows), default=0)

    lines: List[str] = []
    if cat == "all":
        lines.append("Brain MCP — available commands")
        lines.append("=" * 60)
        lines.append("")

    for i, sec in enumerate(sections):
        if i > 0:
            lines.append("")
        lines.append(_BRAIN_HELP_HEADERS[sec] + ":")
        for phrase, tool, desc in _BRAIN_HELP_SECTIONS[sec]:
            lines.append(f"  • {phrase.ljust(phrase_w)}  →  {tool.ljust(tool_w)}  — {desc}")

    if cat == "all":
        lines.append("")
        lines.append("Tip: call brain_help(category='analytics') for one section only.")

    return "\n".join(lines)


@mcp.tool()
async def brain_help(category: str = "all") -> str:
    """
    Show available Brain MCP commands grouped by category.

    Args:
        category: One of "all" (default), "files", "search", "analytics",
            "memory", "skills", "setup", or "help". Filters which section is shown.
    """
    return _format_brain_help(category)


# ─────────────────────────────────────────────────────────────────
# Tool 27 — get_skill
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_skill(name: str) -> str:
    """
    Load a skill from the brain_skills library by name.

    Skills are reusable instruction snippets — workflows, checklists, recipes.
    Returns the skill's content as plain text, ready to follow.

    Args:
        name: Exact skill name (e.g. "startup", "commit-deploy", "session-end").
    """
    db = _open_db()
    try:
        row = db.execute(
            text("""
                SELECT name, description, content, category
                FROM brain_skills
                WHERE name = :name
            """),
            {"name": name},
        ).fetchone()
        if not row:
            return json.dumps(
                {"error": f"skill '{name}' not found", "found": False},
                ensure_ascii=False,
            )
        return (
            f"# Skill: {row.name}  ({row.category})\n"
            f"{row.description or ''}\n"
            f"\n"
            f"{row.content}"
        )
    except Exception as exc:
        logger.error("get_skill error: %s", exc)
        return json.dumps({"error": str(exc), "found": False}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 28 — list_skills
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def list_skills(category: Optional[str] = None) -> str:
    """
    List available skills with their descriptions and categories.

    Args:
        category: Optional filter — one of 'workflow', 'coding', 'deploy',
            'debug', 'review'. If omitted, returns all skills.
    """
    db = _open_db()
    try:
        if category:
            rows = db.execute(
                text("""
                    SELECT name, description, category, updated_at
                    FROM brain_skills
                    WHERE category = :category
                    ORDER BY name
                """),
                {"category": category},
            ).fetchall()
        else:
            rows = db.execute(
                text("""
                    SELECT name, description, category, updated_at
                    FROM brain_skills
                    ORDER BY category, name
                """),
            ).fetchall()

        skills = [
            {
                "name": r.name,
                "description": r.description,
                "category": r.category,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
        return json.dumps(
            {"count": len(skills), "category_filter": category, "skills": skills},
            ensure_ascii=False,
            default=str,
        )
    except Exception as exc:
        logger.error("list_skills error: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool 29 — save_skill
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def save_skill(
    name: str,
    description: str,
    content: str,
    category: str,
) -> str:
    """
    Create or update a skill in the brain_skills library.

    On name conflict, the existing row is updated (content / description /
    category overwritten, updated_at refreshed).

    Args:
        name: Unique skill name (slug-style, e.g. "commit-deploy").
        description: One-line summary shown by list_skills.
        content: Full skill body — markdown / numbered steps / checklist.
        category: One of 'workflow', 'coding', 'deploy', 'debug', 'review'.
    """
    valid_categories = {"workflow", "coding", "deploy", "debug", "review"}
    if category not in valid_categories:
        return json.dumps(
            {
                "error": f"invalid category '{category}'",
                "valid": sorted(valid_categories),
                "saved": False,
            },
            ensure_ascii=False,
        )

    db = _open_db()
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        row = db.execute(
            text("""
                INSERT INTO brain_skills (name, description, content, category, created_at, updated_at)
                VALUES (:name, :description, :content, :category, :now, :now)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    content     = EXCLUDED.content,
                    category    = EXCLUDED.category,
                    updated_at  = EXCLUDED.updated_at
                RETURNING id, (xmax = 0) AS inserted
            """),
            {
                "name": name,
                "description": description,
                "content": content,
                "category": category,
                "now": now,
            },
        ).fetchone()
        db.commit()
        skill_id = row[0] if row else None
        was_insert = bool(row[1]) if row else False
        logger.info(
            "save_skill: %s id=%s name=%s",
            "inserted" if was_insert else "updated", skill_id, name,
        )
        return json.dumps(
            {
                "saved": True,
                "skill_id": skill_id,
                "name": name,
                "action": "inserted" if was_insert else "updated",
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        db.rollback()
        logger.error("save_skill error: %s", exc)
        return json.dumps({"error": str(exc), "saved": False}, ensure_ascii=False)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────
# Tool: generate_image (via vendshop.shop Studio API)
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def generate_image(
    prompt: str,
    provider: str = "flux",
    quality: str = "fast",
    aspect_ratio: str = "1:1",
) -> str:
    """
    Generate an image using vendshop.shop AI Studio (Flux or Grok Aurora).

    Use this when the user asks to create, draw, or generate any image.
    Returns a public URL to the generated image.

    Args:
        prompt: Detailed image description in English. Be specific about:
                style, lighting, composition, subject, background.
                Example: "Professional barber shop interior, black leather chairs,
                          neon signs, moody atmospheric lighting, photorealistic"
        provider: "flux" (default, high quality, ~5-15s) or
                  "grok" (xAI Aurora, creative, requires user's xAI key)
        quality: "fast" (Flux Schnell, ~3-5s) or "good" (Flux Dev, ~15s, more detailed)
        aspect_ratio: "1:1" (square), "16:9" (landscape), "9:16" (portrait/Reels),
                      "4:3", "3:4"

    Returns:
        JSON with image URL. If url is empty string, generation failed.
    """
    vendshop_url = os.getenv("VENDSHOP_API_URL", "https://vendshop.shop")
    api_key = os.getenv("VENDSHOP_BRAIN_API_KEY", "")

    if not api_key:
        return json.dumps(
            {
                "error": "VENDSHOP_BRAIN_API_KEY not configured in Railway env vars",
                "url": "",
            },
            ensure_ascii=False,
        )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{vendshop_url}/api/brain/generate-image",
                json={
                    "prompt": prompt,
                    "provider": provider,
                    "aspect_ratio": aspect_ratio,
                    "quality": quality,
                },
                headers={"x-brain-api-key": api_key},
            )

            if resp.status_code == 401:
                return json.dumps(
                    {
                        "error": "Unauthorized — check VENDSHOP_BRAIN_API_KEY matches BRAIN_API_KEY in vendly-storefront",
                        "url": "",
                    },
                    ensure_ascii=False,
                )

            resp.raise_for_status()
            data = resp.json()

            image_url = data.get("url") or data.get("media", {}).get("url", "")
            return json.dumps(
                {
                    "url": image_url,
                    "media_type": "image",
                    "prompt": prompt,
                    "provider": provider,
                    "message": (
                        f"Image generated: {image_url}"
                        if image_url
                        else "Generation failed — no URL returned"
                    ),
                },
                ensure_ascii=False,
            )

    except httpx.TimeoutException:
        return json.dumps(
            {
                "error": "Image generation timed out (60s). Try a shorter prompt or 'fast' quality.",
                "url": "",
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error("generate_image MCP tool error: %s", exc)
        return json.dumps({"error": str(exc), "url": ""}, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────
# Tool: create_video (via vendshop.shop Studio API — Kling)
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def create_video(
    prompt: str,
    image_url: Optional[str] = None,
    duration: int = 5,
    aspect_ratio: str = "9:16",
) -> str:
    """
    Generate a video using vendshop.shop AI Studio (Kling AI).

    Can generate video from text prompt, or animate an existing image.
    Returns a job_id — video takes 2-5 minutes to generate.

    After calling this tool, tell the user:
    "Video generation started! It will take 2-5 minutes.
     You can check status at: vendshop.shop/studio"

    Args:
        prompt: Motion and scene description in English.
                Example: "Slow cinematic zoom into the barber chair,
                          warm golden lighting, hair falling in slow motion"
        image_url: Optional. URL of an existing image to animate (image-to-video).
                   If provided, Kling will animate this specific image.
                   If None, Kling generates video from text only.
        duration: 5 or 10 seconds.
        aspect_ratio: "9:16" (vertical/Reels default), "16:9" (landscape), "1:1" (square)

    Returns:
        JSON with job_id for status polling, or error.
    """
    vendshop_url = os.getenv("VENDSHOP_API_URL", "https://vendshop.shop")
    api_key = os.getenv("VENDSHOP_BRAIN_API_KEY", "")

    if not api_key:
        return json.dumps(
            {
                "error": "VENDSHOP_BRAIN_API_KEY not configured",
                "job_id": "",
            },
            ensure_ascii=False,
        )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{vendshop_url}/api/brain/create-video",
                json={
                    "prompt": prompt,
                    "image_url": image_url,
                    "duration": duration,
                    "aspect_ratio": aspect_ratio,
                },
                headers={"x-brain-api-key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()

            job_id = data.get("jobId") or data.get("job_id", "")
            return json.dumps(
                {
                    "job_id": job_id,
                    "status": "started" if job_id else "failed",
                    "message": (
                        f"Video generation started! Job ID: {job_id}. "
                        f"Takes ~2-5 minutes. Check status at vendshop.shop/studio"
                        if job_id
                        else f"Failed to start video: {data.get('error', 'unknown')}"
                    ),
                    "poll_url": f"{vendshop_url}/api/studio/job/{job_id}" if job_id else "",
                },
                ensure_ascii=False,
            )

    except Exception as exc:
        logger.error("create_video MCP tool error: %s", exc)
        return json.dumps({"error": str(exc), "job_id": ""}, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────
# Tool: update_site_media (via vendshop.shop Brain API)
# ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def update_site_media(
    media_url: str,
    section: str = "hero",
    store_slug: Optional[str] = None,
    lead_email: Optional[str] = None,
    media_type: str = "image",
) -> str:
    """
    Place a generated image or video onto a vendshop.shop site.

    Use this AFTER generate_image or create_video to complete the full pipeline:
    generate image → animate to video → place on site.

    The full pipeline in one conversation:
    1. generate_image("barber shop interior") → image_url
    2. create_video(prompt="zoom in slowly", image_url=image_url) → job_id
    3. update_site_media(media_url=image_url, section="hero", store_slug="berlin-barber")

    Args:
        media_url: URL of the image or video to place on the site.
                   Use the URL returned by generate_image or the video URL after it's ready.
        section: Where to place the media:
                 "hero" — main hero image/video on the homepage
                 "logo" — store logo
                 "gallery" — add to the gallery (keeps last 20)
        store_slug: Slug of the store (e.g. "berlin-barber", "lumiere-nails").
                    Use this for self-serve user stores.
                    Find slug in the store URL: vendshop.shop/store/{slug}
        lead_email: Email of the lead/client (e.g. "client@email.com").
                    Use this for client sites managed via Lead model.
                    One of store_slug or lead_email is required.
        media_type: "image" (default) or "video".
                    When section="hero" and media_type="video", stores as heroVideo.

    Returns:
        JSON with update confirmation or error.
    """
    vendshop_url = os.getenv("VENDSHOP_API_URL", "https://vendshop.shop")
    api_key = os.getenv("VENDSHOP_BRAIN_API_KEY", "")

    if not api_key:
        return json.dumps({
            "error": "VENDSHOP_BRAIN_API_KEY not configured",
            "updated": False,
        }, ensure_ascii=False)

    if not store_slug and not lead_email:
        return json.dumps({
            "error": "Either store_slug or lead_email is required.",
            "updated": False,
        }, ensure_ascii=False)

    try:
        payload = {
            "media_url": media_url,
            "section": section,
            "media_type": media_type,
        }
        if store_slug:
            payload["store_slug"] = store_slug
        if lead_email:
            payload["lead_email"] = lead_email

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{vendshop_url}/api/brain/update-site-media",
                json=payload,
                headers={"x-brain-api-key": api_key},
            )

            if resp.status_code == 401:
                return json.dumps({
                    "error": "Unauthorized — check VENDSHOP_BRAIN_API_KEY",
                    "updated": False,
                }, ensure_ascii=False)

            if resp.status_code == 404:
                target = store_slug or lead_email
                return json.dumps({
                    "error": f"Site not found: {target}. Check the slug or email.",
                    "updated": False,
                }, ensure_ascii=False)

            resp.raise_for_status()
            data = resp.json()

            return json.dumps({
                "updated": data.get("updated", False),
                "target": data.get("target"),
                "section": section,
                "media_url": media_url,
                "message": (
                    f"✅ {section.capitalize()} updated on {store_slug or lead_email}! "
                    f"Changes are live at vendshop.shop"
                    if data.get("updated")
                    else f"Update failed: {data.get('error', 'unknown')}"
                ),
            }, ensure_ascii=False)

    except httpx.TimeoutException:
        return json.dumps({
            "error": "Request timed out. Try again.",
            "updated": False,
        }, ensure_ascii=False)
    except Exception as exc:
        logger.error("update_site_media MCP tool error: %s", exc)
        return json.dumps({"error": str(exc), "updated": False}, ensure_ascii=False)

__all__ = ["mcp"]
