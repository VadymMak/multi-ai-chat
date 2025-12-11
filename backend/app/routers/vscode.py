"""
VS Code Extension API endpoints.
Full Smart Context using EXISTING services:
- build_smart_context() from smart_context.py
- MemoryManager from manager.py
- store_message_with_embedding() from vector_service.py

ADDED: Diagnostic endpoint for debugging search_files() issue
"""
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text  # ← FIXED: Removed print() that got merged here
from pydantic import BaseModel
from uuid import uuid4
import openai

from app.deps import get_current_active_user, get_db
from app.memory.models import User, Role, Project
from app.memory.manager import MemoryManager
from app.providers.factory import ask_model
from app.utils.api_key_resolver import get_openai_key
from app.services.smart_context import build_smart_context
from app.services.vector_service import store_message_with_embedding

router = APIRouter(prefix="/vscode", tags=["vscode"])


# Request/Response Models
class VSCodeChatRequest(BaseModel):
    message: str
    project_id: Optional[int] = None
    role_id: Optional[int] = None
    chat_session_id: Optional[str] = None
    filePath: Optional[str] = None
    fileContent: Optional[str] = None
    selectedText: Optional[str] = None


class VSCodeChatResponse(BaseModel):
    message: str
    chat_session_id: Optional[str] = None


