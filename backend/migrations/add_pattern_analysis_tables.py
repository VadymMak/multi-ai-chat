#!/usr/bin/env python3
"""
Migration: Add Pattern Analysis tables for PatternAnalyzer service

Creates tables for caching error categorization and cross-project solutions:
- error_categories: cached per-project error type breakdown (1-hour TTL)
- cross_project_solutions: cached cross-project error pattern matches

Usage:
    python backend/migrations/add_pattern_analysis_tables.py

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
    """Run the pattern analysis tables migration"""
    print("🚀 Starting migration: add_pattern_analysis_tables")

    database_url = get_database_url()
    engine = create_engine(database_url)

    with engine.connect() as conn:
        # ============================================================
        # Step 1: Create error_categories table
        # ============================================================
        print("  📋 Checking error_categories table...")
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'error_categories'
            )
        """))

        if result.scalar():
            print("  ℹ️ Table error_categories already exists")
        else:
            print("  📝 Creating error_categories table...")
            conn.execute(text("""
                CREATE TABLE error_categories (
                    id                  SERIAL PRIMARY KEY,
                    project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

                    -- Category label (equals error_type value or 'other')
                    category_name       VARCHAR(100) NOT NULL,

                    -- Aggregated statistics
                    error_count         INTEGER DEFAULT 0,
                    resolved_count      INTEGER DEFAULT 0,

                    -- Top 3 most affected file paths as JSON array
                    top_files           JSONB DEFAULT '[]',

                    -- Cache freshness — invalidated after 1 hour
                    last_analyzed_at    TIMESTAMP WITH TIME ZONE,

                    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

                    UNIQUE (project_id, category_name)
                )
            """))
            conn.commit()
            print("  ✅ Table error_categories created")

        # ============================================================
        # Step 2: Create cross_project_solutions table
        # ============================================================
        print("  📋 Checking cross_project_solutions table...")
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cross_project_solutions'
            )
        """))

        if result.scalar():
            print("  ℹ️ Table cross_project_solutions already exists")
        else:
            print("  📝 Creating cross_project_solutions table...")
            conn.execute(text("""
                CREATE TABLE cross_project_solutions (
                    id                  SERIAL PRIMARY KEY,

                    -- Project that has the problem
                    source_project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

                    -- Project whose solution was matched
                    target_project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

                    -- Matched error pattern (normalized)
                    error_pattern       TEXT NOT NULL,

                    -- Solution from target project
                    solution_pattern    TEXT,

                    -- 0.0–1.0 similarity/confidence of the match
                    confidence_score    FLOAT DEFAULT 0.0,

                    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            conn.commit()
            print("  ✅ Table cross_project_solutions created")

        # ============================================================
        # Step 3: Create indexes
        # ============================================================
        print("  📊 Creating indexes...")

        indexes = [
            ("idx_error_categories_project",   "error_categories(project_id)"),
            ("idx_error_categories_analyzed",  "error_categories(last_analyzed_at)"),
            ("idx_cross_project_source",       "cross_project_solutions(source_project_id)"),
            ("idx_cross_project_target",       "cross_project_solutions(target_project_id)"),
        ]

        for idx_name, idx_def in indexes:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}"))
                conn.commit()
            except Exception as e:
                print(f"  ⚠️ Index {idx_name}: {e}")

        print("  ✅ Indexes created")

        # ============================================================
        # Step 4: Add comments
        # ============================================================
        print("  📝 Adding comments...")
        try:
            conn.execute(text("""
                COMMENT ON TABLE error_categories IS
                'Cached error-type breakdown per project — recomputed every hour by PatternAnalyzer'
            """))
            conn.execute(text("""
                COMMENT ON TABLE cross_project_solutions IS
                'Cached cross-project error-pattern matches — links problems in one project to solutions in another'
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
        tables = ["error_categories", "cross_project_solutions"]

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
