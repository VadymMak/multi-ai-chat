from dotenv import load_dotenv
import os
from pathlib import Path

env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path)
print("Loaded from:", env_path)
print("Current working dir:", os.getcwd())
print("OPENAI_API_KEY:", os.getenv("OPENAI_API_KEY"))
print("YOUTUBE_API_KEY:", os.getenv("YOUTUBE_API_KEY"))