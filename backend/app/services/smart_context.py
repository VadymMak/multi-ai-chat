"""
Smart Context Builder - Universal context engine.
FIXED: Now includes actual file CONTENT, not just metadata!
"""

import json
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

# Import existing services
from app.services import vector_service
from app.memory.manager import MemoryManager
from app.memory.models import Project


def format_recent(messages: List[Dict[str, Any]]) -> str:
    """Format recent messages for context"""
    if not messages:
        return "No recent messages"
    
    lines = []
    for msg in messages[-5:]:  # Last 5 only
        sender = msg.get("sender", "unknown")
        text_content = msg.get("text", "")[:200]  # Truncate to 200 chars
        lines.append(f"[{sender}]: {text_content}")
    
    return "\n".join(lines)


def format_git_structure(git_data: Dict[str, Any]) -> str:
    """Format Git structure for context"""
    if not git_data:
        return "No project structure"
    
    files = git_data.get("files", [])
    git_url = git_data.get("git_url", "unknown")
    files_count = len(files)
    
    # List first 50 files
    file_list = "\n".join([f"  - {f['path']}" for f in files[:50]])
    
    if files_count > 50:
        file_list += f"\n  ... and {files_count - 50} more files"
    
    return f"Repository: {git_url}\nFiles ({files_count}):\n{file_list}"


def format_relevant_files_with_content(
    files: List[Dict[str, Any]], 
    db: Session,
    project_id: int,
    max_content_chars: int = 4000
) -> str:
    """
    Format relevant code files WITH actual content for AI context.
    
    FIXED: Previously only showed metadata, now shows real code!
    """
    if not files:
        return "No relevant files found"
    
    lines = []
    chars_used = 0
    max_files = 3  # Limit to top 3 files to save tokens
    
    for f in files[:max_files]:
        path = f.get("file_path", "unknown")
        lang = f.get("language", "")
        similarity = f.get("similarity", 0)
        
        # Header with file info
        lines.append(f"📄 **{path}** ({lang}, {similarity:.0%} match)")
        
        # Get actual content from DB
        try:
            result = db.execute(text("""
                SELECT content FROM file_embeddings
                WHERE project_id = :project_id AND file_path = :file_path
            """), {"project_id": project_id, "file_path": path}).fetchone()
            
            if result and result[0]:
                content = result[0]
                
                # Calculate remaining space
                remaining_chars = max_content_chars - chars_used
                
                if remaining_chars > 500:  # Only add if we have space
                    # Truncate content if needed
                    if len(content) > remaining_chars:
                        content = content[:remaining_chars] + "\n... (truncated)"
                    
                    lines.append(f"```{lang}")
                    lines.append(content)
                    lines.append("```")
                    
                    chars_used += len(content)
                else:
                    # Just show metadata if no space
                    metadata = f.get("metadata", {})
                    if metadata.get("functions"):
                        lines.append(f"   functions: {', '.join(metadata['functions'][:5])}")
                    if metadata.get("classes"):
                        lines.append(f"   classes: {', '.join(metadata['classes'][:5])}")
            else:
                lines.append("   (content not available)")
                
        except Exception as e:
            print(f"⚠️ [format_files] Failed to get content for {path}: {e}")
            lines.append(f"   (error loading content)")
        
        lines.append("")  # Empty line between files
    
    return "\n".join(lines)


