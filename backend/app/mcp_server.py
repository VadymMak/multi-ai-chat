"""
MCP (Model Context Protocol) server for multi-ai-chat.

Exposes 8 tools over SSE transport so Claude Desktop / Claude Code
can query the existing FastAPI backend data without touching the REST API.

Mount point  : /mcp             (added in main.py)
SSE endpoint : /mcp/sse
POST endpoint: /mcp/messages/

Tools
-----
1. search_project_files       — semantic code search via pgvector
2. get_file_content           — full content of an indexed file
3. get_file_dependencies      — import graph for a file or whole project
4. search_conversation_memory — semantic search over chat history
5. list_canon_items           — ADR / CHANGELOG / BACKLOG / GLOSSARY / PMD items
6. get_project_stats          — indexing statistics for a project
7. get_file_versions          — change history for an indexed file
8. build_context_for_query    — full RAG context (calls smart_context)

Design rules
------------
- Every tool is an async function.
- DB sessions are opened and closed inside each handler (not via FastAPI DI).
- Exceptions are caught; {"error": str(exc)} is returned instead of raising.
- No existing router files are modified.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from mcp import types
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from sqlalchemy import text
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route

from app.memory.db import SessionLocal
from app.memory.manager import MemoryManager
from app.services.file_indexer import FileIndexer
from app.services.smart_context import build_smart_context

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# MCP Server instance
# ─────────────────────────────────────────────────────────────────

mcp = Server("multi-ai-chat-mcp")


# ─────────────────────────────────────────────────────────────────
# Helper – open a short-lived DB session (bypasses FastAPI DI)
# ─────────────────────────────────────────────────────────────────

def _open_db():
    """Return a new SQLAlchemy Session. Caller is responsible for closing it."""
    return SessionLocal()


# ─────────────────────────────────────────────────────────────────
# Tool registry
# ─────────────────────────────────────────────────────────────────

@mcp.list_tools()
async def _list_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name="search_project_files",
            description=(
                "Semantic search across indexed project files using pgvector cosine similarity. "
                "Returns a ranked list of matching files with similarity scores, language, "
                "line count, and extracted metadata (functions, classes, imports)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Numeric project ID to search within.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Natural language search query.",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 5,
                        "description": "Maximum number of results to return (default 5).",
                    },
                    "language": {
                        "type": "string",
                        "description": (
                            "Optional language filter "
                            "(e.g. 'python', 'typescript', 'javascript', 'go')."
                        ),
                    },
                },
                "required": ["project_id", "query"],
            },
        ),
        types.Tool(
            name="get_file_content",
            description=(
                "Retrieve the full source content of a specific indexed file "
                "along with its detected language, line count, and extracted metadata."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Numeric project ID.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Exact file path as stored in the index (e.g. 'backend/app/main.py').",
                    },
                },
                "required": ["project_id", "file_path"],
            },
        ),
        types.Tool(
            name="get_file_dependencies",
            description=(
                "Get the import/dependency graph from the file_dependencies table. "
                "When file_path is provided, returns only that file's outgoing imports. "
                "When file_path is omitted, returns all dependencies in the project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Numeric project ID.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "Optional. File path to scope the query "
                            "(omit to get all project dependencies)."
                        ),
                    },
                },
                "required": ["project_id"],
            },
        ),
        types.Tool(
            name="search_conversation_memory",
            description=(
                "Semantic search over conversation history stored in memory_entries "
                "using pgvector cosine similarity. Returns past messages and summaries "
                "ranked by semantic similarity to the query."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID as stored in memory_entries (string).",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query to find semantically similar messages.",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 5,
                        "description": "Maximum number of results to return (default 5).",
                    },
                    "role_id": {
                        "type": "integer",
                        "description": "Optional. Filter messages by assistant/role ID.",
                    },
                },
                "required": ["project_id", "query"],
            },
        ),
        types.Tool(
            name="list_canon_items",
            description=(
                "List canonical knowledge items from the canon_items table. "
                "Supported types: ADR (architectural decisions), CHANGELOG, "
                "BACKLOG, GLOSSARY, PMD. "
                "Only active items are returned by default."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID as stored in canon_items (string).",
                    },
                    "type": {
                        "type": "string",
                        "description": (
                            "Optional type filter: "
                            "ADR | CHANGELOG | BACKLOG | GLOSSARY | PMD."
                        ),
                    },
                    "is_active": {
                        "type": "boolean",
                        "default": True,
                        "description": "When true (default), only active items are returned.",
                    },
                },
                "required": ["project_id"],
            },
        ),
        types.Tool(
            name="get_project_stats",
            description=(
                "Return file indexing statistics for a project: total file count, "
                "number of distinct languages, total line count, total size in KB, "
                "last index timestamp, per-language breakdown, and dependency counts."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Numeric project ID.",
                    },
                },
                "required": ["project_id"],
            },
        ),
        types.Tool(
            name="get_file_versions",
            description=(
                "Return the full version history for an indexed file from the "
                "file_versions table. Each entry includes version number, change type "
                "(create/edit/delete/rollback), change source (user/ai_edit/ai_create/ai_fix), "
                "commit-style message, AI model used (if any), and timestamp."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Numeric project ID.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Exact file path as stored in file_embeddings.",
                    },
                },
                "required": ["project_id", "file_path"],
            },
        ),
        types.Tool(
            name="build_context_for_query",
            description=(
                "Build a full RAG context string for a query against a project. "
                "Internally calls build_smart_context() which combines: "
                "project file tree (START position), past decision summaries (MIDDLE), "
                "recent conversation messages (MIDDLE), semantically similar past "
                "discussions (MIDDLE), and relevant code files with content (END). "
                "Returns ~4 000-token context string ready for LLM injection."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID – accepted as string or integer.",
                    },
                    "query": {
                        "type": "string",
                        "description": "The user query to build context for.",
                    },
                    "role_id": {
                        "type": "integer",
                        "description": "Optional assistant/role ID (defaults to 0).",
                    },
                },
                "required": ["project_id", "query"],
            },
        ),
    ]


# ─────────────────────────────────────────────────────────────────
# Tool call dispatcher
# ─────────────────────────────────────────────────────────────────

@mcp.call_tool()
async def _call_tool(
    name: str,
    arguments: Optional[Dict[str, Any]],
) -> List[types.TextContent]:
    """Route incoming tool calls to individual async handlers."""
    args: Dict[str, Any] = arguments or {}

    _handlers = {
        "search_project_files": _tool_search_project_files,
        "get_file_content": _tool_get_file_content,
        "get_file_dependencies": _tool_get_file_dependencies,
        "search_conversation_memory": _tool_search_conversation_memory,
        "list_canon_items": _tool_list_canon_items,
        "get_project_stats": _tool_get_project_stats,
        "get_file_versions": _tool_get_file_versions,
        "build_context_for_query": _tool_build_context_for_query,
    }

    handler = _handlers.get(name)
    if handler is None:
        result: Any = {"error": f"Unknown tool: {name!r}"}
    else:
        try:
            result = await handler(args)
        except Exception as exc:
            logger.exception("MCP tool %r raised unexpectedly", name)
            result = {"error": str(exc)}

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, default=str, ensure_ascii=False),
        )
    ]


# ─────────────────────────────────────────────────────────────────
# Tool 1 — search_project_files
# Calls: FileIndexer.search_files(project_id, query, limit, language, db)
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
        # Normalise metadata: may arrive as raw JSON string from the DB row
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
# Direct DB query on file_embeddings
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
            return {
                "error": (
                    f"File not found: {file_path!r} "
                    f"in project {project_id}. "
                    "Make sure the project is indexed."
                )
            }

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
# Direct DB query on file_dependencies
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
                "imports_what": (
                    json.loads(r.imports_what) if r.imports_what else []
                ),
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
# Direct pgvector query on memory_entries scoped to project_id.
# (vector_service.search_similar_messages is scoped to chat_session_id;
#  for the MCP layer we need project-level search instead.)
# ─────────────────────────────────────────────────────────────────

async def _tool_search_conversation_memory(args: Dict[str, Any]) -> Any:
    project_id: str = str(args["project_id"])
    query: str = str(args["query"])
    limit: int = int(args.get("limit", 5))
    role_id: Optional[int] = (
        int(args["role_id"]) if args.get("role_id") is not None else None
    )

    db = _open_db()
    try:
        # Import here to keep module-level imports clean and avoid
        # triggering the lazy OpenAI client before it is needed.
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
                SELECT
                    raw_text,
                    summary,
                    timestamp,
                    is_summary,
                    1 - (embedding <=> CAST(:query_embedding AS vector)) AS similarity
                FROM memory_entries
                WHERE project_id  = :project_id
                  AND embedding   IS NOT NULL
                  AND deleted     = FALSE
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
                "timestamp": (
                    r.timestamp.isoformat() if r.timestamp else None
                ),
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
# Direct DB query on canon_items
# ─────────────────────────────────────────────────────────────────

async def _tool_list_canon_items(args: Dict[str, Any]) -> Any:
    project_id: str = str(args["project_id"])
    item_type: Optional[str] = args.get("type")
    is_active: bool = bool(args.get("is_active", True))

    db = _open_db()
    try:
        type_clause = "AND type = :item_type" if item_type else ""
        params: Dict[str, Any] = {
            "project_id": project_id,
            "is_active": is_active,
        }
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
                    "created_at": (
                        r.created_at.isoformat() if r.created_at else None
                    ),
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
# Calls: FileIndexer.get_project_stats(project_id)
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
# Direct DB query on file_versions JOIN file_embeddings
# ─────────────────────────────────────────────────────────────────

async def _tool_get_file_versions(args: Dict[str, Any]) -> Any:
    project_id: int = int(args["project_id"])
    file_path: str = str(args["file_path"])

    db = _open_db()
    try:
        rows = db.execute(
            text("""
                SELECT
                    fv.version_number,
                    fv.change_type,
                    fv.change_source,
                    fv.change_message,
                    fv.ai_model,
                    fv.created_at
                FROM file_versions   fv
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
                "created_at": (
                    r.created_at.isoformat() if r.created_at else None
                ),
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
# Calls: build_smart_context() from services/smart_context.py
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
            session_id="",   # no active chat session for MCP queries
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
# SSE transport + Starlette sub-application
#
# FastAPI mounts this at /mcp (see main.py).
# Claude connects to:
#   GET  /mcp/sse          — opens the SSE stream
#   POST /mcp/messages/    — sends JSON-RPC messages back to the server
# ─────────────────────────────────────────────────────────────────

_sse_transport = SseServerTransport("/mcp/messages/")


async def _handle_sse(request: Request) -> None:
    """Accept a new SSE connection and run the MCP server on it."""
    async with _sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        await mcp.run(
            read_stream,
            write_stream,
            mcp.create_initialization_options(),
        )


# Starlette sub-app that main.py mounts at /mcp
mcp_starlette_app = Starlette(
    routes=[
        Route("/sse", endpoint=_handle_sse),
        Mount("/messages/", app=_sse_transport.handle_post_message),
    ]
)
