"""
Migration: Add Full Text Search (FTS) to file_embeddings table
Date: 2026-01-12
Description: Adds tsvector column and GIN index for lexical search
             This enables exact word matching in addition to semantic search
"""

import os
import logging
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Add FTS (Full Text Search) support to file_embeddings table"""
    
    # Get DATABASE_URL from environment
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("❌ DATABASE_URL not set in environment")
        return False
    
    logger.info(f"🔄 Running FTS migration for file_embeddings...")
    logger.info(f"   Database: {database_url.split('@')[-1] if '@' in database_url else 'local'}")
    
    try:
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Check if column already exists
            check_column_query = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'file_embeddings'
                    AND column_name = 'content_tsv'
                )
            """)
            
            result = conn.execute(check_column_query)
            column_exists = result.scalar()
            
            if column_exists:
                logger.info("✅ content_tsv column already exists - skipping migration")
                return True
            
            # Step 1: Add tsvector column
            logger.info("   📝 Adding content_tsv column...")
            add_column_sql = text("""
                ALTER TABLE file_embeddings 
                ADD COLUMN IF NOT EXISTS content_tsv tsvector
            """)
            conn.execute(add_column_sql)
            logger.info("   ✅ Column added")
            
            # Step 2: Populate existing records
            logger.info("   📝 Populating content_tsv for existing records...")
            logger.info("   ⏳ This may take a while for large tables...")
            
            update_sql = text("""
                UPDATE file_embeddings 
                SET content_tsv = to_tsvector('english', COALESCE(content, ''))
                WHERE content_tsv IS NULL
            """)
            result = conn.execute(update_sql)
            updated_count = result.rowcount
            logger.info(f"   ✅ Updated {updated_count} records")
            
            # Step 3: Create GIN index for fast search
            logger.info("   📝 Creating GIN index for FTS...")
            
            # Check if index exists
            check_index_query = text("""
                SELECT EXISTS (
                    SELECT FROM pg_indexes 
                    WHERE indexname = 'idx_file_embeddings_fts'
                )
            """)
            result = conn.execute(check_index_query)
            index_exists = result.scalar()
            
            if not index_exists:
                create_index_sql = text("""
                    CREATE INDEX idx_file_embeddings_fts 
                    ON file_embeddings USING GIN(content_tsv)
                """)
                conn.execute(create_index_sql)
                logger.info("   ✅ GIN index created")
            else:
                logger.info("   ✅ GIN index already exists")
            
            # Step 4: Create trigger for auto-update
            logger.info("   📝 Creating trigger for auto-update...")
            
            # Create or replace the trigger function
            create_function_sql = text("""
                CREATE OR REPLACE FUNCTION update_file_embeddings_tsv()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.content_tsv := to_tsvector('english', COALESCE(NEW.content, ''));
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
            """)
            conn.execute(create_function_sql)
            logger.info("   ✅ Trigger function created")
            
            # Check if trigger exists and drop it first (to avoid duplicates)
            drop_trigger_sql = text("""
                DROP TRIGGER IF EXISTS file_embeddings_tsv_trigger 
                ON file_embeddings
            """)
            conn.execute(drop_trigger_sql)
            
            # Create trigger
            create_trigger_sql = text("""
                CREATE TRIGGER file_embeddings_tsv_trigger
                BEFORE INSERT OR UPDATE ON file_embeddings
                FOR EACH ROW EXECUTE FUNCTION update_file_embeddings_tsv()
            """)
            conn.execute(create_trigger_sql)
            logger.info("   ✅ Trigger created")
            
            conn.commit()
            
            logger.info("")
            logger.info("✅ FTS migration completed successfully!")
            logger.info("")
            logger.info("   📊 What was added:")
            logger.info("      - content_tsv (tsvector) - Full Text Search vector")
            logger.info("      - idx_file_embeddings_fts (GIN index) - Fast FTS lookup")
            logger.info("      - Auto-update trigger - Keeps content_tsv in sync")
            logger.info("")
            logger.info("   📋 Usage example:")
            logger.info("      SELECT file_path, ts_rank(content_tsv, query) as rank")
            logger.info("      FROM file_embeddings, to_tsquery('english', 'useState & React') query")
            logger.info("      WHERE content_tsv @@ query")
            logger.info("      ORDER BY rank DESC")
            logger.info("      LIMIT 10;")
            logger.info("")
            logger.info("   🎯 Benefits:")
            logger.info("      - Exact word matching (vs semantic similarity)")
            logger.info("      - Fast searches with GIN index")
            logger.info("      - Automatic updates via trigger")
            logger.info("      - Combines with pgvector for hybrid search")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_migration()
    exit(0 if success else 1)