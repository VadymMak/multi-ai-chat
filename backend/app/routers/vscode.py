"""
VS Code Extension API endpoints.
Simple chat interface with Smart Context from pgvector.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.deps import get_current_active_user, get_db
from app.memory.models import User
from app.providers.factory import ask_model
from app.utils.api_key_resolver import get_openai_key
from app.services.file_indexer import FileIndexer  # ← ADD THIS

router = APIRouter(prefix="/vscode", tags=["vscode"])


# Request/Response Models
class VSCodeChatRequest(BaseModel):
    message: str
    project_id: Optional[int] = None  # ← ADD THIS
    filePath: Optional[str] = None
    fileContent: Optional[str] = None
    selectedText: Optional[str] = None


class VSCodeChatResponse(BaseModel):
    message: str


@router.post("/chat", response_model=VSCodeChatResponse)
async def vscode_chat(
    request: VSCodeChatRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Simple chat endpoint for VS Code Extension with Smart Context.
    
    - Supports project_id for Smart Context (pgvector search)
    - Supports file context (filePath, fileContent, selectedText)
    - Uses same ask_model function as /ask endpoint
    """
    
    try:
        # Get user's OpenAI API key
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Build system prompt
        system_prompt = "You are a helpful coding assistant for VS Code Extension users."
        
        # ========== SMART CONTEXT FROM PGVECTOR ==========
        if request.project_id:
            try:
                indexer = FileIndexer(db)
                # Search for relevant files based on user's question
                relevant_files = await indexer.search_files(
                    project_id=request.project_id,
                    query=request.message,
                    limit=5
                )
                
                if relevant_files:
                    system_prompt += "\n\n🔍 **Relevant files from your codebase:**\n"
                    
                    for file_info in relevant_files:
                        # Get file content
                        content = await indexer.get_file_content(
                            project_id=request.project_id,
                            file_path=file_info["file_path"]
                        )
                        
                        if content:
                            # Truncate long files
                            content_preview = content[:3000]
                            if len(content) > 3000:
                                content_preview += "\n... (truncated)"
                            
                            system_prompt += f"\n\n📄 **{file_info['file_path']}** (similarity: {file_info['similarity']}):\n```{file_info['language']}\n{content_preview}\n```"
                    
                    system_prompt += "\n\n---\nUse the above codebase context to answer the user's question."
            except Exception as e:
                print(f"⚠️ Smart Context error (continuing without): {e}")
        # ========== END SMART CONTEXT ==========
        
        # Add current file context if provided
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
        
        # Build messages array
        messages = [
            {
                "role": "user",
                "content": request.message
            }
        ]
        
        # Call AI model
        ai_response = ask_model(
            messages=messages,
            model_key="gpt-4o-mini",
            system_prompt=system_prompt,
            api_key=user_api_key
        )
        
        return VSCodeChatResponse(message=ai_response)
        
    except Exception as e:
        print(f"❌ Error in /vscode/chat: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error: {str(e)}"
        )