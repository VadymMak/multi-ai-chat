# File: backend/app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# ✅ Load environment variables from .env
load_dotenv()

# ✅ Create FastAPI app with API metadata
app = FastAPI(
    title="Crypto Trading LLM API",
    description="API for crypto market trading with LLM, YouTube data, file uploads, and sentiment analytics",
    version="1.0.0"
)

# ✅ Configure CORS (Cross-Origin Resource Sharing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # 🔒 Use specific frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Import routers
from app.routers import (
    ask,
    ask_ai_to_ai,
    ask_ai_to_ai_turn,
    youtube,
    chat,
    projects,
    audit  # ✅ NEW: Audit router
)
from app.routers.upload_file import router as upload_router
from app.routers.prompt_template import router as prompt_template_router

# ✅ Register routers (all use "/api" prefix)
app.include_router(ask.router, prefix="/api")
app.include_router(ask_ai_to_ai.router, prefix="/api")
app.include_router(ask_ai_to_ai_turn.router, prefix="/api")
app.include_router(youtube.router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(prompt_template_router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(audit.router, prefix="/api")  # ✅ REGISTERED HERE

# ✅ Root endpoint
@app.get("/")
def read_root():
    return {"message": "Crypto Trading LLM API is running"}

# ✅ Health check
@app.get("/health")
async def health_check():
    return {"status": "healthy"}