async def build_smart_context(
    project_id: int,
    role_id: int, 
    query: str,
    session_id: str,
    db: Session,
    memory: MemoryManager
) -> str:
    """
    Build Smart Context using existing services.
    Returns ~4K tokens instead of 150K.
    
    Components:
    1. pgvector semantic search (relevant past conversations)
    2. Recent 5 messages (immediate context)
    3. Summaries (high-level context)
    4. Git structure (if available)
    5. Relevant code files WITH CONTENT from file_embeddings
    """
    
    print(f"🎯 [Smart Context] Building for project={project_id}, role={role_id}, query={query[:50]}...")
    
    parts = []
    
    # 1. pgvector semantic search (EXISTING!)
    try:
        relevant_context = vector_service.get_relevant_context(
            db=db,
            query=query,
            session_id=session_id,
            limit=3
        )
        if relevant_context:
            parts.append(f"📌 RELEVANT CONTEXT:\n{relevant_context}")
            print(f"✅ [Smart Context] Added relevant context from pgvector")
    except Exception as e:
        print(f"⚠️ [Smart Context] pgvector search failed: {e}")
    
    # 2. Recent 5 messages (EXISTING!)
    try:
        recent_data = memory.retrieve_messages(
            project_id=str(project_id),
            role_id=role_id,
            limit=5,
            chat_session_id=session_id,
            for_display=False 
        )
        # Handle list slicing properly
        all_messages = recent_data.get("messages", [])
        recent_messages = all_messages[-5:] if len(all_messages) > 5 else all_messages
        recent_text = format_recent(recent_messages)
        parts.append(f"📌 RECENT CONVERSATION:\n{recent_text}")
        print(f"✅ [Smart Context] Added {len(recent_messages)} recent messages")
    except Exception as e:
        print(f"⚠️ [Smart Context] Recent messages failed: {e}")
    
    # 3. Summaries (EXISTING!)
    try:
        summaries = memory.load_recent_summaries(
            project_id=str(project_id),
            role_id=role_id,
            limit=3
        )
        if summaries:
            summaries_text = "\n".join(summaries)
            parts.append(f"📌 SUMMARIES:\n{summaries_text}")
            print(f"✅ [Smart Context] Added {len(summaries)} summaries")
    except Exception as e:
        print(f"⚠️ [Smart Context] Summaries failed: {e}")
    
    # 4. Git structure (if exists) - OPTIONAL BONUS
    try:
        project = db.query(Project).filter_by(id=project_id).first()
        if project and project.git_url and project.project_structure:
            db.refresh(project)
            git_data = json.loads(project.project_structure)
            git_text = format_git_structure(git_data)
            parts.append(f"📌 PROJECT STRUCTURE:\n{git_text}")
            print(f"✅ [Smart Context] Added Git structure ({len(git_data.get('files', []))} files)")
        else:
            print(f"ℹ️ [Smart Context] No Git structure available")
    except Exception as e:
        print(f"⚠️ [Smart Context] Git structure failed: {e}")
    
    # ============================================================
    # 5. Relevant code files WITH CONTENT
    # FIXED: Now includes actual code, not just metadata!
    # ============================================================
    try:
        from app.services.file_indexer import FileIndexer
        
        indexer = FileIndexer(db)
        
        # Search files by project_id
        print(f"🔍 [Smart Context] Searching indexed files for project={project_id}...")
        relevant_files = await indexer.search_files(
            project_id=project_id,
            query=query,
            limit=5
        )
        
        if relevant_files:
            # FIXED: Use new function that includes content!
            files_text = format_relevant_files_with_content(
                files=relevant_files,
                db=db,
                project_id=project_id,
                max_content_chars=4000  # ~1000 tokens for code
            )
            parts.append(f"📌 RELEVANT CODE FILES:\n{files_text}")
            print(f"✅ [Smart Context] Added {len(relevant_files)} relevant code files WITH content")
        else:
            print(f"ℹ️ [Smart Context] No indexed files found for query")
            
    except Exception as e:
        print(f"⚠️ [Smart Context] File search failed: {e}")
        import traceback
        traceback.print_exc()
    
    result = "\n\n".join(parts)
    print(f"✅ [Smart Context] Built context with {len(parts)} components")
    
    return result


# ============================================================
# Sync wrapper for backwards compatibility
# ============================================================
def build_smart_context_sync(
    project_id: int,
    role_id: int, 
    query: str,
    session_id: str,
    db: Session,
    memory: MemoryManager
) -> str:
    """
    Synchronous wrapper for build_smart_context.
    Use this if calling from sync code.
    """
    import asyncio
    
    try:
        # Try to get existing event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running (e.g., in FastAPI), create task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    build_smart_context(project_id, role_id, query, session_id, db, memory)
                )
                return future.result()
        else:
            return loop.run_until_complete(
                build_smart_context(project_id, role_id, query, session_id, db, memory)
            )
    except RuntimeError:
        # No event loop, create new one
        return asyncio.run(
            build_smart_context(project_id, role_id, query, session_id, db, memory)
        )