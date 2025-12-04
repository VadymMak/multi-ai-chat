"""
VS Code Extension API endpoints.
Simple chat interface without project/role complexity.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.deps import get_current_active_user, get_db
from app.memory.models import User
from app.providers.factory import ask_model  # ✅ Используем ту же функцию что и в ask.py!
from app.utils.api_key_resolver import get_openai_key  # ✅ Правильный импорт

router = APIRouter(prefix="/vscode", tags=["vscode"])


# Request/Response Models
class VSCodeChatRequest(BaseModel):
    message: str


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
    - Uses same ask_model function as /ask endpoint
    - User must be authenticated (JWT token)
    """
    
    try:
        # ✅ Get user's OpenAI API key (same way as /ask does)
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # ✅ Build simple messages array
        messages = [
            {
                "role": "user",
                "content": request.message
            }
        ]
        
        # ✅ Simple system prompt
        system_prompt = "You are a helpful coding assistant for VS Code Extension users."
        
        # ✅ Use the same ask_model function that /ask uses!
        ai_response = ask_model(
            messages=messages,
            model_key="gpt-4o-mini",  # Fast and cheap
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