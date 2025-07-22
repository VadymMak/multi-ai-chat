# File: backend/app/memory/db.py

import os
import time
import logging
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import OperationalError

from .models import Base

__all__ = ["engine", "SessionLocal", "Base", "get_db", "init_db", "DATABASE_URL", "SQLALCHEMY_URL"]

# ─────────────────────────── Logging ───────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────── .env resolution ───────────────────────
# Try project .env first; fall back to current working dir
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENV_CANDIDATES = [
    os.path.join(PROJECT_ROOT, ".env"),
    os.environ.get("ENV_FILE", ""),  # allow override
]

for candidate in ENV_CANDIDATES:
    if candidate and os.path.exists(candidate):
        load_dotenv(dotenv_path=candidate)
        logger.info(f"Loaded .env from: {candidate}")
        break
else:
    # As a last resort, load default .env if present in CWD
    load_dotenv()
    logger.info("Loaded .env from current working directory (if present).")

# ───────────────────── Database URL / Paths ─────────────────────
DEFAULT_DB_PATH = os.path.abspath(os.path.join(PROJECT_ROOT, "memory.db"))
DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
SQLALCHEMY_URL: str = DATABASE_URL  # Backward compatibility alias
ECHO = (os.getenv("SQLALCHEMY_ECHO", "0").strip().lower() in {"1", "true", "yes", "on"})

# Ensure SQLite directory exists (except for :memory:)
if DATABASE_URL.startswith("sqlite"):
    # strip "sqlite:///" and normalize
    db_path = DATABASE_URL.replace("sqlite:///", "", 1)
    if db_path and db_path != ":memory:":
        # Convert to absolute in case a relative path was provided
        abs_path = os.path.abspath(db_path)
        dir_name = os.path.dirname(abs_path)
        try:
            os.makedirs(dir_name, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create SQLite directory '{dir_name}': {e}")

# ─────────────────────────── Create engine ──────────────────────
try:
    if DATABASE_URL.startswith("postgresql"):
        # PostgreSQL with connection pooling
        from sqlalchemy.pool import QueuePool
        
        engine = create_engine(
            DATABASE_URL,
            poolclass=QueuePool,
            pool_size=int(os.getenv("SQL_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("SQL_MAX_OVERFLOW", "10")),
            pool_timeout=int(os.getenv("SQL_POOL_TIMEOUT", "30")),
            pool_recycle=int(os.getenv("SQL_POOL_RECYCLE", "3600")),
            pool_pre_ping=True,
            echo=ECHO
        )
        logger.info("✅ PostgreSQL configured with connection pooling")
        logger.info(f"Database URL: {DATABASE_URL.split('@')[0]}@***")  # Hide credentials
    else:
        # SQLite without pooling
        from sqlalchemy.pool import NullPool
        
        engine = create_engine(
            DATABASE_URL,
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
            echo=ECHO
        )
        logger.info("✅ SQLite configured (development mode)")
        logger.info(f"Database path: {DATABASE_URL}")
        
except Exception as e:
    logger.error(f"❌ Failed to create engine: {e}")
    raise

# ───────────────────── SQLite performance tweaks ────────────────
if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore[no-redef]
        try:
            cursor = dbapi_connection.cursor()
            # Keep foreign keys enforced and use WAL for better concurrency
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            # Cache size negative = KB pages in memory cache
            cursor.execute("PRAGMA cache_size=-64000;")
            cursor.close()
        except Exception as e:
            # Never fail app due to pragma issues
            logger.warning(f"SQLite PRAGMA setup warning: {e}")

# ───────────────────────── Session factory ──────────────────────
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# FastAPI dependency
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Standalone scripts utility
def get_session() -> Session:
    return SessionLocal()

# ────────────────────────── Init helpers ────────────────────────
def init_db(retries: int = 3, delay: float = 1.0) -> None:
    """
    Create all tables (including CanonItem) with a small retry loop for
    first-boot races (e.g., containerized environments).
    Also enables pgvector extension for PostgreSQL databases.
    """
    for attempt in range(1, retries + 1):
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("✅ Database tables created successfully.")
            
            # Enable pgvector extension (PostgreSQL only)
            if str(engine.url).startswith("postgresql"):
                try:
                    with engine.connect() as conn:
                        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                        conn.commit()
                    logger.info("✅ pgvector extension enabled")
                except Exception as e:
                    logger.warning(f"⚠️ pgvector extension not available: {e}")
                    logger.info("💡 Semantic search will be disabled. Install pgvector to enable.")
            
            return
        except OperationalError as e:
            logger.warning(f"⚠️ Attempt {attempt}/{retries} failed creating tables: {e}")
            if attempt == retries:
                logger.error("❌ Failed to create tables after all retries.")
                raise
            time.sleep(delay)

# Optionally initialize at import if desired; harmless if tables exist
if os.getenv("INIT_DB_ON_IMPORT", "1").strip().lower() in {"1", "true", "yes", "on"}:
    try:
        init_db()
    except Exception:
        # Don't crash import path; app can still call init on startup
        logger.exception("DB init at import failed; continuing. App may initialize on startup.")

__all__ = [
    "engine",
    "SessionLocal", 
    "Base",
    "get_db",
    "init_db",
    "DATABASE_URL",
    "SQLALCHEMY_URL"
]
