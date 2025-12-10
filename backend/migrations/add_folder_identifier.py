"""
Migration: Add folder_identifier column to projects table
Date: 2024-12-10
Purpose: Enable automatic project detection by VS Code Extension
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.memory.db import SessionLocal
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Add folder_identifier column to projects table"""
    db = SessionLocal()
    
    try:
        logger.info("🔄 Starting migration: add folder_identifier to projects")
        
        # Check if column exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='projects' AND column_name='folder_identifier'
        """))
        
        if result.fetchone():
            logger.info("✅ Column 'folder_identifier' already exists. Skipping migration.")
            db.close()
            return
        
        # Add column
        logger.info("📝 Adding folder_identifier column...")
        db.execute(text("""
            ALTER TABLE projects ADD COLUMN folder_identifier VARCHAR(16)
        """))
        
        # Create index
        logger.info("📊 Creating index on folder_identifier...")
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_projects_folder_identifier 
            ON projects(folder_identifier)
        """))
        
        # Create composite index for user_id + folder_identifier
        logger.info("📊 Creating composite index on (user_id, folder_identifier)...")
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_projects_user_folder 
            ON projects(user_id, folder_identifier)
        """))
        
        db.commit()
        logger.info("✅ Migration completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_migration()