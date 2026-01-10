"""
Migration: Add file_dependencies table for Project Builder
Date: 2024-12-06
Description: Creates file_dependencies table to track imports/exports between generated files
             This enables context-aware code generation (Phase 0 - Fix Project Builder)
"""

import os
import logging
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Create file_dependencies table for tracking file imports/exports"""
    
    # Get DATABASE_URL from environment
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("❌ DATABASE_URL not set in environment")
        return False
    
    logger.info(f"🔄 Running file_dependencies table migration...")
    logger.info(f"   Database: {database_url.split('@')[-1] if '@' in database_url else 'local'}")
    
    try:
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Check if table already exists
            check_table_query = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'file_dependencies'
                )
            """)
            
            result = conn.execute(check_table_query)
            table_exists = result.scalar()
            
            if table_exists:
                logger.info("✅ file_dependencies table already exists - skipping migration")
                return True
            
            logger.info("   📝 Creating file_dependencies table...")
            
            # Create table
            create_table_sql = text("""
                CREATE TABLE file_dependencies (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source_file TEXT NOT NULL,
                    target_file TEXT NOT NULL,
                    dependency_type VARCHAR(50),
                    imports_what JSONB,
                    created_at TIMESTAMP DEFAULT NOW(),
                    
                    UNIQUE(project_id, source_file, target_file)
                )
            """)
            
            conn.execute(create_table_sql)
            logger.info("   ✅ Table created")
            
            # Create indexes
            logger.info("   📝 Creating indexes...")
            
            indexes = [
                "CREATE INDEX idx_file_deps_project ON file_dependencies(project_id)",
                "CREATE INDEX idx_file_deps_source ON file_dependencies(source_file)",
                "CREATE INDEX idx_file_deps_target ON file_dependencies(target_file)"
            ]
            
            for idx, index_sql in enumerate(indexes, 1):
                conn.execute(text(index_sql))
                logger.info(f"   ✅ Index {idx}/3 created")
            
            conn.commit()
            
            logger.info("✅ file_dependencies migration completed successfully!")
            logger.info("   📊 Table structure:")
            logger.info("      - id (Primary Key)")
            logger.info("      - project_id (Foreign Key → projects)")
            logger.info("      - source_file (e.g., 'logger.ts')")
            logger.info("      - target_file (e.g., 'types.d.ts')")
            logger.info("      - dependency_type (e.g., 'import')")
            logger.info("      - imports_what (JSONB: ['LogLevel', 'ILogger'])")
            logger.info("      - created_at")
            logger.info("   📈 3 indexes created for performance")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_migration()
    exit(0 if success else 1)