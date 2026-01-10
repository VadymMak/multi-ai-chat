"""
One-time migration: Change roles.description from VARCHAR(255) to TEXT
Run with: python migrate_description.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from app.config.settings import settings

def migrate():
    engine = create_engine(settings.database_url)
    
    with engine.connect() as conn:
        print("🔄 Altering roles.description to TEXT...")
        conn.execute(text("ALTER TABLE roles ALTER COLUMN description TYPE TEXT;"))
        conn.commit()
        print("✅ Migration complete!")

if __name__ == "__main__":
    migrate()