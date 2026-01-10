backend/
├── app/
│ ├── **init**.py
│ ├── main.py # Entry point for FastAPI app
│ ├── api/ # Route definitions
│ │ ├── **init**.py
│ │ ├── ask.py # /ask endpoint (OpenAI, Claude, etc.)
│ │ ├── ask_ai_to_ai.py # /ask-ai-to-ai logic
│ │ └── youtube.py # /youtube or YouTube-enhanced route
│ ├── services/ # Core logic for providers
│ │ ├── **init**.py
│ │ ├── openai_service.py
│ │ ├── anthropic_service.py
│ │ ├── grok_service.py # (optional future use)
│ │ └── youtube_service.py
│ ├── memory/ # Memory management (SQLite, PostgreSQL)
│ │ ├── **init**.py
│ │ ├── manager.py # MemoryManager class
│ │ └── models.py # DB schema (if using SQLAlchemy or Pydantic)
│ ├── config/ # App configuration and environment
│ │ ├── **init**.py
│ │ └── settings.py # Load env, constants, secrets
│ ├── utils/ # Common helpers
│ │ ├── **init**.py
│ │ ├── retry.py # Retry decorators, backoff logic
│ │ └── token_utils.py # tiktoken utilities for trimming context
│ └── schemas/ # Pydantic models for requests/responses
│ ├── **init**.py
│ ├── chat.py
│ └── youtube.py
├── .env
├── Dockerfile
├── requirements.txt
├── runtime.txt
└── README.md
