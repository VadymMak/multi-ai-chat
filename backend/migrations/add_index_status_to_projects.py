"""
Migration: Add index status columns to projects table
Date: 2024-12-10
Purpose: Track project indexing status and file count
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
    """Add indexed_at and files_count columns to projects table"""
    db = SessionLocal()
    
    try:
        logger.info("🔄 Starting migration: add index status to projects")
        
        # Check if column exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='projects' AND column_name='indexed_at'
        """))
        
        if result.fetchone():
            logger.info("✅ Column 'indexed_at' already exists. Skipping migration.")
            db.close()
            return
        
        # Add indexed_at column
        logger.info("📝 Adding indexed_at column...")
        db.execute(text("""
            ALTER TABLE projects ADD COLUMN indexed_at TIMESTAMP
        """))
        
        # Add files_count column
        logger.info("📝 Adding files_count column...")
        db.execute(text("""
            ALTER TABLE projects ADD COLUMN files_count INTEGER DEFAULT 0
        """))
        
        # Create index on indexed_at
        logger.info("📊 Creating index on indexed_at...")
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_projects_indexed_at 
            ON projects(indexed_at)
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