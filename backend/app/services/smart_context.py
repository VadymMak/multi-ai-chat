"""
Smart Context Builder - Universal context engine.

REFACTORED v2.0:
- Removed Git structure (using file_embeddings as source of truth)
- Reordered sections based on "Lost in the Middle" research:
  * START (high attention): Project Tree
  * MIDDLE (lower attention): Summaries, Messages, Semantic
  * END (high attention): Relevant Code
"""

from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

# Import existing services
from app.services import vector_service
from app.memory.manager import MemoryManager


def format_recent(messages: List[Dict[str, Any]]) -> str:
    """
    Format recent messages for context.
    SKIP bad AI responses that say "context does not include"
    """
    if not messages:
        return "No recent messages"
    
    # Bad response patterns to skip
    bad_patterns = [
        "provided context does not include",
        "context does not include",
        "i don't see any information",
        "the context doesn't contain",
        "no specific information"
    ]
    
    lines = []
    
    for msg in messages[-5:]:  # Last 5 only
        sender = msg.get("sender", "unknown")
        msg_text = msg.get("text", "")
        
        # Skip bad AI responses
        if sender in ["openai", "anthropic", "assistant"]:
            text_lower = msg_text.lower()
            if any(pattern in text_lower for pattern in bad_patterns):
                print(f"⏭️ [format_recent] Skipped bad response from {sender}")
                continue
        
        # Truncate to 200 chars
        text_preview = msg_text[:200]
        lines.append(f"[{sender}]: {text_preview}")
    
    return "\n".join(lines) if lines else "No relevant recent messages"


