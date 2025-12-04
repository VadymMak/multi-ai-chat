"""
VS Code Extension API endpoints.
Simple chat interface without project/role complexity.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.deps import get_current_active_user, get_db
from app.memory.models import User
from app.providers.factory import ask_model
from app.utils.api_key_resolver import get_openai_key

router = APIRouter(prefix="/vscode", tags=["vscode"])


# Request/Response Models
class VSCodeChatRequest(BaseModel):
    message: str
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
    Simple chat endpoint for VS Code Extension.
    
    - No project_id/role_id required
    - Supports file context (filePath, fileContent, selectedText)
    - Uses same ask_model function as /ask endpoint
    - User must be authenticated (JWT token)
    """
    
    try:
        # Get user's OpenAI API key
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Build system prompt with file context
        system_prompt = "You are a helpful coding assistant for VS Code Extension users."
        
        # Add file context if provided
        if request.filePath:
            system_prompt += f"\n\n📁 Current file: {request.filePath}"
        
        if request.selectedText:
            # If user selected code, focus on that
            system_prompt += f"\n\n✂️ Selected code:\n```\n{request.selectedText}\n```"
            system_prompt += "\n\nFocus on explaining/improving the selected code above."
        elif request.fileContent:
            # If no selection, include full file content (limited to 5000 chars)
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