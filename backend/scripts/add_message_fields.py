"""
Add deleted and updated_at fields to memory_entries table
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app.memory.db import get_session

def migrate():
    db = get_session()
    
    try:
        print("🔧 Adding deleted and updated_at columns to memory_entries...")
        
        # Check if columns already exist
        result = db.execute(text("PRAGMA table_info(memory_entries)")).fetchall()
        columns = [row[1] for row in result]
        
        # Add deleted column
        if 'deleted' not in columns:
            db.execute(text("""
                ALTER TABLE memory_entries 
                ADD COLUMN deleted BOOLEAN DEFAULT 0 NOT NULL
            """))
            db.commit()
            print("✅ Added 'deleted' column")
        else:
            print("⏭️  'deleted' column already exists")
        
        # Add updated_at column (NULL default for SQLite compatibility)
        if 'updated_at' not in columns:
            db.execute(text("""
                ALTER TABLE memory_entries 
                ADD COLUMN updated_at DATETIME
            """))
            db.commit()
            
            # Update existing rows to have current timestamp
            db.execute(text("""
                UPDATE memory_entries 
                SET updated_at = timestamp 
                WHERE updated_at IS NULL
            """))
            db.commit()
            
            print("✅ Added 'updated_at' column and populated with existing timestamps")
        else:
            print("⏭️  'updated_at' column already exists")
        
        # Create index on deleted
        try:
            db.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_memory_entries_deleted 
                ON memory_entries(deleted)
            """))
            db.commit()
            print("✅ Created index on 'deleted'")
        except Exception as e:
            print(f"⚠️  Index creation: {e}")
        
        print("✅ Migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate()