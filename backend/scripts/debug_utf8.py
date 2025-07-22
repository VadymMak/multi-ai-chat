# scripts/debug_utf8.py

import sys
import os
import unicodedata
import logging
from sqlalchemy.orm import Session

# ✅ Add root path to sys.path so 'app.memory' can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.memory.db import SessionLocal  # ✅ correct location of db.py
from app.memory.models import MemoryEntry, AuditLog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("utf8-debug")

def is_valid_utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False

def analyze_invalid_chars(text: str) -> list:
    return [
        f"U+{ord(c):04X} ({unicodedata.name(c, 'UNKNOWN')})"
        for c in text
        if not is_valid_utf8(c)
    ]

def scan_memory_table(db: Session):
    rows = db.query(MemoryEntry).all()
    logger.info(f"🔍 Scanning MemoryEntry → {len(rows)} rows")
    for row in rows:
        for field_name in ["summary", "raw_text"]:
            value = getattr(row, field_name)
            if value and not is_valid_utf8(value):
                bad_chars = analyze_invalid_chars(value)
                logger.warning(f"[❌ UTF-8 Error] row_id={row.id}, field={field_name}, bad_chars={bad_chars}")

def scan_audit_log(db: Session):
    rows = db.query(AuditLog).all()
    logger.info(f"🔍 Scanning AuditLog → {len(rows)} rows")
    for row in rows:
        if row.query and not is_valid_utf8(row.query):
            bad_chars = analyze_invalid_chars(row.query)
            logger.warning(f"[❌ UTF-8 Error] audit_id={row.id}, field=query, bad_chars={bad_chars}")

def main():
    db = SessionLocal()
    try:
        scan_memory_table(db)
        scan_audit_log(db)
        logger.info("✅ UTF-8 scan complete.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
