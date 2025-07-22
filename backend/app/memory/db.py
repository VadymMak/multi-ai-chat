# File: backend/app/memory/db.py

import os
import time
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import OperationalError

from .models import Base

# ✅ Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Load environment variables
load_dotenv(dotenv_path="E:/projects/ai-assistant/backend/.env")

# ✅ Determine database path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "../../memory.db"))

# ✅ SQLAlchemy database URL
SQLALCHEMY_URL = os.getenv("SQLALCHEMY_URL", f"sqlite:///{DB_PATH}")

# ✅ Engine config based on backend
engine_args = {}
if SQLALCHEMY_URL.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}
elif SQLALCHEMY_URL.startswith("postgresql"):
    engine_args.update({
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
    })

# ✅ Create SQLAlchemy engine
try:
    engine = create_engine(SQLALCHEMY_URL, **engine_args)
    logger.info(f"Database engine created: {SQLALCHEMY_URL}")
except Exception as e:
    logger.error(f"❌ Failed to create engine: {e}")
    raise

# ✅ Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ✅ For FastAPI dependency injection
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ✅ For standalone script access (e.g. insert/test/query)
def get_session() -> Session:
    return SessionLocal()

# ✅ Create tables if missing
def init_db(retries: int = 3):
    for attempt in range(retries):
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("✅ Database tables created successfully.")
            return
        except OperationalError as e:
            logger.warning(f"⚠️ Attempt {attempt+1}/{retries} failed: {e}")
            if attempt == retries - 1:
                logger.error("❌ Failed to create tables after all retries.")
                raise
            time.sleep(1)
