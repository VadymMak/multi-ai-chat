"""
Database Migration: Add file_versions table

This migration adds version control for files (our own Git):
- Track every change to files
- Support rollback to any version
- Track AI vs user changes
- Link changes to Agentic Plans
"""

from sqlalchemy import text, inspect
from app.memory.db import engine
import sys


def check_table_exists(table_name: str) -> bool:
    """Check if table exists"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def migrate():
    """Run the migration"""
    print("=" * 80)
    print("🔄 MIGRATION: Add file_versions table")
    print("=" * 80)
    
    conn = engine.connect()
    trans = conn.begin()
    
    try:
        # Check if migration already applied
        if check_table_exists('file_versions'):
            print("\n✅ Migration already applied! Table 'file_versions' exists.")
            print("   Nothing to do.")
            conn.close()
            return True
        
        print("\n📊 Pre-migration check...")
        
        # Check file_embeddings exists
        if not check_table_exists('file_embeddings'):
            print("\n❌ ERROR: Table 'file_embeddings' not found!")
            print("   Please run file_embeddings migration first.")
            trans.rollback()
            conn.close()
            return False
        
        # Count existing files
        result = conn.execute(text("SELECT COUNT(*) FROM file_embeddings;"))
        file_count = result.fetchone()[0]
        print(f"   Existing files in file_embeddings: {file_count}")
        
        # Create table
        print("\n🔧 Step 1/4: Creating file_versions table...")
        conn.execute(text("""
            CREATE TABLE file_versions (
                id SERIAL PRIMARY KEY,
                file_id INTEGER REFERENCES file_embeddings(id) ON DELETE CASCADE,
                version_number INTEGER NOT NULL,
                content TEXT NOT NULL,
                diff_from_previous TEXT,
                change_type TEXT NOT NULL,
                change_source TEXT NOT NULL,
                change_message TEXT,
                user_id INTEGER REFERENCES users(id),
                ai_model TEXT,
                plan_id TEXT,
                step_num INTEGER,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(file_id, version_number)
            );
        """))
        print("   ✅ Table created")
        
        # Create indexes
        print("\n🔧 Step 2/4: Creating index on file_id...")
        conn.execute(text(
            "CREATE INDEX idx_versions_file ON file_versions(file_id);"
        ))
        print("   ✅ Index created")
        
        print("\n🔧 Step 3/4: Creating index on created_at...")
        conn.execute(text(
            "CREATE INDEX idx_versions_created ON file_versions(created_at DESC);"
        ))
        print("   ✅ Index created")
        
        print("\n🔧 Step 4/4: Creating index on change_source...")
        conn.execute(text(
            "CREATE INDEX idx_versions_source ON file_versions(change_source);"
        ))
        print("   ✅ Index created")
        
        # Commit transaction
        trans.commit()
        
        print("\n" + "=" * 80)
        print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        
        # Show table structure
        print("\n📋 Table structure:")
        result = conn.execute(text("""
            SELECT 
                column_name, 
                data_type, 
                is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'file_versions' 
            ORDER BY ordinal_position;
        """))
        
        print(f"\n   {'Column':<20} {'Type':<25} {'Nullable':<10}")
        print("   " + "-" * 55)
        for row in result:
            col_name, data_type, nullable = row
            print(f"   {col_name:<20} {data_type:<25} {nullable:<10}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"\n❌ MIGRATION FAILED: {e}")
        print("\n🔄 Rolling back changes...")
        trans.rollback()
        conn.close()
        
        import traceback
        print("\n📋 Full error details:")
        traceback.print_exc()
        
        return False


def main():
    """Main entry point - auto mode for CI/CD"""
    print("\n" + "=" * 80)
    print("DATABASE MIGRATION: file_versions")
    print("=" * 80)
    print("\nThis script will create 'file_versions' table for:")
    print("  • Track every file change (our own Git)")
    print("  • Store full content + diff")
    print("  • Track change source (user/ai_edit/ai_create/ai_fix)")
    print("  • Link to Agentic Plans (plan_id, step_num)")
    print("  • Enable rollback to any version")
    print("=" * 80)
    
    # Auto-run in CI/CD (no input needed)
    success = migrate()
    
    if success:
        print("\n✅ Migration completed!")
        return 0
    else:
        print("\n❌ Migration failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())