from __future__ import annotations

import logging
import os
import traceback
from contextlib import asynccontextmanager
from typing import Any, Dict

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException



# ───────────────────── .env & logging ─────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

# DB init (ensures all tables exist, including CanonItem)
from app.memory.db import init_db, DATABASE_URL


# ──────────────────── App lifespan hook ───────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info(f"Initializing database… URL={DATABASE_URL}")
        init_db()

        # 🔧 One-time migration: roles.description VARCHAR(255) -> TEXT
        try:
            from sqlalchemy import create_engine, text
            engine = create_engine(DATABASE_URL)
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE roles ALTER COLUMN description TYPE TEXT;"))
                conn.commit()
                logger.info("✅ Migration: roles.description -> TEXT")
        except Exception as e:
            logger.info(f"ℹ️ Migration skipped (already done or not needed): {e}")
        
        # Create superuser on startup if configured
        await create_superuser()
        
        # 🌱 Seed database with default data
        try:
            from app.seed import run_seed
            run_seed()
        except Exception as e:
            logger.error(f"❌ Failed to seed database: {e}")
            import traceback
            traceback.print_exc()
        
        yield
    finally:
        pass


# ────────────────────── FastAPI app ───────────────────────
app = FastAPI(
    title="Multi LLM Assistant",
    description=(
        "API for crypto market trading with LLM, YouTube data, file uploads, "
        "and sentiment analytics"
    ),
    version="1.0.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

# ──────────────────── CORS configuration ──────────────────
# Allow multiple origins via env: CORS_ORIGINS="http://localhost:3000,https://example.com"
raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").strip()
allow_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
# Support wildcard explicitly if requested
if allow_origins == ["*"]:
    logger.info("CORS allow_origins: * (all)")
else:
    logger.info(f"CORS allow_origins: {allow_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins if allow_origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────── Global JSON error handlers ───────────────
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail if isinstance(exc.detail, str) else "HTTP error",
            "path": request.url.path,
        },
    )


def _sanitize_pydantic_errors(errors: Any) -> list[Dict[str, Any]]:
    """
    Convert Pydantic/Starlette validation errors into JSON-serializable dictionaries.
    Avoid putting non-serializable objects (e.g., raw Exceptions) into the payload.
    """
    out: list[dict] = []
    if not isinstance(errors, list):
        return out

    for e in errors:
        if not isinstance(e, dict):
            continue
        item: Dict[str, Any] = {
            "loc": e.get("loc"),
            "msg": e.get("msg"),
            "type": e.get("type"),
        }
        # Optional: include input only if it's simple/serializable
        if "input" in e:
            try:
                val = e.get("input")
                item["input"] = val if isinstance(val, (str, int, float, bool, type(None))) else str(val)
            except Exception:
                item["input"] = None

        # Sanitize ctx (can contain raw Exception objects)
        ctx = e.get("ctx")
        if isinstance(ctx, dict):
            safe_ctx: Dict[str, Any] = {}
            for k, v in ctx.items():
                if isinstance(v, (str, int, float, bool, type(None))):
                    safe_ctx[k] = v
                else:
                    safe_ctx[k] = str(v)
            if safe_ctx:
                item["ctx"] = safe_ctx

        out.append(item)
    return out


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = _sanitize_pydantic_errors(exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation error",
            "errors": errors,
            "path": request.url.path,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception at %s %s", request.method, request.url.path)
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Internal server error: {type(exc).__name__}",
            "path": request.url.path,
        },
    )


# ─────────────────────── Routers ──────────────────────────
# Keep imports after app creation to avoid circulars during startup
from app.routers import (  # noqa: E402
    ask,
    ask_ai_to_ai,
    ask_ai_to_ai_turn,
    youtube,
    chat,
    projects,
    audit,
    roles,
    balance,
    debate,
    init,
    auth,
    api_keys,
    admin,
)

# Optional routers (guarded so startup doesn't crash if missing)
try:
    from app.routers.upload_file import router as upload_router  # type: ignore  # noqa: E402
    logger.info("Loaded optional router: upload_file")
except Exception as e:
    upload_router = None  # type: ignore
    logger.info(f"Optional router 'upload_file' not available: {e}")

try:
    from app.routers.prompt_template import router as prompt_template_router  # type: ignore  # noqa: E402
    logger.info("Loaded optional router: prompt_template")
except Exception as e:
    prompt_template_router = None  # type: ignore
    logger.info(f"Optional router 'prompt_template' not available: {e}")

