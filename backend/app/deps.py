from typing import Generator               # ✅ добавляем
from fastapi import Depends
from sqlalchemy.orm import Session
from app.memory.db import SessionLocal

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency – открыть сессию и закрыть после запроса."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
