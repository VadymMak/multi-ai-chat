from fastapi import FastAPI
from dotenv import load_dotenv
from app.routers import ask, ask_ai_to_ai, ask_ai_to_ai_turn
from app.services.youtube_sevice import perform_youtube_search

load_dotenv()

app = FastAPI(
    title="Crypto Trading LLM API",
    description="API for crypto market trading with LLM, YouTube data, and sentiment analytics",
    version="1.0.0"
)

app.include_router(ask.router)
app.include_router(ask_ai_to_ai.router)
app.include_router(ask_ai_to_ai_turn.router)

@app.get("/")
def read_root():
    return {"message": "Crypto Trading LLM API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}