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
import json

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
    response_type: str = "chat"  
    original_content: Optional[str] = None  
    new_content: Optional[str] = None  
    diff: Optional[str] = None  
    file_path: Optional[str] = None  
    tokens_used: Optional[Dict[str, int]] = None  


async def classify_user_intent(
    message: str,
    has_file_open: bool,
    user_api_key: str
) -> str:
    """
    Classify user intent using GPT-4o-mini.
    
    Returns: "EDIT", "CREATE", or "CHAT"
    Cost: ~$0.0001 (very cheap!)
    """
    
    prompt = f"""Classify this user message into ONE category:

Message: "{message}"
File is currently open: {has_file_open}

Categories:
- EDIT: User wants to modify/change/fix/refactor/add to existing code in the open file
  Examples: "add error handling", "fix this bug", "refactor to async", "optimize this"
  
- CREATE: User wants to create/build/make a new file/component/class
  Examples: "create a UserService", "make a login component", "build an API client"
  
- CHAT: User wants explanation/discussion/help/information
  Examples: "explain this code", "what does this do", "why use async", "how does this work"

Rules:
- If file is open AND message asks to change it → EDIT
- If message asks to create something new → CREATE  
- Otherwise → CHAT

Respond with ONLY one word: EDIT, CREATE, or CHAT"""

    try:
        classification = ask_model(
            messages=[{"role": "user", "content": prompt}],
            model_key="gpt-4o-mini",
            temperature=0.1,
            max_tokens=10,
            api_key=user_api_key
        )
        
        result = classification.strip().upper()
        
        # Validate result
        if result in ["EDIT", "CREATE", "CHAT"]:
            print(f"🎯 [Intent] '{message[:50]}...' → {result}")
            return result
        else:
            print(f"⚠️ [Intent] Invalid classification '{result}', defaulting to CHAT")
            return "CHAT"
            
    except Exception as e:
        print(f"⚠️ [Intent] Classification failed: {e}, defaulting to CHAT")
        return "CHAT"

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

        # ========== CLASSIFY USER INTENT ==========
        has_file_open = bool(request.filePath and request.fileContent)
        
        intent = await classify_user_intent(
            message=request.message,
            has_file_open=has_file_open,
            user_api_key=user_api_key
        )
        
        # ========== ROUTE TO EDIT MODE ==========
        if intent == "EDIT" and has_file_open and project_id:
            print(f"🎯 [Intent] EDIT mode activated!")
            
            # Call edit-file endpoint logic
            try:
                edit_request = EditFileRequest(
                    project_id=project_id,
                    file_path=request.filePath,
                    instruction=request.message,
                    current_content=request.fileContent
                )
                
                edit_response = await edit_file_with_ai(edit_request, current_user, db)
                
                # Store in memory for history
                if project_id:
                    try:
                        user_entry = memory.store_chat_message(
                            project_id_str, role_id, chat_session_id,
                            "user", request.message
                        )
                        store_message_with_embedding(db, user_entry.id, request.message)
                    except Exception as e:
                        print(f"⚠️ [Memory] Store failed: {e}")
                    
                    # Store AI response
                    try:
                        ai_msg = f"I've edited the file '{request.filePath}'. Please review the changes."
                        ai_entry = memory.store_chat_message(
                            project_id_str, role_id, chat_session_id,
                            "assistant", ai_msg
                        )
                        store_message_with_embedding(db, ai_entry.id, ai_msg)
                    except Exception as e:
                        print(f"⚠️ [Memory] AI store failed: {e}")
                
                # Return edit response
                return VSCodeChatResponse(
                    message=f"I've edited the file. Please review the changes in the diff view.",
                    chat_session_id=chat_session_id,
                    response_type="edit",
                    original_content=edit_response.original_content,
                    new_content=edit_response.new_content,
                    diff=edit_response.diff,
                    file_path=request.filePath,
                    tokens_used=edit_response.tokens_used
                )
                
            except Exception as e:
                print(f"❌ [EDIT mode] Failed: {e}")
                # Fall through to normal chat mode
                intent = "CHAT"
        
        # ========== ROUTE TO CREATE MODE ==========
        elif intent == "CREATE" and project_id:
            print(f"🎯 [Intent] CREATE mode activated!")
            
            # Call create-file endpoint logic
            try:
                create_request = CreateFileRequest(
                    project_id=project_id,
                    instruction=request.message,
                    file_path=None,  # Let AI suggest
                    current_content=None
                )
                
                create_response = await create_file_with_ai(create_request, current_user, db)
                
                # Store in memory
                if project_id:
                    try:
                        user_entry = memory.store_chat_message(
                            project_id_str, role_id, chat_session_id,
                            "user", request.message
                        )
                        store_message_with_embedding(db, user_entry.id, request.message)
                    except Exception as e:
                        print(f"⚠️ [Memory] Store failed: {e}")
                    
                    try:
                        ai_msg = f"I've created the file '{create_response.file_path}'. Please review the content."
                        ai_entry = memory.store_chat_message(
                            project_id_str, role_id, chat_session_id,
                            "assistant", ai_msg
                        )
                        store_message_with_embedding(db, ai_entry.id, ai_msg)
                    except Exception as e:
                        print(f"⚠️ [Memory] AI store failed: {e}")
                
                # Return create response
                return VSCodeChatResponse(
                    message=f"I've created a new file: {create_response.file_path}. Please review the content.",
                    chat_session_id=chat_session_id,
                    response_type="create",
                    new_content=create_response.content,
                    file_path=create_response.file_path,
                    tokens_used={"total": create_response.tokens_used}
                )
                
            except Exception as e:
                print(f"❌ [CREATE mode] Failed: {e}")
                # Fall through to normal chat mode
                intent = "CHAT"
        
        # ========== CHAT MODE (existing code continues) ==========
        print(f"💬 [Intent] CHAT mode (explanation/discussion)")
        
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
            chat_session_id=chat_session_id,
            response_type="chat"
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
    current_content: Optional[str] = None  


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
    file_path: Optional[str] = None  
    current_content: Optional[str] = None  

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
    max_tokens: int = 8192
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

