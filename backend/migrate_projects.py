"""Safely add user_id to projects table"""
import os
from sqlalchemy import create_engine, text
from app.config.settings import settings

def migrate():
    # Use SQLAlchemy engine (like the app does)
    engine = create_engine(settings.DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            print("=" * 80)
            print("🔄 MIGRATION: Add user_id to projects table")
            print("=" * 80)
            
            # Check if column already exists
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM information_schema.columns 
                    WHERE table_name = 'projects' 
                    AND column_name = 'user_id'
                );
            """))
            exists = result.fetchone()[0]
            
            if exists:
                print("✅ Column 'user_id' already exists! No migration needed.")
                return
            
            # Count existing projects
            result = conn.execute(text("SELECT COUNT(*) FROM projects;"))
            project_count = result.fetchone()[0]
            print(f"\n📊 Found {project_count} existing projects")
            
            # Check if admin user exists
            result = conn.execute(text("SELECT id FROM users WHERE is_superuser = true LIMIT 1;"))
            admin = result.fetchone()
            if not admin:
                print("❌ No superuser found! Create admin user first.")
                return
            
            admin_id = admin[0]
            print(f"👤 Admin user id: {admin_id}")
            
            print("\n🔧 Step 1: Adding user_id column (nullable)...")
            conn.execute(text("ALTER TABLE projects ADD COLUMN user_id INTEGER;"))
            conn.commit()
            print("✅ Column added")
            
            print("\n🔧 Step 2: Adding foreign key constraint...")
            conn.execute(text("""
                ALTER TABLE projects 
                ADD CONSTRAINT fk_projects_user 
                FOREIGN KEY (user_id) 
                REFERENCES users(id) 
                ON DELETE CASCADE;
            """))
            conn.commit()
            print("✅ Foreign key added")
            
            print(f"\n🔧 Step 3: Setting user_id={admin_id} for existing projects...")
            result = conn.execute(text(f"UPDATE projects SET user_id = {admin_id} WHERE user_id IS NULL;"))
            conn.commit()
            print(f"✅ Updated {result.rowcount} projects")
            
            print("\n🔧 Step 4: Making user_id NOT NULL...")
            conn.execute(text("ALTER TABLE projects ALTER COLUMN user_id SET NOT NULL;"))
            conn.commit()
            print("✅ Column is now NOT NULL")
            
            # Add assistant_id if not exists
            print("\n🔧 Step 5: Adding assistant_id column (if not exists)...")
            conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS assistant_id INTEGER;"))
            conn.commit()
            
            # Add foreign key for assistant_id
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
            conn.commit()
            print("✅ Assistant FK added")
            
            # Add timestamps
            print("\n🔧 Step 6: Adding timestamps...")
            conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
            conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
            conn.commit()
            print("✅ Timestamps added")
            
            print("\n" + "=" * 80)
            print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
            print("=" * 80)
            
            # Show final structure
            print("\n📋 Final structure:")
            result = conn.execute(text("""
                SELECT column_name, data_type, is_nullable 
                FROM information_schema.columns 
                WHERE table_name = 'projects' 
                ORDER BY ordinal_position;
            """))
            for row in result:
                print(f"   {row[0]:<20} {row[1]:<15} (nullable: {row[2]})")
            
    except Exception as e:
        print(f"\n❌ MIGRATION FAILED: {e}")
        print("⚠️  Check if database is running and credentials are correct")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import sys
    
    print("\n⚠️  WARNING: This will modify the database!")
    print("    - Add 'user_id' column to projects table")
    print("    - Set existing projects to admin user")
    print("    - Add foreign key constraint\n")
    
    response = input("Continue? (yes/no): ").strip().lower()
    
    if response in ["yes", "y"]:
        migrate()
    else:
        print("❌ Migration cancelled")