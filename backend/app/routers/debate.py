"""
Debate Router
Endpoint для режима дебатов между AI моделями
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional, Union
from sqlalchemy.orm import Session
from uuid import uuid4

from app.memory.db import get_db
from app.memory.models import Role, Project
from app.services.debate_manager import debate_manager

router = APIRouter(tags=["Debate"])


class DebateRequest(BaseModel):
    """
    Request model для запуска дебата
    """
    topic: str
    rounds: int = 3
    session_id: Optional[str] = None
    role_id: Optional[int] = None
    project_id: Optional[Union[int, str]] = None
    
    @field_validator("topic")
    @classmethod
    def topic_not_empty(cls, value: str) -> str:
        """Проверяет что topic не пустой"""
        if not value or not value.strip():
            raise ValueError("topic cannot be empty")
        return value.strip()
    
    @field_validator("rounds")
    @classmethod
    def rounds_valid(cls, value: int) -> int:
        """Проверяет что количество раундов валидно"""
        if value < 1:
            raise ValueError("rounds must be at least 1")
        if value > 10:
            raise ValueError("rounds cannot exceed 10")
        return value
    
    @field_validator("role_id")
    @classmethod
    def role_id_positive(cls, value: Optional[int]) -> Optional[int]:
        """Проверяет что role_id положительный если указан"""
        if value is not None and value <= 0:
            raise ValueError("role_id must be a positive integer")
        return value
    
    @field_validator("project_id", mode="before")
    @classmethod
    def project_id_safe(cls, v):
        """Проверяет что project_id валидный если указан"""
        if v is None or v == "":
            return None
        if v == "default":
            raise ValueError("project_id cannot be 'default'")
        s = str(v).strip()
        if not s.isdigit() or int(s) <= 0:
            raise ValueError("project_id must be a positive integer")
        return s


@router.post("/debate")
def start_debate(
    data: DebateRequest,
    db: Session = Depends(get_db)
):
    """
    Запускает дебат между AI моделями
    
    Args:
        data: DebateRequest с темой дебата и параметрами
        db: Database session
        
    Returns:
        Полная структура дебата с результатами всех раундов
        
    Raises:
        HTTPException: При ошибках валидации или выполнения
    """
    
    # Validate role_id if provided
    if data.role_id is not None:
        role = db.get(Role, data.role_id)
        if not role:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown role_id={data.role_id}. Create the role first."
            )
    
    # Validate project_id if provided
    if data.project_id is not None:
        project_id_str = str(data.project_id).strip()
        if not project_id_str.isdigit() or int(project_id_str) <= 0:
            raise HTTPException(
                status_code=400,
                detail="project_id must be a positive integer"
            )
        project_id_int = int(project_id_str)
        project = db.get(Project, project_id_int)
        if not project:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown project_id={project_id_int}. Create/link the project first."
            )
    
    # Generate session_id if not provided
    session_id = data.session_id or str(uuid4())
    
    print(f"\n🎯 Starting debate: '{data.topic[:100]}...'")
    print(f"   Rounds: {data.rounds}, Session: {session_id}")
    
    try:
        # Start the debate (synchronous call)
        result = debate_manager.start_debate(
            topic=data.topic,
            rounds=data.rounds,
            session_id=session_id
        )
        
        print(f"✅ Debate completed successfully!")
        print(f"   Total tokens: {result['total_tokens']}")
        print(f"   Total cost: ${result['total_cost']}")
        
        return result
        
    except ValueError as e:
        # Handle validation errors from debate_manager
        raise HTTPException(status_code=400, detail=str(e))
        
    except Exception as e:
        # Handle unexpected errors
        print(f"❌ Error in /debate: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Debate execution failed: {str(e)}"
        )


@router.get("/debate/{debate_id}")
async def get_debate(debate_id: str):
    """
    Получает результаты дебата по ID (placeholder для будущей функциональности)
    
    Args:
        debate_id: UUID дебата
        
    Returns:
        Результаты дебата
        
    Note:
        Пока не реализовано хранение дебатов в БД
    """
    raise HTTPException(
        status_code=501,
        detail="Debate history retrieval not yet implemented"
    )
