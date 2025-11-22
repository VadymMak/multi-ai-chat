"""Add user_id to projects table for multi-user support"""
import psycopg2
from app.config.settings import settings

def migrate():
    # Parse DATABASE_URL
    conn = psycopg2.connect(settings.DATABASE_URL)
    cur = conn.cursor()
    
    try:
        print("🔄 Adding user_id column to projects table...")
        
        # Add user_id column
        cur.execute("""
            ALTER TABLE projects 
            ADD COLUMN IF NOT EXISTS user_id INTEGER;
        """)
        
        # Add foreign key constraint
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'fk_projects_user'
                ) THEN
                    ALTER TABLE projects 
                    ADD CONSTRAINT fk_projects_user 
                    FOREIGN KEY (user_id) 
                    REFERENCES users(id) 
                    ON DELETE CASCADE;
                END IF;
            END $$;
        """)
        
        # Set default user_id to superuser (id=1) for existing projects
        cur.execute("""
            UPDATE projects 
            SET user_id = 1 
            WHERE user_id IS NULL;
        """)
        
        # Make user_id NOT NULL
        cur.execute("""
            ALTER TABLE projects 
            ALTER COLUMN user_id SET NOT NULL;
        """)
        
        conn.commit()
        print("✅ Migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    migrate()