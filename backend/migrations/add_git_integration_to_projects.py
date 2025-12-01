"""
Migration: Add Git Integration fields to projects table
Date: 2024-12-01
Description: Adds git_url, git_updated_at, git_sync_status columns to projects table
"""

import os
import logging
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Add Git integration fields to projects table"""
    
    # Get DATABASE_URL from environment
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("❌ DATABASE_URL not set in environment")
        return False
    
    logger.info(f"🔄 Running Git integration migration...")
    logger.info(f"   Database: {database_url.split('@')[-1] if '@' in database_url else 'local'}")
    
    try:
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Check if columns already exist
            check_query = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'projects' 
                AND column_name IN ('git_url', 'git_updated_at', 'git_sync_status')
            """)
            
            result = conn.execute(check_query)
            existing_columns = [row[0] for row in result]
            
            if len(existing_columns) == 3:
                logger.info("✅ Git integration columns already exist - skipping migration")
                return True
            
            # Add columns if they don't exist
            migrations = []
            
            if 'git_url' not in existing_columns:
                migrations.append(
                    "ALTER TABLE projects ADD COLUMN git_url VARCHAR(500) NULL"
                )
                logger.info("   📝 Adding column: git_url")
            
            if 'git_updated_at' not in existing_columns:
                migrations.append(
                    "ALTER TABLE projects ADD COLUMN git_updated_at TIMESTAMP NULL"
                )
                logger.info("   📝 Adding column: git_updated_at")
            
            if 'git_sync_status' not in existing_columns:
                migrations.append(
                    "ALTER TABLE projects ADD COLUMN git_sync_status VARCHAR(20) NULL"
                )
                logger.info("   📝 Adding column: git_sync_status")
            
            # Execute migrations
            for migration_sql in migrations:
                conn.execute(text(migration_sql))
            
            conn.commit()
            
            logger.info("✅ Git integration migration completed successfully!")
            logger.info(f"   Added {len(migrations)} column(s)")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_migration()
    exit(0 if success else 1)