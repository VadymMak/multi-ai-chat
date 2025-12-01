"""
Smart Context Builder - Universal context engine.
Uses existing services: vector_service + memory/manager.
"""

import json
from typing import List, Dict, Any
from sqlalchemy.orm import Session

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
        text = msg.get("text", "")[:200]  # Truncate to 200 chars
        lines.append(f"[{sender}]: {text}")
    
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


def build_smart_context(
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
    # 2. Recent 5 messages (EXISTING!)
    try:
        recent_data = memory.retrieve_messages(
            project_id=str(project_id),
            role_id=role_id,
            limit=5,
            chat_session_id=session_id,
            for_display=False 
        )
        # ✅ FIX: Handle list slicing properly
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
    
    # 4. Git structure (if exists)
    try:
        project = db.query(Project).filter_by(id=project_id).first()
        if project and project.git_url and project.project_structure:
            db.refresh(project)
            git_data = json.loads(project.project_structure)
            git_text = format_git_structure(git_data)
            parts.append(f"📌 PROJECT STRUCTURE:\n{git_text}")
            print(f"✅ [Smart Context] Added Git structure ({len(git_data.get('files', []))} files)")
        else:
            print(f"ℹ️ [Smart Context] No Git structure (project without Git)")
    except Exception as e:
        print(f"⚠️ [Smart Context] Git structure failed: {e}")
    
    result = "\n\n".join(parts)
    print(f"✅ [Smart Context] Built context with {len(parts)} components")
    
    return result