def get_file_language(file_path: str) -> Optional[str]:
    """Get language from file extension"""
    extensions = {
        ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript",
        ".py": "python",
        ".html": "html", ".css": "css",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml",
        ".md": "markdown"
    }
    for ext, lang in extensions.items():
        if file_path.endswith(ext):
            return lang
    return None


async def collect_editing_context_from_vscode(
    project_id: int,
    file_path: str,
    current_content: str,
    instruction: str,
    db: Session,
    user_api_key: str
) -> Dict[str, Any]:
    """
    STEP 1 of Two-Step Editing: Collect context with GPT-4o-mini.
    
    Uses:
    - Current file content from VS Code (source of truth!)
    - Semantic search to find related files
    - GPT-4o-mini to analyze what context is needed
    
    Returns:
    {
        "current_file_content": str,  # From VS Code
        "related_files": dict,        # From database
        "analysis": dict,             # GPT-4o-mini analysis
        "tokens_used": int
    }
    """
    try:
        print(f"📋 [Step 1] Collecting context with GPT-4o-mini...")
        
        # 1. Use semantic search to find RELATED FILES
        from app.services.file_indexer import FileIndexer
        indexer = FileIndexer(db)
        
        related_files_search = await indexer.search_files(
            project_id=project_id,
            query=instruction,
            limit=10
        )
        
        print(f"🔍 Found {len(related_files_search)} related files via semantic search")
        
        # 2. Build analysis prompt for GPT-4o-mini
        available_files = [f['file_path'] for f in related_files_search]
        
        prompt = f"""Analyze this code editing task and determine what context is needed.

FILE: {file_path}

CURRENT CONTENT (first 4000 chars):
```
{current_content[:4000]}
```

INSTRUCTION: {instruction}

AVAILABLE RELATED FILES:
{json.dumps(available_files, indent=2)}

Analyze and return JSON only:
{{
  "related_files_needed": ["file1.ts", "file2.ts"],
  "reason": "Brief explanation"
}}

Return ONLY JSON, no markdown."""

        # 3. Call GPT-4o-mini (cheap analysis!)
        analysis_response = ask_model(
            messages=[{"role": "user", "content": prompt}],
            model_key="gpt-4o-mini",
            temperature=0.2,
            max_tokens=500,
            api_key=user_api_key
        )
        
        # 4. Parse analysis
        try:
            # Remove markdown if present
            clean_response = analysis_response.strip()
            if clean_response.startswith("```"):
                clean_response = clean_response.split("```")[1]
                if clean_response.startswith("json"):
                    clean_response = clean_response[4:]
            
            analysis_data = json.loads(clean_response)
        except Exception as e:
            print(f"⚠️ [Step 1] Failed to parse analysis, using fallback: {e}")
            analysis_data = {
                "related_files_needed": available_files[:3],
                "reason": "Using top semantic matches (parsing failed)"
            }
        
        # 5. Load ONLY needed files from database
        context_files = {}
        
        for needed_file in analysis_data.get("related_files_needed", [])[:5]:
            try:
                result = db.execute(
                    text("""
                        SELECT content FROM file_embeddings
                        WHERE project_id = :project_id AND file_path = :file_path
                    """),
                    {"project_id": project_id, "file_path": needed_file}
                ).fetchone()
                
                if result and result[0]:
                    context_files[needed_file] = result[0]
                    print(f"  ✅ Loaded: {needed_file}")
            except Exception as e:
                print(f"  ⚠️ Failed to load {needed_file}: {e}")
        
        print(f"✅ [Step 1] Context collected: {len(context_files)} files loaded")
        
        return {
            "current_file_content": current_content,
            "related_files": context_files,
            "analysis": analysis_data,
            "tokens_used": 300  # Approximate for GPT-4o-mini
        }
        
    except Exception as e:
        print(f"❌ [Step 1] Context collection failed: {e}")
        import traceback
        traceback.print_exc()
        
        # Fallback: return just current content
        return {
            "current_file_content": current_content,
            "related_files": {},
            "analysis": {"reason": f"Context collection failed: {str(e)}"},
            "tokens_used": 0
        }


