#!/usr/bin/env python3
"""
Migration: Add file_embeddings table for Multi-File Context

This table stores embeddings of ALL project files for semantic code search.
Used for debugging assistant and multi-file context features.

Usage:
    python backend/migrations/add_file_embeddings_table.py
    
Safe to run multiple times (idempotent).
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError, OperationalError


def get_database_url():
    """Get database URL from environment"""
    database_url = os.environ.get("DATABASE_URL")
    
    if not database_url:
        # Try loading from .env file
        try:
            from dotenv import load_dotenv
            env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
            load_dotenv(env_path)
            database_url = os.environ.get("DATABASE_URL")
        except ImportError:
            pass
    
    if not database_url:
        print("❌ DATABASE_URL not found in environment")
        sys.exit(1)
    
    # Handle Railway's postgres:// vs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    return database_url


def run_migration():
    """Run the file_embeddings migration"""
    print("🚀 Starting migration: add_file_embeddings_table")
    
    database_url = get_database_url()
    engine = create_engine(database_url)
    
    with engine.connect() as conn:
        # ============================================================
        # Step 1: Ensure pgvector extension exists
        # ============================================================
        print("  📦 Checking pgvector extension...")
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            print("  ✅ pgvector extension ready")
        except Exception as e:
            print(f"  ⚠️ pgvector extension check: {e}")
            # Continue anyway - extension might already exist
        
        # ============================================================
        # Step 2: Check if table already exists
        # ============================================================
        print("  📋 Checking if file_embeddings table exists...")
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'file_embeddings'
            )
        """))
        table_exists = result.scalar()
        
        if table_exists:
            print("  ℹ️ Table file_embeddings already exists, checking for updates...")
            
            # Check if all columns exist
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'file_embeddings'
            """))
            existing_columns = {row[0] for row in result}
            
            required_columns = {
                'id', 'project_id', 'file_path', 'file_name', 'language',
                'content', 'content_hash', 'file_size', 'line_count',
                'embedding', 'metadata', 'created_at', 'updated_at', 'indexed_at'
            }
            
            missing_columns = required_columns - existing_columns
            
            if missing_columns:
                print(f"  ⚠️ Missing columns: {missing_columns}")
                # Add missing columns here if needed
            else:
                print("  ✅ All columns present")
            
            # Check indexes
            result = conn.execute(text("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename = 'file_embeddings'
            """))
            existing_indexes = {row[0] for row in result}
            print(f"  📊 Existing indexes: {existing_indexes}")
            
            print("  ✅ Migration already applied, skipping table creation")
            return True
        
        # ============================================================
        # Step 3: Create the table
        # ============================================================
        print("  📝 Creating file_embeddings table...")
        
        conn.execute(text("""
            CREATE TABLE file_embeddings (
                id SERIAL PRIMARY KEY,
                
                -- Project reference
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                
                -- File information
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                language VARCHAR(50),
                
                -- Content
                content TEXT,
                content_hash VARCHAR(64),
                file_size INTEGER,
                line_count INTEGER,
                
                -- Embedding (pgvector) - 1536 dimensions for text-embedding-3-small
                embedding vector(1536),
                
                -- Metadata (JSON for flexibility)
                metadata JSONB DEFAULT '{}',
                
                -- Timestamps
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                indexed_at TIMESTAMP DEFAULT NOW(),
                
                -- Unique constraint
                UNIQUE(project_id, file_path)
            )
        """))
        conn.commit()
        print("  ✅ Table created")
        
        # ============================================================
        # Step 4: Create indexes
        # ============================================================
        print("  📊 Creating indexes...")
        
        # Vector similarity search index (IVFFlat)
        try:
            conn.execute(text("""
                CREATE INDEX idx_file_embeddings_vector 
                ON file_embeddings USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """))
            conn.commit()
            print("  ✅ Vector index created")
        except Exception as e:
            print(f"  ⚠️ Vector index: {e}")
        
        # Project filtering index
        try:
            conn.execute(text("""
                CREATE INDEX idx_file_embeddings_project 
                ON file_embeddings(project_id)
            """))
            conn.commit()
            print("  ✅ Project index created")
        except Exception as e:
            print(f"  ⚠️ Project index: {e}")
        
        # File path lookup index
        try:
            conn.execute(text("""
                CREATE INDEX idx_file_embeddings_path 
                ON file_embeddings(project_id, file_path)
            """))
            conn.commit()
            print("  ✅ Path index created")
        except Exception as e:
            print(f"  ⚠️ Path index: {e}")
        
        # Language filtering index
        try:
            conn.execute(text("""
                CREATE INDEX idx_file_embeddings_language 
                ON file_embeddings(language)
            """))
            conn.commit()
            print("  ✅ Language index created")
        except Exception as e:
            print(f"  ⚠️ Language index: {e}")
        
        # Content hash index (for change detection)
        try:
            conn.execute(text("""
                CREATE INDEX idx_file_embeddings_hash 
                ON file_embeddings(project_id, content_hash)
            """))
            conn.commit()
            print("  ✅ Hash index created")
        except Exception as e:
            print(f"  ⚠️ Hash index: {e}")
        
        # ============================================================
        # Step 5: Add table comments
        # ============================================================
        print("  📝 Adding comments...")
        try:
            conn.execute(text("""
                COMMENT ON TABLE file_embeddings IS 
                'Stores embeddings of project files for semantic code search'
            """))
            conn.execute(text("""
                COMMENT ON COLUMN file_embeddings.embedding IS 
                'OpenAI text-embedding-3-small vector (1536 dimensions)'
            """))
            conn.execute(text("""
                COMMENT ON COLUMN file_embeddings.content_hash IS 
                'SHA-256 hash of content for detecting file changes'
            """))
            conn.execute(text("""
                COMMENT ON COLUMN file_embeddings.metadata IS 
                'JSON with imports, exports, classes, functions extracted from file'
            """))
            conn.commit()
            print("  ✅ Comments added")
        except Exception as e:
            print(f"  ⚠️ Comments: {e}")
        
        # ============================================================
        # Step 6: Create helper functions
        # ============================================================
        print("  🔧 Creating helper functions...")
        
        # search_similar_files function
        try:
            conn.execute(text("""
                CREATE OR REPLACE FUNCTION search_similar_files(
                    p_project_id INTEGER,
                    p_query_embedding vector(1536),
                    p_limit INTEGER DEFAULT 5
                )
                RETURNS TABLE (
                    id INTEGER,
                    file_path TEXT,
                    file_name TEXT,
                    language VARCHAR(50),
                    similarity FLOAT
                ) AS $$
                BEGIN
                    RETURN QUERY
                    SELECT 
                        fe.id,
                        fe.file_path,
                        fe.file_name,
                        fe.language,
                        1 - (fe.embedding <=> p_query_embedding) AS similarity
                    FROM file_embeddings fe
                    WHERE fe.project_id = p_project_id
                      AND fe.embedding IS NOT NULL
                    ORDER BY fe.embedding <=> p_query_embedding
                    LIMIT p_limit;
                END;
                $$ LANGUAGE plpgsql
            """))
            conn.commit()
            print("  ✅ search_similar_files function created")
        except Exception as e:
            print(f"  ⚠️ search_similar_files function: {e}")
        
        # get_project_file_stats function
        try:
            conn.execute(text("""
                CREATE OR REPLACE FUNCTION get_project_file_stats(p_project_id INTEGER)
                RETURNS TABLE (
                    language VARCHAR(50),
                    file_count BIGINT,
                    total_lines BIGINT,
                    total_size BIGINT
                ) AS $$
                BEGIN
                    RETURN QUERY
                    SELECT 
                        fe.language,
                        COUNT(*)::BIGINT AS file_count,
                        COALESCE(SUM(fe.line_count), 0)::BIGINT AS total_lines,
                        COALESCE(SUM(fe.file_size), 0)::BIGINT AS total_size
                    FROM file_embeddings fe
                    WHERE fe.project_id = p_project_id
                    GROUP BY fe.language
                    ORDER BY file_count DESC;
                END;
                $$ LANGUAGE plpgsql
            """))
            conn.commit()
            print("  ✅ get_project_file_stats function created")
        except Exception as e:
            print(f"  ⚠️ get_project_file_stats function: {e}")
        
        print("🎉 Migration completed successfully!")
        return True


