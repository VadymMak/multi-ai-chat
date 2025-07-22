# backend/scripts/test_insert_prompt_template.py

import sys
import os
from sqlalchemy.orm import Session

# ✅ Add backend/ to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(script_dir, ".."))
sys.path.append(backend_root)

from app.memory.db import SessionLocal
from app.memory.models import Role, PromptTemplate

def insert_test_prompt():
    db: Session = SessionLocal()

    # Check or create dummy role
    role = db.query(Role).filter_by(name="Test Prompt Role").first()
    if not role:
        role = Role(name="Test Prompt Role", description="For prompt template testing")
        db.add(role)
        db.commit()
        db.refresh(role)

    # Insert prompt template
    prompt = PromptTemplate(
        role_id=role.id,
        name="Default Prompt",
        content="You are a helpful assistant specialized in [role].",
        is_default=True
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)

    print("✅ Prompt inserted:")
    print(f"Role: {role.name} (ID: {role.id})")
    print(f"Prompt: {prompt.name} (ID: {prompt.id}) → {prompt.content}")

    db.close()

if __name__ == "__main__":
    insert_test_prompt()
