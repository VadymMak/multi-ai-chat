#!/usr/bin/env python3
"""
Migration: Add query_classification_logs table

Purpose: Log query classifications for ML training data collection (Week 2)
Date: December 9, 2024
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

# Add app to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))


def run_migration():
    """
    Create query_classification_logs table for logging search queries.
    
    This table collects data for future ML model training.
    """
    
    # Get database URL from environment
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("❌ ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    
    print("🔧 Starting migration: add_query_classification_logs")
    print(f"📊 Database: {database_url.split('@')[1] if '@' in database_url else 'localhost'}")
    
    try:
        # Create engine
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Check if table already exists
            check_table = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'query_classification_logs'
                );
            """)
            
            result = conn.execute(check_table)
            table_exists = result.scalar()
            
            if table_exists:
                print("✅ Table 'query_classification_logs' already exists. Skipping migration.")
                return
            
            print("📝 Creating table 'query_classification_logs'...")
            
            # Create table
            create_table = text("""
                CREATE TABLE query_classification_logs (
                    -- Primary key
                    id SERIAL PRIMARY KEY,
                    
                    -- Context
                    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                    user_id INTEGER,
                    
                    -- Query data
                    query TEXT NOT NULL,
                    classified_as VARCHAR(50) NOT NULL,
                    
                    -- Results data (updated after search)
                    search_results_count INTEGER DEFAULT 0,
                    search_took_ms INTEGER DEFAULT 0,
                    
                    -- Timing
                    timestamp TIMESTAMP DEFAULT NOW(),
                    
                    -- User feedback (optional, for ML training quality)
                    user_clicked_result INTEGER,
                    user_satisfied BOOLEAN,
                    
                    -- Constraints
                    CONSTRAINT valid_clicked_result 
                        CHECK (user_clicked_result IS NULL OR user_clicked_result > 0),
                    CONSTRAINT valid_classified_as 
                        CHECK (classified_as IN ('filename', 'symbol', 'pattern', 'semantic', 'hybrid'))
                );
            """)
            
            conn.execute(create_table)
            conn.commit()
            
            print("✅ Table created successfully")
            
            # Create indexes
            print("📝 Creating indexes...")
            
            indexes = [
                ("idx_query_logs_project", "project_id"),
                ("idx_query_logs_timestamp", "timestamp DESC"),
                ("idx_query_logs_classified", "classified_as"),
            ]
            
            for index_name, column in indexes:
                create_index = text(f"""
                    CREATE INDEX IF NOT EXISTS {index_name} 
                    ON query_classification_logs({column});
                """)
                conn.execute(create_index)
                print(f"  ✅ Index '{index_name}' created")
            
            conn.commit()
            
            # Add comments
            print("📝 Adding table comments...")
            
            comments = [
                ("TABLE query_classification_logs", 
                 "Logs query classifications for ML training data collection (Week 2+)"),
                ("COLUMN query_classification_logs.classified_as",
                 "Rule-based classification: filename, symbol, pattern, semantic"),
                ("COLUMN query_classification_logs.user_clicked_result",
                 "Position of result user clicked (1=first, 2=second, etc.). Gold data for training!"),
                ("COLUMN query_classification_logs.user_satisfied",
                 "User feedback: Did they find what they needed? Helps measure accuracy."),
            ]
            
            for target, description in comments:
                comment_sql = text(f"COMMENT ON {target} IS :description")
                conn.execute(comment_sql, {"description": description})
            
            print("✅ Comments added")
            
            conn.commit()
            
            # Verify table
            print("🔍 Verifying table creation...")
            
            verify = text("""
                SELECT 
                    column_name, 
                    data_type, 
                    is_nullable
                FROM information_schema.columns
                WHERE table_name = 'query_classification_logs'
                ORDER BY ordinal_position;
            """)
            
            result = conn.execute(verify)
            columns = result.fetchall()
            
            print(f"✅ Table has {len(columns)} columns:")
            for col in columns:
                nullable = "NULL" if col.is_nullable == "YES" else "NOT NULL"
                print(f"  - {col.column_name}: {col.data_type} ({nullable})")
            
            print("\n🎉 Migration completed successfully!")
            print("\n📊 Usage example:")
            print("""
            from app.services.query_classifier_with_logging import classify_and_log
            
            query_type = classify_and_log(
                query="FileIndexer",
                project_id=18,
                db=db
            )
            """)
            
    except ProgrammingError as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()