#!/usr/bin/env python3
"""
Migration: Add Prediction tables for Structural Prediction Service

Creates tables for caching and logging impact predictions:
- prediction_cache: caches impact results per (project, changed_files_hash) with TTL
- prediction_history: logs every prediction made and optional accuracy feedback

Usage:
    python backend/migrations/add_prediction_tables.py

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
    """Run the prediction tables migration"""
    print("🚀 Starting migration: add_prediction_tables")

    database_url = get_database_url()
    engine = create_engine(database_url)

    with engine.connect() as conn:
        # ============================================================
        # Step 1: Create prediction_cache table
        # ============================================================
        print("  📋 Checking prediction_cache table...")
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'prediction_cache'
            )
        """))

        if result.scalar():
            print("  ℹ️ Table prediction_cache already exists")
        else:
            print("  📝 Creating prediction_cache table...")
            conn.execute(text("""
                CREATE TABLE prediction_cache (
                    id                SERIAL PRIMARY KEY,
                    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

                    -- Cache key: MD5 hash of sorted changed_files JSON
                    changed_files_hash TEXT NOT NULL,

                    -- Cached result as JSON string
                    result_json       TEXT NOT NULL,

                    -- TTL timestamps
                    created_at        TIMESTAMP DEFAULT NOW(),
                    expires_at        TIMESTAMP NOT NULL
                )
            """))
            conn.commit()
            print("  ✅ Table prediction_cache created")

        # ============================================================
        # Step 2: Create prediction_history table
        # ============================================================
        print("  📋 Checking prediction_history table...")
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'prediction_history'
            )
        """))

        if result.scalar():
            print("  ℹ️ Table prediction_history already exists")
        else:
            print("  📝 Creating prediction_history table...")
            conn.execute(text("""
                CREATE TABLE prediction_history (
                    id                SERIAL PRIMARY KEY,
                    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

                    -- Input: files that were changed
                    changed_files     TEXT[] NOT NULL,

                    -- Predicted impact (JSON)
                    predicted_impact  TEXT NOT NULL,

                    -- Actual impact filled in later for accuracy tracking
                    actual_impact     TEXT,

                    -- Accuracy score (0.0 - 1.0), filled after actual impact known
                    accuracy_score    FLOAT,

                    created_at        TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
            print("  ✅ Table prediction_history created")

        # ============================================================
        # Step 3: Create indexes
        # ============================================================
        print("  📊 Creating indexes...")

        indexes = [
            ("idx_prediction_cache_project",      "prediction_cache(project_id)"),
            ("idx_prediction_cache_hash",          "prediction_cache(changed_files_hash)"),
            ("idx_prediction_cache_expires",       "prediction_cache(expires_at)"),
            ("idx_prediction_history_project",     "prediction_history(project_id)"),
            ("idx_prediction_history_created_at",  "prediction_history(created_at DESC)"),
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
                COMMENT ON TABLE prediction_cache IS
                'Caches structural impact predictions per project + changed_files hash (TTL: 5 min)'
            """))
            conn.execute(text("""
                COMMENT ON TABLE prediction_history IS
                'Logs all impact predictions made; accuracy_score filled after actual impact observed'
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
        tables = ["prediction_cache", "prediction_history"]

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