@router.post("/chat", response_model=VSCodeChatResponse)
async def vscode_chat(
    request: VSCodeChatRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    VS Code Extension chat with FULL Smart Context.
    
    Now uses:
    - build_smart_context() for pgvector search + recent + summaries + files
    - MemoryManager for conversation storage
    - store_message_with_embedding() for future semantic search
    """
    
    try:
        # Get user's OpenAI API key
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Initialize MemoryManager
        memory = MemoryManager(db)
        
        # ========== VALIDATE PROJECT & ROLE ==========
        project_id = request.project_id
        role_id = request.role_id or 1  # Default role
        
        if project_id:
            project = db.get(Project, project_id)
            if not project:
                print(f"⚠️ [VSCode] Project {project_id} not found")
                project_id = None
        
        # Validate role
        role = db.get(Role, role_id)
        if not role:
            role_id = 1
        
        project_id_str = str(project_id) if project_id else "0"
        
        # ========== GET/CREATE CHAT SESSION ==========
        if request.chat_session_id:
            chat_session_id = request.chat_session_id.strip()
        elif project_id:
            chat_session_id = memory.get_or_create_chat_session_id(role_id, project_id_str)
        else:
            chat_session_id = str(uuid4())
        
        print(f"\n🔌 [VSCode] /chat project={project_id} role={role_id} session={chat_session_id[:8]}...")
        print(f"📥 User: {request.message[:100]}...")
        
        # ========== STORE USER MESSAGE + EMBEDDING ==========
        if project_id:
            try:
                user_entry = memory.store_chat_message(
                    project_id_str, role_id, chat_session_id,
                    "user", request.message
                )
                # Store embedding for future semantic search
                try:
                    store_message_with_embedding(db, user_entry.id, request.message)
                    print(f"✅ [Memory] User message stored with embedding")
                except Exception as e:
                    print(f"⚠️ [Memory] Embedding skipped: {e}")
            except Exception as e:
                print(f"⚠️ [Memory] Store failed: {e}")
        
        # ========== BUILD SMART CONTEXT (EXISTING FUNCTION!) ==========
        system_prompt = "You are a helpful coding assistant for VS Code Extension users."
        
        if project_id:
            try:
                print(f"🎯 [Smart Context] Calling build_smart_context()...")
                smart_context = await build_smart_context(
                    project_id=project_id,
                    role_id=role_id,
                    query=request.message,
                    session_id=chat_session_id,
                    db=db,
                    memory=memory
                )
                if smart_context:
                    system_prompt += f"\n\n{smart_context}"
                    print(f"✅ [Smart Context] Added context (~{len(smart_context)} chars)")
            except Exception as e:
                print(f"⚠️ [Smart Context] Failed: {e}")
                import traceback
                traceback.print_exc()
        
        # ========== ADD CURRENT FILE CONTEXT (keep existing) ==========
        if request.filePath:
            system_prompt += f"\n\n📁 Current file: {request.filePath}"
        
        if request.selectedText:
            system_prompt += f"\n\n✂️ Selected code:\n```\n{request.selectedText}\n```"
            system_prompt += "\n\nFocus on explaining/improving the selected code above."
        elif request.fileContent:
            content_preview = request.fileContent[:5000]
            if len(request.fileContent) > 5000:
                content_preview += "\n... (truncated)"
            system_prompt += f"\n\n📄 File content:\n```\n{content_preview}\n```"
        
        # ========== CALL AI MODEL ==========
        messages = [{"role": "user", "content": request.message}]
        
        ai_response = ask_model(
            messages=messages,
            model_key="gpt-4o-mini",
            system_prompt=system_prompt,
            api_key=user_api_key
        )
        
        print(f"📤 AI: {ai_response[:100]}...")
        
        # ========== STORE AI RESPONSE + EMBEDDING ==========
        if project_id:
            try:
                ai_entry = memory.store_chat_message(
                    project_id_str, role_id, chat_session_id,
                    "assistant", ai_response
                )
                # Store embedding for AI response too
                try:
                    store_message_with_embedding(db, ai_entry.id, ai_response)
                    print(f"✅ [Memory] AI response stored with embedding")
                except Exception as e:
                    print(f"⚠️ [Memory] AI embedding skipped: {e}")
            except Exception as e:
                print(f"⚠️ [Memory] AI store failed: {e}")
        
        return VSCodeChatResponse(
            message=ai_response,
            chat_session_id=chat_session_id
        )
        
    except Exception as e:
        print(f"❌ Error in /vscode/chat: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error: {str(e)}"
        )


# ========== DIAGNOSTIC ENDPOINT ==========
@router.get("/debug-search/{project_id}")
async def debug_search(
    project_id: int,
    query: str = Query(..., description="Search query to test"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    🔍 DIAGNOSTIC ENDPOINT
    
    Helps debug why search_files() returns wrong results.
    
    Tests:
    1. How many files in project
    2. How many have embeddings
    3. Query embedding creation
    4. Actual search results vs expected
    5. Raw distance values
    
    Example:
        GET /api/vscode/debug-search/18?query=FileIndexer
    """
    
    try:
        # Get user's OpenAI API key for embedding creation
        user_api_key = get_openai_key(current_user, db, required=True)
        
        print(f"\n🔍 [DEBUG] Starting diagnostic for project={project_id}, query='{query}'")
        
        # ========== 1. PROJECT INFO ==========
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        
        project_info = {
            "project_id": project_id,
            "project_name": project.name,
            "has_git_url": bool(project.git_url),
            "git_url": project.git_url
        }
        
        # ========== 2. FILE COUNTS ==========
        total_files_result = db.execute(
            text("SELECT COUNT(*) as count FROM file_embeddings WHERE project_id = :pid"),
            {"pid": project_id}
        ).fetchone()
        total_files = total_files_result[0] if total_files_result else 0
        
        files_with_embeddings_result = db.execute(
            text("SELECT COUNT(*) as count FROM file_embeddings WHERE project_id = :pid AND embedding IS NOT NULL"),
            {"pid": project_id}
        ).fetchone()
        files_with_embeddings = files_with_embeddings_result[0] if files_with_embeddings_result else 0
        
        # ========== 3. CREATE QUERY EMBEDDING ==========
        print(f"🔮 [DEBUG] Creating embedding for query: '{query}'")
        
        # Use EXACT pattern from vector_service.py (which works!)
        import httpx
        
        http_client = httpx.Client(
            timeout=httpx.Timeout(60.0, connect=10.0),
            trust_env=False  # Don't read proxy from environment
        )
        
        from openai import OpenAI
        client = OpenAI(api_key=user_api_key, http_client=http_client)
        
        try:
            embedding_response = client.embeddings.create(
                input=query,
                model="text-embedding-3-small"
            )
            query_embedding = embedding_response.data[0].embedding
        finally:
            http_client.close()
        
        query_embedding_info = {
            "query": query,
            "embedding_length": len(query_embedding),
            "embedding_sample": query_embedding[:5],  # First 5 dimensions
            "model": "text-embedding-3-small"
        }
        
        # ========== 4. TEST SEARCH WITH QUERY EMBEDDING ==========
        print(f"🔎 [DEBUG] Testing search with query embedding...")
        
        # SQL search (use CAST syntax like vector_service.py)
        search_sql = text("""
            SELECT 
                file_path,
                language,
                1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
            FROM file_embeddings
            WHERE project_id = :project_id
                AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:query_embedding AS vector)
            LIMIT 5
        """)
        
        search_results = db.execute(
            search_sql,
            {
                "project_id": project_id,
                "query_embedding": query_embedding  # Pass list directly!
            }
        ).fetchall()
        
        search_results_list = [
            {
                "file_path": row[0],
                "language": row[1],
                "similarity": float(row[2])
            }
            for row in search_results
        ]
        
        # ========== 5. TEST FILE-TO-FILE COMPARISON ==========
        print(f"📊 [DEBUG] Testing file-to-file comparison...")
        
        # Find a file that should match (e.g., contains query term in path)
        target_file_result = db.execute(
            text("""
                SELECT file_path, embedding
                FROM file_embeddings
                WHERE project_id = :pid 
                    AND file_path ILIKE :pattern
                    AND embedding IS NOT NULL
                LIMIT 1
            """),
            {"pid": project_id, "pattern": f"%{query}%"}
        ).fetchone()
        
        file_to_file_comparison = None
        if target_file_result:
            target_file_path = target_file_result[0]
            target_embedding = target_file_result[1]
            
            # Compare this file's embedding to all others
            file_to_file_sql = text("""
                SELECT 
                    file_path,
                    language,
                    1 - (embedding <=> CAST(:target_embedding AS vector)) as similarity
                FROM file_embeddings
                WHERE project_id = :project_id
                    AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:target_embedding AS vector)
                LIMIT 5
            """)
            
            file_to_file_results = db.execute(
                file_to_file_sql,
                {
                    "project_id": project_id,
                    "target_embedding": target_embedding  # Pass list directly!
                }
            ).fetchall()
            
            file_to_file_comparison = {
                "target_file": target_file_path,
                "results": [
                    {
                        "file_path": row[0],
                        "language": row[1],
                        "similarity": float(row[2])
                    }
                    for row in file_to_file_results
                ]
            }
        
        # ========== 6. FIND SPECIFIC FILE IF EXISTS ==========
        specific_file_check = None
        if "file_indexer" in query.lower() or "FileIndexer" in query:
            specific_file_result = db.execute(
                text("""
                    SELECT 
                        file_path,
                        1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
                    FROM file_embeddings
                    WHERE project_id = :pid 
                        AND file_path ILIKE '%file_indexer%'
                        AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:query_embedding AS vector)
                    LIMIT 3
                """),
                {"pid": project_id, "query_embedding": query_embedding}  # Pass list directly!
            ).fetchall()
            
            specific_file_check = [
                {
                    "file_path": row[0],
                    "similarity": float(row[1])
                }
                for row in specific_file_result
            ]
        
        # ========== 7. RETURN COMPREHENSIVE REPORT ==========
        report = {
            "project_info": project_info,
            "database_stats": {
                "total_files": total_files,
                "files_with_embeddings": files_with_embeddings,
                "embedding_coverage": f"{(files_with_embeddings/total_files*100):.1f}%" if total_files > 0 else "0%"
            },
            "query_embedding": query_embedding_info,
            "search_with_query_embedding": {
                "method": "Query text → Embedding → Search files",
                "results_count": len(search_results_list),
                "results": search_results_list
            },
            "file_to_file_comparison": file_to_file_comparison,
            "specific_file_check": specific_file_check,
            "analysis": {
                "issue": "If search_with_query_embedding shows low similarities, query embedding doesn't match file embeddings",
                "possible_causes": [
                    "Query text is too different from file content structure",
                    "File embeddings include metadata (classes, functions) that query doesn't",
                    "Need to preprocess query to match file content format"
                ],
                "recommendations": [
                    "If file-to-file similarity is high (>0.7) but query similarity is low (<0.3): Use hybrid search",
                    "If specific_file_check finds the file but similarity is low: Embedding mismatch confirmed",
                    "Consider adding filename matching for queries that look like paths"
                ]
            }
        }
        
        print(f"✅ [DEBUG] Diagnostic complete")
        return report
        
    except Exception as e:
        print(f"❌ [DEBUG] Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Diagnostic error: {str(e)}"
        )


# ========== QUICK FILE LOOKUP ==========
@router.get("/files/{project_id}")
async def list_indexed_files(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, description="Max files to return"),
    search: Optional[str] = Query(None, description="Filter by file path")
):
    """
    List indexed files in a project.
    Useful for verifying what's in the database.
    
    Example:
        GET /api/vscode/files/18?search=file_indexer
    """
    
    try:
        if search:
            query = text("""
                SELECT file_path, language, 
                       CASE WHEN embedding IS NOT NULL THEN true ELSE false END as has_embedding
                FROM file_embeddings
                WHERE project_id = :pid 
                    AND file_path ILIKE :pattern
                ORDER BY file_path
                LIMIT :limit
            """)
            results = db.execute(
                query,
                {"pid": project_id, "pattern": f"%{search}%", "limit": limit}
            ).fetchall()
        else:
            query = text("""
                SELECT file_path, language,
                       CASE WHEN embedding IS NOT NULL THEN true ELSE false END as has_embedding
                FROM file_embeddings
                WHERE project_id = :pid
                ORDER BY file_path
                LIMIT :limit
            """)
            results = db.execute(
                query,
                {"pid": project_id, "limit": limit}
            ).fetchall()
        
        files = [
            {
                "file_path": row[0],
                "language": row[1],
                "has_embedding": row[2]
            }
            for row in results
        ]
        
        return {
            "project_id": project_id,
            "search": search,
            "count": len(files),
            "files": files
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error: {str(e)}"
        )
    
