#!/usr/bin/env python3
"""
Migration: Add Auto-Learning tables for Smart Cline

Creates tables for learning from code errors:
- learned_errors: Stores error patterns and solutions
- learned_breaking_changes: Tracks file renames that break imports
- error_resolutions: History of how errors were fixed

Usage:
    python backend/migrations/add_auto_learning_tables.py
    
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
    
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    return database_url


def run_migration():
    """Run the auto-learning tables migration"""
    print("🚀 Starting migration: add_auto_learning_tables")
    
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
        
        # ============================================================
        # Step 2: Create learned_errors table
        # ============================================================
        print("  📋 Checking learned_errors table...")
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'learned_errors'
            )
        """))
        
        if result.scalar():
            print("  ℹ️ Table learned_errors already exists")
        else:
            print("  📝 Creating learned_errors table...")
            conn.execute(text("""
                CREATE TABLE learned_errors (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    
                    -- Error pattern
                    error_pattern TEXT NOT NULL,
                    error_type TEXT,
                    error_code TEXT,
                    file_path TEXT,
                    line_number INTEGER,
                    code_snippet TEXT,
                    
                    -- Solution
                    solution_pattern TEXT,
                    solution_example TEXT,
                    
                    -- Statistics
                    occurrence_count INTEGER DEFAULT 1,
                    resolved_count INTEGER DEFAULT 0,
                    last_seen TIMESTAMP DEFAULT NOW(),
                    first_seen TIMESTAMP DEFAULT NOW(),
                    
                    -- Embedding for semantic search
                    embedding vector(1536),
                    
                    -- Timestamps
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
            print("  ✅ Table learned_errors created")
        
        # ============================================================
        # Step 3: Create learned_breaking_changes table
        # ============================================================
        print("  📋 Checking learned_breaking_changes table...")
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'learned_breaking_changes'
            )
        """))
        
        if result.scalar():
            print("  ℹ️ Table learned_breaking_changes already exists")
        else:
            print("  📝 Creating learned_breaking_changes table...")
            conn.execute(text("""
                CREATE TABLE learned_breaking_changes (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    
                    -- Change info
                    change_type TEXT NOT NULL,
                    old_path TEXT NOT NULL,
                    new_path TEXT,
                    
                    -- Impact
                    broken_files TEXT[],
                    broken_imports TEXT[],
                    broken_count INTEGER DEFAULT 0,
                    
                    -- Status
                    is_resolved BOOLEAN DEFAULT FALSE,
                    resolved_at TIMESTAMP,
                    detected_at TIMESTAMP DEFAULT NOW(),
                    detected_by TEXT DEFAULT 'system'
                )
            """))
            conn.commit()
            print("  ✅ Table learned_breaking_changes created")
        
        # ============================================================
        # Step 4: Create error_resolutions table
        # ============================================================
        print("  📋 Checking error_resolutions table...")
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'error_resolutions'
            )
        """))
        
        if result.scalar():
            print("  ℹ️ Table error_resolutions already exists")
        else:
            print("  📝 Creating error_resolutions table...")
            conn.execute(text("""
                CREATE TABLE error_resolutions (
                    id SERIAL PRIMARY KEY,
                    learned_error_id INTEGER REFERENCES learned_errors(id) ON DELETE CASCADE,
                    original_code TEXT,
                    fixed_code TEXT,
                    fix_method TEXT,
                    fix_successful BOOLEAN DEFAULT TRUE,
                    resolved_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
            print("  ✅ Table error_resolutions created")
        
        # ============================================================
        # Step 5: Create indexes
        # ============================================================
        print("  📊 Creating indexes...")
        
        indexes = [
            ("idx_learned_errors_project", "learned_errors(project_id)"),
            ("idx_learned_errors_type", "learned_errors(error_type)"),
            ("idx_learned_errors_count", "learned_errors(occurrence_count DESC)"),
            ("idx_learned_errors_file", "learned_errors(file_path)"),
            ("idx_breaking_changes_project", "learned_breaking_changes(project_id)"),
            ("idx_breaking_changes_old_path", "learned_breaking_changes(old_path)"),
            ("idx_breaking_changes_resolved", "learned_breaking_changes(is_resolved)"),
            ("idx_resolutions_error", "error_resolutions(learned_error_id)"),
        ]
        
        for idx_name, idx_def in indexes:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}"))
                conn.commit()
            except Exception as e:
                print(f"  ⚠️ Index {idx_name}: {e}")
        
        # Vector index
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_learned_errors_embedding 
                ON learned_errors USING ivfflat (embedding vector_cosine_ops)
            """))
            conn.commit()
        except Exception as e:
            print(f"  ⚠️ Vector index: {e}")
        
        print("  ✅ Indexes created")
        
        # ============================================================
        # Step 6: Add comments
        # ============================================================
        print("  📝 Adding comments...")
        try:
            conn.execute(text("""
                COMMENT ON TABLE learned_errors IS 
                'Stores code error patterns for AI learning - prevents repeated mistakes'
            """))
            conn.execute(text("""
                COMMENT ON TABLE learned_breaking_changes IS 
                'Tracks file renames/deletions that break imports'
            """))
            conn.execute(text("""
                COMMENT ON TABLE error_resolutions IS 
                'History of how errors were fixed - used for learning solutions'
            """))
            conn.commit()
            print("  ✅ Comments added")
        except Exception as e:
            print(f"  ⚠️ Comments: {e}")
        
        print("🎉 Migration completed successfully!")
        return True


def verify_migration():
    """Verify the migration was applied correctly"""
    print("\n🔍 Verifying migration...")
    
    database_url = get_database_url()
    engine = create_engine(database_url)
    
    with engine.connect() as conn:
        tables = ['learned_errors', 'learned_breaking_changes', 'error_resolutions']
        
        for table in tables:
            result = conn.execute(text(f"""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = '{table}'
            """))
            if result.scalar() > 0:
                print(f"  ✅ Table {table} exists")
            else:
                print(f"  ❌ Table {table} missing!")
                return False
        
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