def verify_migration():
    """Verify the migration was applied correctly"""
    print("\n🔍 Verifying migration...")
    
    database_url = get_database_url()
    engine = create_engine(database_url)
    
    with engine.connect() as conn:
        # Check table exists
        result = conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_name = 'file_embeddings'
        """))
        table_count = result.scalar()
        
        if table_count == 0:
            print("  ❌ Table file_embeddings does not exist!")
            return False
        
        print("  ✅ Table file_embeddings exists")
        
        # Check column count
        result = conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_name = 'file_embeddings'
        """))
        column_count = result.scalar()
        print(f"  ✅ {column_count} columns found")
        
        # Check index count
        result = conn.execute(text("""
            SELECT COUNT(*) FROM pg_indexes 
            WHERE tablename = 'file_embeddings'
        """))
        index_count = result.scalar()
        print(f"  ✅ {index_count} indexes found")
        
        # Check vector extension
        result = conn.execute(text("""
            SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')
        """))
        has_vector = result.scalar()
        if has_vector:
            print("  ✅ pgvector extension installed")
        else:
            print("  ⚠️ pgvector extension not found")
        
        print("\n✅ Migration verified successfully!")
        return True


if __name__ == "__main__":
    try:
        success = run_migration()
        if success:
            verify_migration()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)