# ========================================================================
# 🚀 SMART CLINE ENDPOINTS - Day 1 Implementation
# Edit and create files with AI + Smart Context
# ========================================================================

import difflib


# ========== REQUEST/RESPONSE MODELS ==========

class EditFileRequest(BaseModel):
    """Request to edit a file with AI assistance"""
    project_id: int
    file_path: str
    instruction: str


class EditFileResponse(BaseModel):
    """Response with original, new content, and diff"""
    success: bool
    original_content: str
    new_content: str
    diff: str
    tokens_used: Dict[str, int]
    message: Optional[str] = None


class CreateFileRequest(BaseModel):
    """Request to create a new file with AI assistance"""
    project_id: int
    instruction: str
    file_path: Optional[str] = None  # If None, AI suggests filename


class CreateFileResponse(BaseModel):
    """Response with new file content"""
    success: bool
    file_path: str
    content: str
    related_files: List[str]
    tokens_used: int
    message: Optional[str] = None


# ========== HELPER FUNCTIONS ==========

def generate_unified_diff(
    original: str,
    modified: str,
    filename: str
) -> str:
    """
    Generate unified diff format for preview.
    Returns diff string that VS Code can display.
    """
    try:
        original_lines = original.splitlines(keepends=True)
        modified_lines = modified.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm=""
        )
        
        return "".join(diff)
    except Exception as e:
        print(f"⚠️ [Diff] Error generating diff: {e}")
        return f"Error generating diff: {str(e)}"


