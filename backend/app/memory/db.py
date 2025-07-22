# File: backend/app/memory/db.py

import os
import time
import logging
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import OperationalError

from .models import Base

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
SQLALCHEMY_URL = os.getenv("SQLALCHEMY_URL", f"sqlite:///{DEFAULT_DB_PATH}")
ECHO = (os.getenv("SQLALCHEMY_ECHO", "0").strip().lower() in {"1", "true", "yes", "on"})

# Ensure SQLite directory exists (except for :memory:)
if SQLALCHEMY_URL.startswith("sqlite"):
    # strip "sqlite:///" and normalize
    db_path = SQLALCHEMY_URL.replace("sqlite:///", "", 1)
    if db_path and db_path != ":memory:":
        # Convert to absolute in case a relative path was provided
        abs_path = os.path.abspath(db_path)
        dir_name = os.path.dirname(abs_path)
        try:
            os.makedirs(dir_name, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create SQLite directory '{dir_name}': {e}")

# ─────────────────────────── Engine opts ────────────────────────
engine_args = {"echo": ECHO, "pool_pre_ping": True}

if SQLALCHEMY_URL.startswith("sqlite"):
    # check_same_thread=False for FastAPI multi-threads; add pragmas via events below
    engine_args["connect_args"] = {"check_same_thread": False}
elif SQLALCHEMY_URL.startswith(("postgresql", "postgresql+psycopg")):
    # Reasonable defaults; override via env if needed
    engine_args.update({
        "pool_size": int(os.getenv("SQL_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("SQL_MAX_OVERFLOW", "10")),
        "pool_timeout": int(os.getenv("SQL_POOL_TIMEOUT", "30")),
    })

# ─────────────────────────── Create engine ──────────────────────
try:
    engine = create_engine(SQLALCHEMY_URL, **engine_args)
    logger.info(f"Database engine created: {SQLALCHEMY_URL}")
except Exception as e:
    logger.error(f"❌ Failed to create engine: {e}")
    raise

# ───────────────────── SQLite performance tweaks ────────────────
if SQLALCHEMY_URL.startswith("sqlite"):

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
    """
    for attempt in range(1, retries + 1):
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("✅ Database tables created successfully.")
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
