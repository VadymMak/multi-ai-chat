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
from typing import Any, Dict, List, Optional

import httpx

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
                    (:project_id, :project_id_int, NULL, 'SESSION_SUMMARY', :title, :body, :tags::jsonb, :terms, :created_at, TRUE)
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


__all__ = ["mcp"]
