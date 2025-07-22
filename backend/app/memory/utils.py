# app/memory/utils.py

import tiktoken
import unicodedata
from sqlalchemy.orm import Session
from app.memory.models import Project

MAX_MEMORY_TOKENS = 1000
ENCODING_MODEL = "gpt-3.5-turbo"

enc = tiktoken.encoding_for_model(ENCODING_MODEL)


def trim_memory(texts: list[str], max_tokens: int = MAX_MEMORY_TOKENS) -> str:
    """Join, tokenize and trim memory to the last `max_tokens`."""
    joined = "\n\n".join(texts)
    tokens = enc.encode(joined)
    if len(tokens) > max_tokens:
        tokens = tokens[-max_tokens:]
    return enc.decode(tokens)


def get_project_structure(db: Session, project_id: int) -> str:
    """Retrieve project_structure markdown string for prompt injection."""
    project = db.query(Project).filter(Project.id == project_id).first()
    return project.project_structure or "" if project else ""

def safe_text(s: str) -> str:
    """
    Remove invalid unicode characters (surrogates, control codes) from strings
    so they can safely be returned to the frontend (especially JSON/UTF-8).
    """
    if not isinstance(s, str):
        return str(s)
    return ''.join(c for c in s if unicodedata.category(c) != "Cs")