async def call_openai_for_editing(
    prompt: str,
    api_key: str,
    max_tokens: int = 3000
) -> str:
    """
    Call OpenAI GPT-4o for code editing/generation.
    Returns AI response as string.
    """
    try:
        import httpx
        from openai import OpenAI
        
        # Use same pattern as in vector_service.py
        http_client = httpx.Client(
            timeout=httpx.Timeout(60.0, connect=10.0),
            trust_env=False
        )
        
        client = OpenAI(api_key=api_key, http_client=http_client)
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert code editor and generator."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,
                max_tokens=max_tokens
            )
            
            return response.choices[0].message.content
            
        finally:
            http_client.close()
            
    except Exception as e:
        print(f"❌ [OpenAI] Error: {e}")
        raise


# ========== EDIT FILE ENDPOINT ==========

@router.post("/edit-file", response_model=EditFileResponse)
async def edit_file_with_ai(
    request: EditFileRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Edit file with AI assistance using Smart Context.
    """
    try:
        print(f"\n✏️ [Edit File] project={request.project_id}, file={request.file_path}")
        
        # Get user's OpenAI API key
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Validate project
        project = db.get(Project, request.project_id)
        if not project:
            raise HTTPException(404, f"Project {request.project_id} not found")
        
        # Read current file content
        file_result = db.execute(
            text("""
                SELECT content, language
                FROM file_embeddings
                WHERE project_id = :project_id AND file_path = :file_path
            """),
            {"project_id": request.project_id, "file_path": request.file_path}
        ).fetchone()
        
        if not file_result or not file_result[0]:
            raise HTTPException(404, f"File '{request.file_path}' not found")
        
        original_content = file_result[0]
        language = file_result[1] or "text"
        
        # Build Smart Context
        memory = MemoryManager(db)
        chat_session_id = str(uuid4())
        
        smart_context = await build_smart_context(
            project_id=request.project_id,
            role_id=1,
            query=request.instruction,
            session_id=chat_session_id,
            db=db,
            memory=memory
        )
        
        # Build AI prompt
        prompt = f"""Edit this file according to the instruction.

FILE: {request.file_path}
LANGUAGE: {language}

CURRENT CONTENT:
{original_content}

INSTRUCTION:
{request.instruction}

PROJECT CONTEXT:
{smart_context}

RULES:
1. Return ONLY the complete modified file content
2. No markdown code blocks
3. No explanations
4. Maintain imports and style from project context

Generate the edited file:"""

        # Call AI
        new_content = await call_openai_for_editing(prompt, user_api_key, 3000)
        
        # Clean markdown if present
        new_content = new_content.strip()
        if new_content.startswith("```"):
            lines = new_content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            new_content = "\n".join(lines)
        
        # Generate diff
        diff = generate_unified_diff(original_content, new_content, request.file_path)
        
        # Calculate tokens
        tokens_used = {
            "context": len(smart_context.split()) * 1.3,
            "prompt": len(prompt.split()) * 1.3,
            "response": len(new_content.split()) * 1.3,
            "total": (len(prompt) + len(new_content)) // 4
        }
        
        return EditFileResponse(
            success=True,
            original_content=original_content,
            new_content=new_content,
            diff=diff,
            tokens_used=tokens_used,
            message="File edited successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Edit File] Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to edit file: {str(e)}")


# ========== CREATE FILE ENDPOINT ==========

@router.post("/create-file", response_model=CreateFileResponse)
async def create_file_with_ai(
    request: CreateFileRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Create new file with AI assistance using Smart Context.
    """
    try:
        print(f"\n📝 [Create File] project={request.project_id}")
        
        # Get user's OpenAI API key
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Validate project
        project = db.get(Project, request.project_id)
        if not project:
            raise HTTPException(404, f"Project {request.project_id} not found")
        
        # Build Smart Context
        memory = MemoryManager(db)
        chat_session_id = str(uuid4())
        
        smart_context = await build_smart_context(
            project_id=request.project_id,
            role_id=1,
            query=request.instruction,
            session_id=chat_session_id,
            db=db,
            memory=memory
        )
        
        # Extract related files
        related_files = []
        try:
            import re
            file_pattern = r'📄 \*\*([^\*]+)\*\*'
            matches = re.findall(file_pattern, smart_context)
            related_files = matches[:5]
        except:
            pass
        
        # Build AI prompt
        file_path_text = f"Create file: {request.file_path}" if request.file_path else "Suggest filename and create"
        
        prompt = f"""Create a new file according to the instruction.

INSTRUCTION:
{request.instruction}

FILE PATH: {file_path_text}

PROJECT CONTEXT:
{smart_context}

RULES:
1. Return ONLY the file content
2. Use imports and patterns from similar files
3. No markdown code blocks
4. No explanations
5. Production-ready code

Generate the file:"""

        # Call AI
        content = await call_openai_for_editing(prompt, user_api_key, 3000)
        
        # Clean markdown
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        
        # Suggest filename if needed
        final_file_path = request.file_path
        if not final_file_path:
            suggestion_prompt = f"Suggest filename for: {request.instruction}. Return ONLY filename."
            suggested = await call_openai_for_editing(suggestion_prompt, user_api_key, 50)
            final_file_path = suggested.strip().strip('"').strip("'")
        
        # Calculate tokens
        tokens_used = (len(prompt) + len(content)) // 4
        
        return CreateFileResponse(
            success=True,
            file_path=final_file_path,
            content=content,
            related_files=related_files,
            tokens_used=tokens_used,
            message="File created successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Create File] Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to create file: {str(e)}")