def format_relevant_files_with_content(
    files: List[Dict[str, Any]], 
    db: Session,
    project_id: int,
    max_content_chars: int = 4000
) -> str:
    """
    Format relevant code files WITH actual content for AI context.
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
            
            print(f"🔍 [DEBUG smart_context] File: {path}")
            print(f"   Result exists: {result is not None}")

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
    
    ORDER BASED ON RESEARCH ("Lost in the Middle" effect):
    - START (high attention): Project structure
    - MIDDLE (lower attention): Summaries, messages, semantic context
    - END (high attention): Relevant code files
    
    Components:
    1. 📁 Project Tree (START - from file_embeddings, NOT Git!)
    2. 📝 Summaries (MIDDLE - past decisions)
    3. 💬 Recent messages (MIDDLE - conversation flow)
    4. 🔍 Semantic context (MIDDLE - related past discussions)
    5. 📄 Relevant code (END - similar code with content)
    """
    
    print(f"🎯 [Smart Context] Building for project={project_id}, role={role_id}, query={query[:50]}...")
    
    parts = []
    
    # ============================================================
    # 1. PROJECT TREE (START - high attention!)
    # Source: file_embeddings (NOT Git!)
    # This tells AI "where things are" in the project
    # ============================================================
    try:
        tree_result = db.execute(text("""
            SELECT 
                fe.file_path, 
                fe.file_name, 
                fe.language, 
                fe.line_count,
                (SELECT COUNT(*) FROM file_dependencies fd 
                 WHERE fd.project_id = fe.project_id 
                 AND fd.source_file = fe.file_path) as import_count,
                (SELECT COUNT(*) FROM file_dependencies fd 
                 WHERE fd.project_id = fe.project_id 
                 AND fd.target_file = fe.file_path) as used_by_count
            FROM file_embeddings fe
            WHERE fe.project_id = :project_id
            ORDER BY fe.file_path
            LIMIT 200
        """), {"project_id": project_id}).fetchall()
        
        if tree_result:
            # Group by directory
            dirs = {}
            total_lines = 0
            languages = set()
            
            for row in tree_result:
                file_path, file_name, language, line_count, import_count, used_by_count = row
                file_parts = file_path.split("/")
                dir_path = "/".join(file_parts[:-1]) if len(file_parts) > 1 else "."
                
                if dir_path not in dirs:
                    dirs[dir_path] = []
                dirs[dir_path].append({
                    "name": file_name,
                    "lang": language or "?",
                    "lines": line_count or 0,
                    "imports": import_count or 0,
                    "used_by": used_by_count or 0
                })
                
                total_lines += line_count or 0
                if language:
                    languages.add(language)
            
            # Build compact tree
            tree_lines = []
            
            # Header with stats
            tree_lines.append(f"📊 {len(tree_result)} files | {total_lines:,} lines | {', '.join(sorted(languages)[:5])}")
            tree_lines.append("")
            
            lines_used = 2
            max_lines = 60
            dirs_shown = 0
            
            for dir_path in sorted(dirs.keys()):
                if lines_used >= max_lines:
                    remaining = len(dirs) - dirs_shown
                    if remaining > 0:
                        tree_lines.append(f"... and {remaining} more directories")
                    break
                
                # Directory header with file count
                dir_files = dirs[dir_path]
                tree_lines.append(f"📁 {dir_path}/ ({len(dir_files)} files)")
                lines_used += 1
                dirs_shown += 1
                
                # Sort files: most "used_by" first (core files)
                sorted_files = sorted(dir_files, key=lambda x: x["used_by"], reverse=True)
                
                for f in sorted_files[:8]:  # Max 8 files per dir
                    if lines_used >= max_lines:
                        break
                    
                    # Show used_by count for important files
                    used_by_indicator = f" ⭐{f['used_by']}" if f['used_by'] > 2 else ""
                    tree_lines.append(f"  ├── {f['name']} ({f['lang']}, {f['lines']}L){used_by_indicator}")
                    lines_used += 1
                
                if len(dir_files) > 8:
                    tree_lines.append(f"  └── ... +{len(dir_files) - 8} more")
                    lines_used += 1
            
            tree_text = "\n".join(tree_lines)
            parts.append(f"📌 PROJECT STRUCTURE (from database):\n{tree_text}")
            print(f"✅ [Smart Context] 1. Added project tree ({len(tree_result)} files, {dirs_shown} dirs)")
        else:
            print(f"ℹ️ [Smart Context] 1. No indexed files found")
            
    except Exception as e:
        print(f"⚠️ [Smart Context] 1. Project tree failed: {e}")
    
    # ============================================================
    # 2. SUMMARIES (MIDDLE - past decisions)
    # ============================================================
    try:
        summaries = memory.load_recent_summaries(
            project_id=str(project_id),
            role_id=role_id,
            limit=3
        )
        if summaries:
            summaries_text = "\n".join(summaries)
            parts.append(f"📌 PAST DECISIONS:\n{summaries_text}")
            print(f"✅ [Smart Context] 2. Added {len(summaries)} summaries")
    except Exception as e:
        print(f"⚠️ [Smart Context] 2. Summaries failed: {e}")
    
    # ============================================================
    # 3. RECENT MESSAGES (MIDDLE - conversation flow)
    # ============================================================
    try:
        recent_data = memory.retrieve_messages(
            project_id=str(project_id),
            role_id=role_id,
            limit=5,
            chat_session_id=session_id,
            for_display=False 
        )
        all_messages = recent_data.get("messages", [])
        recent_messages = all_messages[-5:] if len(all_messages) > 5 else all_messages
        recent_text = format_recent(recent_messages)
        parts.append(f"📌 RECENT CONVERSATION:\n{recent_text}")
        print(f"✅ [Smart Context] 3. Added {len(recent_messages)} recent messages")
    except Exception as e:
        print(f"⚠️ [Smart Context] 3. Recent messages failed: {e}")
    
    # ============================================================
    # 4. SEMANTIC CONTEXT (MIDDLE - related past discussions)
    # ============================================================
    try:
        relevant_context = vector_service.get_relevant_context(
            db=db,
            query=query,
            session_id=session_id,
            limit=3
        )
        if relevant_context:
            parts.append(f"📌 RELATED DISCUSSIONS:\n{relevant_context}")
            print(f"✅ [Smart Context] 4. Added semantic context from pgvector")
    except Exception as e:
        print(f"⚠️ [Smart Context] 4. Semantic search failed: {e}")
    
    # ============================================================
    # 5. RELEVANT CODE FILES (END - high attention!)
    # Uses: Semantic (pgvector) + FTS (tsvector) + Graph (dependencies)
    # This is the MOST IMPORTANT section - placed at END for high attention
    # ============================================================
    try:
        from app.services.hybrid_search_service import hybrid_search
        
        print(f"🔍 [Smart Context] 5. Hybrid search for project={project_id}...")

        relevant_files = hybrid_search(
            query=query,
            project_id=project_id,
            db=db,
            preset="code",  # Balanced: semantic=40%, fts=30%, graph=30%
            limit=15
        )

        if relevant_files:
            # Map combined_score to similarity for format function
            for f in relevant_files:
                f["similarity"] = f.get("combined_score", f.get("score", 0))
            
            files_text = format_relevant_files_with_content(
                files=relevant_files,
                db=db,
                project_id=project_id,
                max_content_chars=4000  # ~1000 tokens for code
            )
            
            # Show search sources in log
            sources_summary = {}
            for f in relevant_files[:5]:
                for src in f.get("sources", ["unknown"]):
                    sources_summary[src] = sources_summary.get(src, 0) + 1
            
            parts.append(f"📌 RELEVANT CODE (use these patterns!):\n{files_text}")
            print(f"✅ [Smart Context] 5. Added {len(relevant_files)} files via HYBRID search")
            print(f"   Sources: {sources_summary}")
        else:
            print(f"ℹ️ [Smart Context] 5. No relevant files found for query")
            
    except Exception as e:
        print(f"⚠️ [Smart Context] 5. Hybrid search failed: {e}")
        import traceback
        traceback.print_exc()
    
    # ============================================================
    # BUILD FINAL CONTEXT
    # ============================================================
    result = "\n\n".join(parts)
    
    print(f"""
✅ [Smart Context] Built context with {len(parts)} components:
   Order: Tree(START) → Summaries → Messages → Semantic → Code(END)
   Total chars: {len(result)}
   Estimated tokens: ~{len(result) // 4}
""")
    
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
        loop = asyncio.get_event_loop()
        if loop.is_running():
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
        return asyncio.run(
            build_smart_context(project_id, role_id, query, session_id, db, memory)
        )