# ========== EDIT FILE ENDPOINT ==========

@router.post("/edit-file", response_model=EditFileResponse)
async def edit_file_with_ai(
    request: EditFileRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Edit file with AI assistance using TWO-STEP approach:
    1. GPT-4o-mini collects context (~$0.0001)
    2. Claude Sonnet 4.5 edits code (~$0.015)
    
    Total cost: ~$0.015 per edit (50-100x cheaper than Cline!)
    """
    try:
        print(f"\n✏️ [Edit File] project={request.project_id}, file={request.file_path}")
        
        # Get user's API keys
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Validate project
        project = db.get(Project, request.project_id)
        if not project:
            raise HTTPException(404, f"Project {request.project_id} not found")
        
        # ========== GET CURRENT FILE CONTENT ==========
        # Priority 1: From VS Code (request.current_content)
        # Priority 2: From database (file_embeddings)
        
        if request.current_content:
            original_content = request.current_content
            print("📄 Using content from VS Code (source of truth!)")
            
            # Try to get language from database if file exists
            lang_result = db.execute(
                text("""
                    SELECT language FROM file_embeddings
                    WHERE project_id = :project_id AND file_path = :file_path
                """),
                {"project_id": request.project_id, "file_path": request.file_path}
            ).fetchone()
            
            language = lang_result[0] if lang_result else get_file_language(request.file_path)
            
        else:
            # Fallback: Read from database
            file_result = db.execute(
                text("""
                    SELECT content, language
                    FROM file_embeddings
                    WHERE project_id = :project_id AND file_path = :file_path
                """),
                {"project_id": request.project_id, "file_path": request.file_path}
            ).fetchone()
            
            if not file_result or not file_result[0]:
                raise HTTPException(
                    404, 
                    f"File '{request.file_path}' not found in database. Please provide current_content or index the project."
                )
            
            original_content = file_result[0]
            language = file_result[1] or get_file_language(request.file_path)
            print("📄 Using content from database (indexed)")
        
        # ========== STEP 1: Collect Context with GPT-4o-mini ==========
        print(f"🚀 [DEBUG] About to call collect_editing_context_from_vscode...")
        print(f"   project_id={request.project_id}")
        print(f"   file_path={request.file_path}")
        print(f"   instruction={request.instruction[:50]}...")
        print(f"   content_length={len(original_content)}")

        try:
            context_data = await collect_editing_context_from_vscode(
                project_id=request.project_id,
                file_path=request.file_path,
                current_content=original_content,
                instruction=request.instruction,
                db=db,
                user_api_key=user_api_key
            )
            print(f"✅ [DEBUG] collect_editing_context_from_vscode returned successfully")
            print(f"   tokens_used={context_data.get('tokens_used', 0)}")
            print(f"   related_files={len(context_data.get('related_files', {}))}")
        except Exception as e:
            print(f"❌ [DEBUG] collect_editing_context_from_vscode FAILED: {e}")
            import traceback
            traceback.print_exc()
            # Fallback
            context_data = {
                "current_file_content": original_content,
                "related_files": {},
                "analysis": {"reason": f"Failed: {str(e)}"},
                "tokens_used": 0
            }

        # ========== STEP 2: Build Prompt for Claude Sonnet 4.5 ==========
        print(f"🤖 [Step 2] Editing with Claude Sonnet 4.5...")
        
        prompt = f"""You are an expert code editor. Edit this file according to the instruction.

FILE: {request.file_path}
LANGUAGE: {language or 'unknown'}

CURRENT CONTENT:
```
{context_data['current_file_content']}
```

INSTRUCTION:
{request.instruction}
"""
        
        # Add related files context if available
        if context_data['related_files']:
            prompt += "\n\nRELATED FILES FOR CONTEXT:\n"
            for file_path, content in context_data['related_files'].items():
                file_lang = get_file_language(file_path) or ""
                prompt += f"\n{file_path}:\n```{file_lang}\n{content[:2000]}\n```\n"
        
        prompt += """
RULES:
1. Return ONLY the complete edited file content
2. Use correct types/imports from related files shown above
3. Maintain code style and conventions
4. Do NOT include markdown code blocks in output
5. Keep all unchanged parts exactly as they are

Generate the edited file:"""
        
        # ========== STEP 2: Call Claude Sonnet 4.5 ==========
        from app.utils.api_key_resolver import get_anthropic_key
        from app.providers.factory import ask_model
        
        anthropic_key = get_anthropic_key(current_user, db, required=False)
        
        if anthropic_key:
            print("🤖 Using Claude Sonnet 4.5 for editing")
            new_content = ask_model(
                messages=[{"role": "user", "content": prompt}],
                model_key="claude-sonnet-4.5",
                system_prompt="You are an expert code editor.",
                temperature=0.2,
                max_tokens=8192,
                api_key=anthropic_key
            )
        else:
            print("🤖 Using GPT-4o for editing (no Claude key)")
            new_content = await call_openai_for_editing(prompt, user_api_key, 8192)
        
        # ========== Clean Markdown ==========
        new_content = new_content.strip()
        
        # Remove markdown code blocks if present
        if "```" in new_content:
            parts = new_content.split("```")
            if len(parts) >= 3:
                code_block = parts[1]
                lines = code_block.split("\n")
                if lines and lines[0].strip() in ["typescript", "python", "javascript", "tsx", "jsx", "js", "ts", "py", language]:
                    lines = lines[1:]
                new_content = "\n".join(lines).strip()
            elif len(parts) == 2 and parts[0].strip() == "":
                code_block = parts[1]
                lines = code_block.split("\n")
                if lines and lines[0].strip() in ["typescript", "python", "javascript", "tsx", "jsx", "js", "ts", "py", language]:
                    lines = lines[1:]
                new_content = "\n".join(lines).strip()
        
        if new_content.endswith("```"):
            new_content = new_content[:-3].strip()
        
        # ========== Generate Diff ==========
        diff = generate_unified_diff(original_content, new_content, request.file_path)
        
        # ========== Calculate Tokens ==========
        tokens_used = {
            "step1_gpt4o_mini": context_data['tokens_used'],
            "step2_prompt": int(len(prompt.split()) * 1.3),
            "step2_response": int(len(new_content.split()) * 1.3),
            "total": context_data['tokens_used'] + (len(prompt) + len(new_content)) // 4
        }
        
        print(f"✅ [Edit File] Complete! Tokens: Step1={tokens_used['step1_gpt4o_mini']}, Step2={tokens_used['step2_prompt'] + tokens_used['step2_response']}")
        
        return EditFileResponse(
            success=True,
            original_content=original_content,
            new_content=new_content,
            diff=diff,
            tokens_used=tokens_used,
            message=f"File edited using {'Claude Sonnet 4.5' if anthropic_key else 'GPT-4o'}"
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
    Create new file with AI assistance using TWO-STEP approach:
    1. GPT-4o-mini analyzes task and finds related files (~$0.0001)
    2. Claude Sonnet 4.5 generates code (~$0.015)
    
    Total cost: ~$0.015 per file
    """
    try:
        print(f"\n📝 [Create File] project={request.project_id}")
        
        # Get user's API keys
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Validate project
        project = db.get(Project, request.project_id)
        if not project:
            raise HTTPException(404, f"Project {request.project_id} not found")
        
        # ========== STEP 1: Collect Context with GPT-4o-mini ==========
        # Use empty content for new file creation
        base_content = request.current_content or ""
        
        context_data = await collect_editing_context_from_vscode(
            project_id=request.project_id,
            file_path=request.file_path or "new-file",
            current_content=base_content,
            instruction=request.instruction,
            db=db,
            user_api_key=user_api_key
        )
        
        # ========== STEP 2: Build Prompt for Claude Sonnet 4.5 ==========
        print(f"🤖 [Step 2] Creating file with Claude Sonnet 4.5...")
        
        file_path_text = f"Create file: {request.file_path}" if request.file_path else "Suggest appropriate filename and create file"
        
        prompt = f"""You are an expert code generator. Create a new file according to the instruction.

{file_path_text}

INSTRUCTION:
{request.instruction}
"""
        
        # Add base content if provided
        if base_content:
            prompt += f"""
BASE CONTENT (to extend):
```
{base_content}
```
"""
        
        # Add related files context
        if context_data['related_files']:
            prompt += "\n\nRELATED FILES FOR CONTEXT:\n"
            for file_path, content in context_data['related_files'].items():
                file_lang = get_file_language(file_path) or ""
                prompt += f"\n{file_path}:\n```{file_lang}\n{content[:2000]}\n```\n"
        
        prompt += """
RULES:
1. Return ONLY the file content
2. Use imports and patterns from related files shown above
3. Follow project's code style and conventions
4. Do NOT include markdown code blocks in output
5. Production-ready, well-commented code

Generate the file content:"""
        
        # ========== STEP 2: Call Claude Sonnet 4.5 ==========
        from app.utils.api_key_resolver import get_anthropic_key
        from app.providers.factory import ask_model
        
        anthropic_key = get_anthropic_key(current_user, db, required=False)
        
        if anthropic_key:
            print("🤖 Using Claude Sonnet 4.5 for file creation")
            content = ask_model(
                messages=[{"role": "user", "content": prompt}],
                model_key="claude-sonnet-4.5",
                system_prompt="You are an expert code generator.",
                temperature=0.2,
                max_tokens=8192,
                api_key=anthropic_key
            )
        else:
            print("🤖 Using GPT-4o for file creation (no Claude key)")
            content = await call_openai_for_editing(prompt, user_api_key, 8192)
        
        # ========== Clean Markdown ==========
        content = content.strip()
        
        # Remove markdown code blocks if present
        if "```" in content:
            parts = content.split("```")
            if len(parts) >= 3:
                code_block = parts[1]
                lines = code_block.split("\n")
                if lines and lines[0].strip() in ["typescript", "python", "javascript", "tsx", "jsx", "js", "ts", "py"]:
                    lines = lines[1:]
                content = "\n".join(lines).strip()
            elif len(parts) == 2 and parts[0].strip() == "":
                code_block = parts[1]
                lines = code_block.split("\n")
                if lines and lines[0].strip() in ["typescript", "python", "javascript", "tsx", "jsx", "js", "ts", "py"]:
                    lines = lines[1:]
                content = "\n".join(lines).strip()
        
        if content.endswith("```"):
            content = content[:-3].strip()
        
        # Remove "FILE PATH:" prefix if AI added it
        if content.startswith("FILE PATH:"):
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if not line.strip().startswith("FILE PATH:") and line.strip():
                    content = "\n".join(lines[i:]).strip()
                    break
        
        # ========== Suggest Filename if Needed ==========
        final_file_path = request.file_path
        
        if not final_file_path:
            print("💡 Suggesting filename...")
            suggestion_prompt = f"Based on this instruction: '{request.instruction}', suggest an appropriate filename. Return ONLY the filename (e.g., 'UserService.ts')."
            
            if anthropic_key:
                suggested = ask_model(
                    messages=[{"role": "user", "content": suggestion_prompt}],
                    model_key="gpt-4o-mini",  # Use mini for filename suggestion
                    temperature=0.2,
                    max_tokens=50,
                    api_key=user_api_key
                )
            else:
                suggested = await call_openai_for_editing(suggestion_prompt, user_api_key, 50)
            
            final_file_path = suggested.strip().strip('"').strip("'")
            print(f"💡 Suggested filename: {final_file_path}")
        
        # ========== Extract Related Files List ==========
        related_files_list = list(context_data['related_files'].keys())
        
        # ========== Calculate Tokens ==========
        tokens_used = context_data['tokens_used'] + (len(prompt) + len(content)) // 4
        
        print(f"✅ [Create File] Complete! File: {final_file_path}, Tokens: {tokens_used}")
        
        return CreateFileResponse(
            success=True,
            file_path=final_file_path,
            content=content,
            related_files=related_files_list,
            tokens_used=tokens_used,
            message=f"File created using {'Claude Sonnet 4.5' if anthropic_key else 'GPT-4o'}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [Create File] Error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to create file: {str(e)}")