# Single API prefix for everything
app.include_router(init.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(api_keys.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
app.include_router(ask_ai_to_ai.router, prefix="/api")
app.include_router(ask_ai_to_ai_turn.router, prefix="/api")
app.include_router(youtube.router, prefix="/api")
if upload_router:
    app.include_router(upload_router, prefix="/api")
if prompt_template_router:
    app.include_router(prompt_template_router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(roles.router, prefix="/api")
app.include_router(balance.router, prefix="/api")
app.include_router(debate.router, prefix="/api")

# ───────────────────── Runtime config (safe) ──────────────
from app.config.settings import settings  # noqa: E402
from app.config.model_registry import MODEL_REGISTRY  # noqa: E402


def _resolve_key_for_model_name(name: str | None) -> str | None:
    if not name:
        return None
    for k, v in MODEL_REGISTRY.items():
        if v.get("model") == name:
            return k
    return None


@app.get("/api/config")
def read_config():
    # NEVER return secrets; only presence flags + non-sensitive config
    return {
        "env": {
            "OPENAI_API_KEY_present": bool(os.getenv("OPENAI_API_KEY")),
            "ANTHROPIC_API_KEY_present": bool(os.getenv("ANTHROPIC_API_KEY")),
            "YOUTUBE_API_KEY_present": bool(os.getenv("YOUTUBE_API_KEY")),
            "BACKEND_URL": os.getenv("BACKEND_URL"),
        },
        "cors": {
            "allow_origins": allow_origins,
        },
        "models": {
            "default_registry_key": settings.DEFAULT_MODEL,
            "default_registry_entry": MODEL_REGISTRY.get(settings.DEFAULT_MODEL),

            "openai_default_model_name": settings.OPENAI_DEFAULT_MODEL,
            "openai_default_registry_key": _resolve_key_for_model_name(settings.OPENAI_DEFAULT_MODEL),

            "openai_fallback_model_name": settings.OPENAI_FALLBACK_MODEL,
            "openai_fallback_registry_key": _resolve_key_for_model_name(settings.OPENAI_FALLBACK_MODEL),

            "anthropic_default_model_name": settings.ANTHROPIC_DEFAULT_MODEL,
            "anthropic_default_registry_key": _resolve_key_for_model_name(settings.ANTHROPIC_DEFAULT_MODEL),

            "anthropic_fallback_model_name": settings.ANTHROPIC_FALLBACK_MODEL,
            "anthropic_fallback_registry_key": _resolve_key_for_model_name(settings.ANTHROPIC_FALLBACK_MODEL),
        },
        "features": {
            "ENABLE_YT_IN_CHAT": settings.ENABLE_YT_IN_CHAT,
            "YT_SEARCH_MAX_RESULTS": settings.YT_SEARCH_MAX_RESULTS,
            "YT_SEARCH_TIMEOUT": settings.YT_SEARCH_TIMEOUT,
            "ENABLE_CANON": settings.ENABLE_CANON,
            "MEMORY_SUMMARY_BUDGET_TOKENS": settings.MEMORY_SUMMARY_BUDGET_TOKENS,
        },
        "registry_size": len(MODEL_REGISTRY),
    }


@app.get("/api/config/models")
def list_models():
    return {"keys": sorted(MODEL_REGISTRY.keys())}


# ───────────────────── Utility endpoints ───────────────────
@app.get("/")
def read_root():
    return {"message": "Crypto Trading LLM API is running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# ──────────────── Superuser creation on startup ───────────
async def create_superuser():
    """Create superuser if configured and doesn't exist"""
    if not settings.SUPERUSER_EMAIL or not settings.SUPERUSER_PASSWORD:
        logger.info("⚠️ No SUPERUSER_EMAIL/SUPERUSER_PASSWORD configured - skipping superuser creation")
        return
    
    from app.memory.db import SessionLocal
    from app.memory.models import User
    from passlib.hash import bcrypt
    from datetime import datetime
    
    db = SessionLocal()
    try:
        # Check if superuser exists
        existing = db.query(User).filter(User.email == settings.SUPERUSER_EMAIL).first()
        if existing:
            logger.info(f"✅ Superuser already exists: {settings.SUPERUSER_EMAIL}")
            return
        
        # Create superuser
        superuser = User(
            email=settings.SUPERUSER_EMAIL,
            username=settings.SUPERUSER_USERNAME,
            password_hash=bcrypt.hash(settings.SUPERUSER_PASSWORD),
            status="active",
            is_superuser=True,
            is_active=True,
            trial_ends_at=None,  # Superuser doesn't need trial
            subscription_ends_at=None
        )
        
        db.add(superuser)
        db.commit()
        
        logger.info(f"✅ Superuser created: {settings.SUPERUSER_EMAIL}")
        logger.info(f"   Username: {settings.SUPERUSER_USERNAME}")
        logger.info(f"   Password: *** (from SUPERUSER_PASSWORD env var)")
        
    except Exception as e:
        logger.error(f"❌ Error creating superuser: {e}")
        db.rollback()
    finally:
        db.close()
