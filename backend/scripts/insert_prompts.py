# scripts/insert_prompts.py

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import PromptTemplate


def insert_prompt_templates():
    prompts = [
        {
            "role_id": 1,
            "name": "LLM Optimizer",
            "content": "You are an expert in LLM prompt engineering, token efficiency, and system instruction design.",
        },
        {
            "role_id": 2,
            "name": "Frontend Architect",
            "content": "You are a React and TypeScript expert, helping build responsive, accessible, and performant interfaces.",
        },
        {
            "role_id": 3,
            "name": "Marine Troubleshooter",
            "content": "You assist with vessel engineering systems, including electrical layouts, fuel systems, and diagnostics.",
        },
        {
            "role_id": 4,
            "name": "Esoteric Guide",
            "content": "You share insights from Buddhist philosophy, Vedic science, and psychological esotericism.",
        },
        {
            "role_id": 5,
            "name": "Python Coder",
            "content": "You write clean, modular Python code and help with scripts, automation, and backend systems.",
        },
        {
            "role_id": 6,
            "name": "Data Scientist",
            "content": "You analyze datasets, build machine learning models, and visualize results clearly.",
        }
    ]

    db: Session = SessionLocal()

    for prompt in prompts:
        existing = db.query(PromptTemplate).filter(
            PromptTemplate.role_id == prompt["role_id"],
            PromptTemplate.name == prompt["name"]
        ).first()

        if existing:
            print(f"⚠️ Prompt already exists for role {prompt['role_id']}: {prompt['name']}")
            continue

        new_prompt = PromptTemplate(
            role_id=prompt["role_id"],
            name=prompt["name"],
            content=prompt["content"],
            is_default=True
        )
        db.add(new_prompt)
        print(f"✅ Added prompt for role {prompt['role_id']}: {prompt['name']}")

    db.commit()
    print("🎉 Done inserting prompts.")


if __name__ == "__main__":
    insert_prompt_templates()
