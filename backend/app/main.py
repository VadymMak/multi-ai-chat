from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# ✅ Load environment variables
load_dotenv()

# ✅ Create FastAPI instance with metadata
app = FastAPI(
    title="Crypto Trading LLM API",
    description="API for crypto market trading with LLM, YouTube data, file uploads, and sentiment analytics",
    version="1.0.0"
)

# ✅ CORS Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🔐 Replace with frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Routers
from app.routers import ask, ask_ai_to_ai, ask_ai_to_ai_turn, youtube
from app.routers.upload_file import router as upload_router  # ✅ NEW

app.include_router(ask.router)
app.include_router(ask_ai_to_ai.router)
app.include_router(ask_ai_to_ai_turn.router)
app.include_router(youtube.router, prefix="/api")
app.include_router(upload_router, prefix="/api")  # ✅ NEW

# ✅ Root and health endpoints
@app.get("/")
def read_root():
    return {"message": "Crypto Trading LLM API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
