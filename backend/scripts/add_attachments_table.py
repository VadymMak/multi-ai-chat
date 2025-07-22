"""
Add attachments table for file uploads
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app.memory.db import get_session

def migrate():
    db = get_session()
    
    try:
        print("🔧 Creating attachments table...")
        
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                filename VARCHAR(255) NOT NULL,
                original_filename VARCHAR(255) NOT NULL,
                file_type VARCHAR(50) NOT NULL,
                mime_type VARCHAR(100) NOT NULL,
                file_size INTEGER NOT NULL,
                file_path VARCHAR(500) NOT NULL,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (message_id) REFERENCES memory_entries(id) ON DELETE CASCADE
            )
        """))
        
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_attachments_message_id 
            ON attachments(message_id)
        """))
        
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_attachments_id 
            ON attachments(id)
        """))
        
        db.commit()
        print("✅ Attachments table created successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate()