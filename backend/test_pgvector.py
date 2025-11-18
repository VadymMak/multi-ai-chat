"""
Simple test to check if pgvector is enabled
"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get database URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

print(f"🔍 Checking database: {DATABASE_URL.split('@')[0]}...")  # Hide password

try:
    # Create engine
    engine = create_engine(DATABASE_URL)
    
    # Test connection
    with engine.connect() as conn:
        print("✅ Connected to database")
        
        # Check if PostgreSQL
        if "postgresql" not in DATABASE_URL.lower():
            print("❌ NOT using PostgreSQL - using SQLite")
            print("   Vector search requires PostgreSQL")
            sys.exit(1)
        
        print("✅ Using PostgreSQL")
        
        # Check pgvector extension
        result = conn.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ).scalar()
        
        if result:
            print("✅ pgvector extension is ENABLED")
            
            # Check if memory_entries has embedding column
            check_column = conn.execute(
                text("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = 'memory_entries' 
                    AND column_name = 'embedding'
                """)
            ).fetchone()
            
            if check_column:
                print(f"✅ memory_entries.embedding column exists (type: {check_column[1]})")
            else:
                print("⚠️  memory_entries.embedding column NOT found")
                print("   Run migration to add embedding column")
            
            print("\n🎉 Vector search is ready to use!")
            
        else:
            print("❌ pgvector extension NOT enabled")
            print("\n📋 To enable pgvector, run this SQL command:")
            print("   CREATE EXTENSION vector;")
            
except Exception as e:
    print(f"❌ Error: {e}")
    print(f"\n💡 Make sure DATABASE_URL is set in .env")