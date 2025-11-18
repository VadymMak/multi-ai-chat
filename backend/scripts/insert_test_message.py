import sys
import os
import uuid
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import ChatMessage

def insert_test_message(role_id: int, project_id: int):
    db: Session = SessionLocal()

    session_id = str(uuid.uuid4())
    now = datetime.utcnow()

    # User message
    user_msg = ChatMessage(
        sender="user",
        text="Hello, this is a test message",
        chat_session_id=session_id,
        role_id=role_id,
        project_id=project_id,
        timestamp=now,
        is_summary=False
    )
    db.add(user_msg)

    # Assistant message
    assistant_msg = ChatMessage(
        sender="assistant",
        text="Hi there! This is a test assistant reply.",
        chat_session_id=session_id,
        role_id=role_id,
        project_id=project_id,
        timestamp=now,
        is_summary=False
    )
    db.add(assistant_msg)

    db.commit()
    db.close()

    print(f"✅ Inserted test conversation for role_id={role_id}, project_id={project_id}")
    print(f"   chat_session_id = {session_id}")

if __name__ == "__main__":
    # Example: Frontend Developer (role_id=2) + UI Refactor (project_id=2)
    insert_test_message(role_id=2, project_id=2)
