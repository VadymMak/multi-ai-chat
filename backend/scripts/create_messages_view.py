"""Create messages VIEW as alias for memory_entries table"""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from app.config.settings import settings

def migrate():
    """Create messages view that maps to memory_entries"""
    engine = create_engine(settings.DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            print("=" * 80)
            print("🔄 MIGRATION: Create messages VIEW")
            print("=" * 80)
            
            # Check if view already exists
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM information_schema.views 
                    WHERE table_name = 'messages'
                );
            """))
            exists = result.fetchone()[0]
            
            if exists:
                print("✅ VIEW 'messages' already exists! No migration needed.")
                return
            
            print("\n🔧 Creating VIEW 'messages' → 'memory_entries'...")
            
            # Create VIEW that aliases memory_entries
            conn.execute(text("""
                CREATE OR REPLACE VIEW messages AS
                SELECT 
                    id,
                    project_id,
                    project_id_int,
                    role_id,
                    chat_session_id,
                    raw_text as text,
                    'ai' as sender,
                    timestamp as created_at,
                    tokens,
                    summary,
                    is_summary,
                    is_ai_to_ai,
                    deleted,
                    updated_at
                FROM memory_entries
                WHERE deleted = false;
            """))
            
            conn.commit()
            print("✅ VIEW created successfully!")
            
            # Test view
            print("\n🧪 Testing VIEW...")
            result = conn.execute(text("SELECT COUNT(*) FROM messages;"))
            count = result.fetchone()[0]
            print(f"✅ VIEW 'messages' contains {count} records")
            
            print("\n" + "=" * 80)
            print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
            print("=" * 80)
            
    except Exception as e:
        print(f"\n❌ MIGRATION FAILED: {e}")
        print("⚠️  Check if database is running and credentials are correct")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import sys
    
    print("\n⚠️  This will create a VIEW in the database")
    print("    - Creates 'messages' VIEW pointing to 'memory_entries'")
    print("    - Safe: Does NOT modify existing data")
    print("    - Can be reverted with: DROP VIEW messages;\n")
    
    response = input("Continue? (yes/no): ").strip().lower()
    
    if response in ["yes", "y"]:
        migrate()
    else:
        print("❌ Migration cancelled")