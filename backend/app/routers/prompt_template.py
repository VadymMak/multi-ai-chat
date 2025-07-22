# app/routers/prompt_template.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.memory.db import get_db
from app.memory.models import PromptTemplate
from app.memory.schemas.prompt_template import PromptTemplateCreate, PromptTemplateRead

router = APIRouter(
    prefix="/prompts",
    tags=["Prompt Templates"]
)


# ✅ UPDATED route path here
@router.get("/by-role/{role_id}", response_model=List[PromptTemplateRead])
def get_prompts_by_role(role_id: int, db: Session = Depends(get_db)):
    return db.query(PromptTemplate).filter(PromptTemplate.role_id == role_id).all()


@router.post("/", response_model=PromptTemplateRead)
def create_prompt_template(prompt: PromptTemplateCreate, db: Session = Depends(get_db)):
    new_prompt = PromptTemplate(**prompt.dict())
    db.add(new_prompt)
    db.commit()
    db.refresh(new_prompt)
    return new_prompt


@router.put("/{prompt_id}", response_model=PromptTemplateRead)
def update_prompt_template(prompt_id: int, updated: PromptTemplateCreate, db: Session = Depends(get_db)):
    prompt = db.query(PromptTemplate).filter(PromptTemplate.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="PromptTemplate not found")

    for key, value in updated.dict().items():
        setattr(prompt, key, value)

    db.commit()
    db.refresh(prompt)
    return prompt


@router.delete("/{prompt_id}")
def delete_prompt_template(prompt_id: int, db: Session = Depends(get_db)):
    prompt = db.query(PromptTemplate).filter(PromptTemplate.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="PromptTemplate not found")

    db.delete(prompt)
    db.commit()
    return {"message": f"PromptTemplate {prompt_id} deleted successfully"}
