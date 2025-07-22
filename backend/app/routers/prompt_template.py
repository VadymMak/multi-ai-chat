# app/routers/prompt_template.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List

from app.memory.db import get_db
from app.memory.models import PromptTemplate, Role
from app.memory.schemas.prompt_template import (
    PromptTemplateCreate,
    PromptTemplateRead,
)

router = APIRouter(prefix="/prompts", tags=["Prompt Templates"])


@router.get("/by-role/{role_id}", response_model=List[PromptTemplateRead])
def get_prompts_by_role(
    role_id: int,
    db: Session = Depends(get_db),
):
    # Optional: ensure role exists (gives clearer error than empty list)
    if db.get(Role, role_id) is None:
        raise HTTPException(status_code=404, detail="Role not found")

    rows = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.role_id == role_id)
        .order_by(PromptTemplate.is_default.desc(), PromptTemplate.name.asc())
        .all()
    )
    return rows


@router.post("/", response_model=PromptTemplateRead, status_code=201)
def create_prompt_template(
    payload: PromptTemplateCreate,
    db: Session = Depends(get_db),
):
    # Ensure role exists
    if db.get(Role, payload.role_id) is None:
        raise HTTPException(status_code=404, detail="Role not found")

    new_prompt = PromptTemplate(**payload.model_dump())
    db.add(new_prompt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Unique per role: (role_id, name)
        raise HTTPException(
            status_code=409,
            detail="A prompt with this name already exists for the role.",
        )
    db.refresh(new_prompt)
    return new_prompt


@router.put("/{prompt_id}", response_model=PromptTemplateRead)
def update_prompt_template(
    prompt_id: int,
    updated: PromptTemplateCreate,
    db: Session = Depends(get_db),
):
    prompt = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.id == prompt_id)
        .first()
    )
    if not prompt:
        raise HTTPException(status_code=404, detail="PromptTemplate not found")

    # Ensure role exists if role_id is changing (some schemas include it)
    if updated.role_id and db.get(Role, updated.role_id) is None:
        raise HTTPException(status_code=404, detail="Role not found")

    for key, value in updated.model_dump().items():
        setattr(prompt, key, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A prompt with this name already exists for the role.",
        )
    db.refresh(prompt)
    return prompt


@router.delete("/{prompt_id}", status_code=200)
def delete_prompt_template(
    prompt_id: int,
    db: Session = Depends(get_db),
):
    prompt = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.id == prompt_id)
        .first()
    )
    if not prompt:
        raise HTTPException(status_code=404, detail="PromptTemplate not found")

    db.delete(prompt)
    db.commit()
    return {"message": f"PromptTemplate {prompt_id} deleted successfully"}
