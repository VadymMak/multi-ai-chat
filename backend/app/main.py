from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware  # ✅ Added for CORS
from dotenv import load_dotenv
from app.routers import ask, ask_ai_to_ai, ask_ai_to_ai_turn
from app.services.youtube_sevice import perform_youtube_search

load_dotenv()

app = FastAPI(
    title="Crypto Trading LLM API",
    description="API for crypto market trading with LLM, YouTube data, and sentiment analytics",
    version="1.0.0"
)

# ✅ CORS Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict this to Netlify domain in production
    allow_credentials=True,
    allow_methods=["*"],  # Must include OPTIONS for preflight
    allow_headers=["*"],
)

# ✅ Routers
app.include_router(ask.router)
app.include_router(ask_ai_to_ai.router)
app.include_router(ask_ai_to_ai_turn.router)

@app.get("/")
def read_root():
    return {"message": "Crypto Trading LLM API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
