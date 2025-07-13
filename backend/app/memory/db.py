# backend/app/memory/db.py
import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv
from .models import Base

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(dotenv_path="E:/projects/ai-assistant/backend/.env")

# Database URL: Default to SQLite, allow override via environment variable
SQLALCHEMY_URL = os.getenv("SQLALCHEMY_URL", "sqlite:///./memory.db")

# Engine configuration
engine_args = {}
if SQLALCHEMY_URL.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}
elif SQLALCHEMY_URL.startswith("postgresql"):
    engine_args["pool_size"] = 5
    engine_args["max_overflow"] = 10
    engine_args["pool_timeout"] = 30

try:
    engine = create_engine(SQLALCHEMY_URL, **engine_args)
    logger.info(f"Database engine created: {SQLALCHEMY_URL}")
except Exception as e:
    logger.error(f"Failed to create database engine: {e}")
    raise

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db() -> None:
    """Create tables if they don't exist, with retry logic for robustness."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables created successfully")
            return
        except OperationalError as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed to create tables: {e}")
            if attempt == max_retries - 1:
                logger.error("Failed to create database tables after retries")
                raise
            import time
            time.sleep(1)  # Wait before retrying

def get_db():
    """Dependency to provide a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()