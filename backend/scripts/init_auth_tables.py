"""
Initialize authentication tables for multi-user system.
Run this once to add User, UserAPIKey tables and update Projects.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app.memory.db import engine, SessionLocal
from app.memory.models import Base, User, UserAPIKey
from app.config.settings import settings

def run_migration():
    """Create new tables and update existing ones"""
    print("🔄 Starting authentication system migration...")
    
    db = SessionLocal()
    
    try:
        # Create new tables (User, UserAPIKey)
        print("📋 Creating User and UserAPIKey tables...")
        Base.metadata.create_all(bind=engine, tables=[
            User.__table__,
            UserAPIKey.__table__
        ])
        print("✅ Tables created successfully")
        
        # Update Projects table (add user_id, assistant_id columns)
        print("📋 Updating Projects table...")
        
        # Check if columns exist
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='projects' AND column_name IN ('user_id', 'assistant_id', 'created_at', 'updated_at')
        """))
        existing_columns = {row[0] for row in result}
        
        # Add user_id column if not exists
        if 'user_id' not in existing_columns:
            print("  Adding user_id column...")
            db.execute(text("""
                ALTER TABLE projects 
                ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE
            """))
            db.commit()
            print("  ✅ user_id column added")
        else:
            print("  ℹ️ user_id column already exists")
        
        # Add assistant_id column if not exists
        if 'assistant_id' not in existing_columns:
            print("  Adding assistant_id column...")
            db.execute(text("""
                ALTER TABLE projects 
                ADD COLUMN assistant_id INTEGER REFERENCES roles(id) ON DELETE SET NULL
            """))
            db.commit()
            print("  ✅ assistant_id column added")
        else:
            print("  ℹ️ assistant_id column already exists")
        
        # Add timestamps if not exist
        if 'created_at' not in existing_columns:
            print("  Adding created_at column...")
            db.execute(text("""
                ALTER TABLE projects 
                ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """))
            db.commit()
            print("  ✅ created_at column added")
        
        if 'updated_at' not in existing_columns:
            print("  Adding updated_at column...")
            db.execute(text("""
                ALTER TABLE projects 
                ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """))
            db.commit()
            print("  ✅ updated_at column added")
        
        # Remove unique constraint from projects.name (users can have same project names)
        print("  Removing unique constraint from projects.name...")
        try:
            db.execute(text("""
                ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_name_key
            """))
            db.commit()
            print("  ✅ Unique constraint removed")
        except Exception as e:
            print(f"  ⚠️ Could not remove constraint (may not exist): {e}")
        
        print("✅ Projects table updated successfully")
        
        print("\n🎉 Migration completed successfully!")
        print("\n📋 Next steps:")
        print("1. Set ENCRYPTION_KEY in Railway environment variables")
        print("   Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
        print("2. Set JWT_SECRET_KEY in Railway environment variables")
        print("3. Set SUPERUSER_EMAIL and SUPERUSER_PASSWORD")
        print("4. Restart backend - superuser will be auto-created")
        print("5. Update frontend to use new auth endpoints")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()
