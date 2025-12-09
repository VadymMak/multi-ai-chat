"""
VS Code Extension API endpoints.
Full Smart Context using EXISTING services:
- build_smart_context() from smart_context.py
- MemoryManager from manager.py
- store_message_with_embedding() from vector_service.py
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from uuid import uuid4

from app.deps import get_current_active_user, get_db
from app.memory.models import User, Role, Project
from app.memory.manager import MemoryManager
from app.providers.factory import ask_model
from app.utils.api_key_resolver import get_openai_key
from app.services.smart_context import build_smart_context  # ← EXISTING!
from app.services.vector_service import store_message_with_embedding  # ← EXISTING!

router = APIRouter(prefix="/vscode", tags=["vscode"])


# Request/Response Models
class VSCodeChatRequest(BaseModel):
    message: str
    project_id: Optional[int] = None
    role_id: Optional[int] = None  # ← NEW: for MemoryManager
    chat_session_id: Optional[str] = None  # ← NEW: for session continuity
    filePath: Optional[str] = None
    fileContent: Optional[str] = None
    selectedText: Optional[str] = None


class VSCodeChatResponse(BaseModel):
    message: str
    chat_session_id: Optional[str] = None  # ← NEW: return for continuity


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