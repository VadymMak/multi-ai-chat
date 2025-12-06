"""
Migration: Add file_specifications table for Project Builder
Date: 2024-12-06
Description: Creates file_specifications table to store file specs and generated code
             This enables saving specifications and tracking generation status
"""

import os
import logging
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Create file_specifications table for storing file specs and code"""
    
    # Get DATABASE_URL from environment
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("❌ DATABASE_URL not set in environment")
        return False
    
    logger.info(f"🔄 Running file_specifications table migration...")
    logger.info(f"   Database: {database_url.split('@')[-1] if '@' in database_url else 'local'}")
    
    try:
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Check if table already exists
            check_table_query = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'file_specifications'
                )
            """)
            
            result = conn.execute(check_table_query)
            table_exists = result.scalar()
            
            if table_exists:
                logger.info("✅ file_specifications table already exists - skipping migration")
                return True
            
            logger.info("   📝 Creating file_specifications table...")
            
            # Create table
            create_table_sql = text("""
                CREATE TABLE file_specifications (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    file_path TEXT NOT NULL,
                    file_number INTEGER,
                    description TEXT,
                    specification JSONB,
                    generated_code TEXT,
                    language VARCHAR(50),
                    status VARCHAR(20) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    
                    UNIQUE(project_id, file_path)
                )
            """)
            
            conn.execute(create_table_sql)
            logger.info("   ✅ Table created")
            
            # Create indexes
            logger.info("   📝 Creating indexes...")
            
            indexes = [
                "CREATE INDEX idx_file_specs_project ON file_specifications(project_id)",
                "CREATE INDEX idx_file_specs_status ON file_specifications(status)",
                "CREATE INDEX idx_file_specs_file_number ON file_specifications(file_number)"
            ]
            
            for idx, index_sql in enumerate(indexes, 1):
                conn.execute(text(index_sql))
                logger.info(f"   ✅ Index {idx}/3 created")
            
            conn.commit()
            
            logger.info("✅ file_specifications migration completed successfully!")
            logger.info("   📊 Table structure:")
            logger.info("      - id (Primary Key)")
            logger.info("      - project_id (Foreign Key → projects)")
            logger.info("      - file_path (e.g., 'src/logger.ts')")
            logger.info("      - file_number (e.g., 1, 2, 3)")
            logger.info("      - description (what this file does)")
            logger.info("      - specification (JSONB: full spec)")
            logger.info("      - generated_code (TEXT: actual code)")
            logger.info("      - language (e.g., 'typescript')")
            logger.info("      - status ('pending', 'generated', 'error')")
            logger.info("      - created_at, updated_at")
            logger.info("   📈 3 indexes created for performance")
            logger.info("")
            logger.info("   📋 Use cases:")
            logger.info("      1. Save file specifications from Debate Mode")
            logger.info("      2. Track which files are generated")
            logger.info("      3. Store generated code for context")
            logger.info("      4. Enable context-aware generation")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_migration()
    exit(0 if success else 1)