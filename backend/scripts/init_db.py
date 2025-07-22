# File: scripts/init_db.py

import os
from sqlalchemy import create_engine
from app.memory.models import Base

# Define path to SQLite DB
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "memory.db")
DB_URL = f"sqlite:///{DB_PATH}"

# Create engine and bind to metadata
engine = create_engine(DB_URL, echo=True)

def init_database():
    print(f"🔄 Initializing DB at {DB_PATH}")
    Base.metadata.drop_all(bind=engine)  # ❗ Optional: Drop existing tables (CAUTION in prod)
    Base.metadata.create_all(bind=engine)
    print("✅ Database schema created successfully.")

if __name__ == "__main__":
    init_database()
