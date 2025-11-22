"""
Database Migration: Add user_id and related columns to projects table

This migration adds multi-user support to the projects table by:
- Adding user_id column (foreign key to users)
- Adding assistant_id column (foreign key to roles)
- Adding created_at and updated_at timestamps
- Setting existing projects to admin user (id=1)
"""

from sqlalchemy import text, inspect
from app.memory.db import engine
import sys

def check_column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists in table"""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns

def migrate():
    """Run the migration"""
    print("=" * 80)
    print("🔄 MIGRATION: Add user_id to projects table")
    print("=" * 80)
    
    conn = engine.connect()
    trans = conn.begin()
    
    try:
        # Check if migration already applied
        if check_column_exists('projects', 'user_id'):
            print("\n✅ Migration already applied! Column 'user_id' exists.")
            print("   Nothing to do.")
            conn.close()
            return True
        
        print("\n📊 Pre-migration check...")
        
        # Count existing projects
        result = conn.execute(text("SELECT COUNT(*) FROM projects;"))
        project_count = result.fetchone()[0]
        print(f"   Existing projects: {project_count}")
        
        # Check for admin user
        result = conn.execute(text(
            "SELECT id, username FROM users WHERE is_superuser = true ORDER BY id LIMIT 1;"
        ))
        admin = result.fetchone()
        
        if not admin:
            print("\n❌ ERROR: No superuser found in database!")
            print("   Please create an admin user first.")
            trans.rollback()
            conn.close()
            return False
        
        admin_id, admin_username = admin
        print(f"   Admin user: {admin_username} (id={admin_id})")
        
        # Start migration steps
        print("\n🔧 Step 1/7: Adding user_id column...")
        conn.execute(text("ALTER TABLE projects ADD COLUMN user_id INTEGER;"))
        print("   ✅ Column added (nullable)")
        
        print("\n🔧 Step 2/7: Adding foreign key constraint to users...")
        conn.execute(text("""
            ALTER TABLE projects 
            ADD CONSTRAINT fk_projects_user 
            FOREIGN KEY (user_id) 
            REFERENCES users(id) 
            ON DELETE CASCADE;
        """))
        print("   ✅ Foreign key constraint added")
        
        print(f"\n🔧 Step 3/7: Setting user_id={admin_id} for existing projects...")
        result = conn.execute(text(f"UPDATE projects SET user_id = {admin_id} WHERE user_id IS NULL;"))
        updated = result.rowcount
        print(f"   ✅ Updated {updated} projects")
        
        print("\n🔧 Step 4/7: Making user_id NOT NULL...")
        conn.execute(text("ALTER TABLE projects ALTER COLUMN user_id SET NOT NULL;"))
        print("   ✅ Column is now required")
        
        print("\n🔧 Step 5/7: Adding assistant_id column...")
        conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS assistant_id INTEGER;"))
        print("   ✅ Column added")
        
        print("\n🔧 Step 6/7: Adding foreign key to roles...")
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_projects_assistant'
                ) THEN
                    ALTER TABLE projects 
                    ADD CONSTRAINT fk_projects_assistant 
                    FOREIGN KEY (assistant_id) 
                    REFERENCES roles(id) 
                    ON DELETE SET NULL;
                END IF;
            END $$;
        """))
        print("   ✅ Foreign key constraint added")
        
        print("\n🔧 Step 7/7: Adding timestamp columns...")
        conn.execute(text(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
        ))
        conn.execute(text(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
        ))
        print("   ✅ Timestamp columns added")
        
        # Commit transaction
        trans.commit()
        
        print("\n" + "=" * 80)
        print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        
        # Show final structure
        print("\n📋 Final table structure:")
        result = conn.execute(text("""
            SELECT 
                column_name, 
                data_type, 
                is_nullable,
                column_default
            FROM information_schema.columns 
            WHERE table_name = 'projects' 
            ORDER BY ordinal_position;
        """))
        
        print(f"\n   {'Column':<20} {'Type':<25} {'Nullable':<10} {'Default':<20}")
        print("   " + "-" * 80)
        for row in result:
            col_name, data_type, nullable, default = row
            default_str = str(default)[:20] if default else ""
            print(f"   {col_name:<20} {data_type:<25} {nullable:<10} {default_str:<20}")
        
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
    """Main entry point with confirmation"""
    print("\n" + "=" * 80)
    print("DATABASE MIGRATION SCRIPT")
    print("=" * 80)
    print("\nThis script will:")
    print("  • Add 'user_id' column to projects table")
    print("  • Add 'assistant_id' column to projects table")
    print("  • Add 'created_at' and 'updated_at' timestamps")
    print("  • Set existing projects to admin user (id=1)")
    print("  • Add foreign key constraints")
    print("\n⚠️  This will modify the database structure!")
    print("=" * 80)
    
    # Ask for confirmation
    response = input("\nContinue with migration? (yes/no): ").strip().lower()
    
    if response not in ['yes', 'y']:
        print("\n❌ Migration cancelled by user")
        return 1
    
    # Run migration
    success = migrate()
    
    if success:
        print("\n✅ Migration completed successfully!")
        print("   You can now restart your backend server.")
        return 0
    else:
        print("\n❌ Migration failed!")
        print("   Database was rolled back to previous state.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
