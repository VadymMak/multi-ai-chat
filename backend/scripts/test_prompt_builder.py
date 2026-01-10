import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.prompts.prompt_builder import generate_prompt_from_db

def test_prompt():
    db: Session = SessionLocal()

    prompt = generate_prompt_from_db(
        db=db,
        project_id="1",  # ✅ your sample project
        role_id=1,       # 🚧 adjust to real role if exists
        system_prompt="You are a helpful assistant.",
        youtube_context=["Video A: React structure tips"],
        web_context=["Article: Zustand state management"],
        starter_reply="Sure, I can help with that.",
        user_input="How do I restructure the header component?",
    )

    print("🧾 Final Prompt:\n")
    print(prompt)

if __name__ == "__main__":
    test_prompt()
