# 📦 Backend Structure – Multi-AI Assistant

This backend is built with **FastAPI** and follows a modular architecture to keep providers, routes, memory, and services separated.

---

## 🗂️ Folder Structure Overview

```
backend/
└── app/
    ├── main.py                # ✅ FastAPI app entry point
    ├── deps.py                # Global dependencies (e.g., DB session)
    ├── routers/               # All API routes organized by feature
    │   ├── ask.py
    │   ├── ask_ai_to_ai.py
    │   ├── ask_ai_to_ai_turn.py
    │   ├── memory.py
    │   ├── upload_file.py
    │   ├── youtube.py
    │   └── prompt_template.py         # ✅ NEW: Prompt template management
    ├── providers/             # AI model wrappers
    │   ├── claude_provider.py
    │   ├── openai_provider.py
    │   └── youtube_provide.py
    ├── memory/                # Memory system logic
    │   ├── db.py
    │   ├── manager.py
    │   ├── models.py
    │   ├── utils.py
    │   └── schemas/           # ✅ NEW: Includes prompt_template schema
    │       └── prompt_template.py
    ├── prompts/               # Prompt templates and builders
    │   ├── prompt_builder.py
    │   └── system_prompt.py
    ├── services/              # YouTube & Web search
    │   ├── web_search_service.py
    │   └── youtube_sevice.py
    └── utils/                 # Shared utils and helper functions
        └── __init__.py
```

---

## 📚 Directory Descriptions

### `main.py`

- FastAPI app starter: mounts routers, configures CORS.

### `routers/`

- API endpoints split by feature.
- `prompt_template.py`: supports full CRUD on prompt templates.

### `providers/`

- Wraps calls to external AI providers like OpenAI, Claude, Grok.
- Keeps model logic modular and replaceable.

### `memory/`

- Contains all long-term memory logic.
- `manager.py`: Stores & retrieves summaries.
- `models.py`: includes PromptTemplate, Role, Project.
- `schemas/`: contains Pydantic models like PromptTemplateCreate, PromptTemplateRead.

### `prompts/`

- `prompt_builder.py`: Dynamically builds prompts.
- `system_prompt.py`: Stores default role-based system prompts.

### `services/`

- External tools (YouTube, Wikipedia).
- Used in Boost Mode or file summarization.

### `utils/`

- Optional helper files. May include logging, enums, etc.

---

## ✅ FastAPI Design Tips

- Split routes by domain (e.g., ask, upload).
- Keep providers stateless.
- Use `.env` for API keys and credentials.
- Avoid logic inside `main.py` — delegate to route files.

---

## ✅ New Feature: Prompt Template API

### Endpoints

- `GET /api/prompts/{role_id}` → Get all prompts for a role
- `POST /api/prompts/` → Create new prompt template
- `PUT /api/prompts/{prompt_id}` → Update prompt by ID
- `DELETE /api/prompts/{prompt_id}` → Delete prompt by ID

### Example Request – Create Prompt Template

```json
{
  "role_id": 2,
  "name": "Default Prompt",
  "content": "You are a helpful assistant for this role.",
  "is_default": true
}
```

---

## 🧪 Coming Soon (Optional)

- `scripts/`: DB init, seed data, cleanup tasks.
- `tests/`: Unit and integration tests using `pytest`.
- `Dockerfile`: For containerization.
- `.env.template`: To share expected env variables.

---

## 🧠 Goal

This structure helps you:

- Learn **modular backend design**.
- Add new AI providers or endpoints easily.
- Separate logic clearly between models, memory, and services.

---

> Saved as `backend/README.md` to help you as a beginner Python backend developer.
