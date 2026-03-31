# Multi-AI Assistant

A full-stack AI assistant app that integrates multiple AI providers, role-based memory, file upload support, and research tools like YouTube and web search. Built as a modern training project to learn FastAPI, React, and multi-model orchestration.

---

## 🌐 Live Demo

Frontend deployed at: [https://multi-llm-chat.netlify.app](https://multi-llm-chat.netlify.app)

---

## 🗂️ Project Structure

```
multi-ai-assistant/
│
├── backend/
│   ├── app/
│   │   ├── main.py               # Entry point for FastAPI
│   │   ├── api/                  # Routes (e.g., ask, ask-ai-to-ai, upload)
│   │   ├── providers/            # Model providers: openai, claude, grok
│   │   ├── memory/               # Memory manager, token utils, memory DB
│   │   ├── services/             # YouTube, Wikipedia/web search integrations
│   │   └── utils/                # Prompt templates, helpers, logging
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── components/           # ChatArea, InputBar, Header, RoleSelector, etc.
│   │   ├── features/
│   │   │   └── aiConversation/   # Main chat view logic (AiChat.tsx)
│   │   ├── store/                # Zustand stores for chat, model, project, memory
│   │   ├── services/             # Axios API wrappers
│   │   ├── styles/               # Tailwind CSS + custom styles
│   │   └── App.tsx / index.tsx
│   └── README.md
│
├── README.md (this file)
└── .env, .gitignore, Dockerfile (coming soon)
```

---

## 🚀 Features

- ✅ OpenAI, Claude, and xAI Grok support
- ✅ Boost Mode: AI-to-AI review flow
- ✅ Role & Project-based long-term memory
- ✅ Document upload with OCR and summarization
- ✅ YouTube + Wikipedia search integration
- ✅ Prompt injection with custom variables
- ✅ Typing animation and streaming responses
- ✅ Tailwind-styled React frontend
- ✅ FastAPI backend with modular structure

---

## 🛠 Getting Started (Backend)

```bash
# Navigate to backend directory
cd backend

# Create and activate virtual environment
python -m venv llm_env
source llm_env/bin/activate  # or .\llm_env\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn app.main:app --reload
```

> 📌 Configure `.env` file with your OpenAI, Anthropic, and YouTube API keys.

---

## 💬 Getting Started (Frontend)

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

> Tailwind CSS is configured manually and loaded via `src/styles/tailwind.css`.

---

## 📦 Deployment

- Frontend: **Netlify** (`https://multi-llm-chat.netlify.app`)
- Backend: _(TBD: Planning for Docker + Railway/Render/EC2)_

---

## 🧪 Tech Stack

- **Frontend:** React + TypeScript + Zustand + Axios + Tailwind CSS
- **Backend:** FastAPI + SQLite (local), PostgreSQL-ready
- **AI Providers:** OpenAI, Claude (Anthropic), Grok (xAI)
- **File Support:** PDF, DOCX, CSV, TXT, Markdown, Images (with OCR)

---

## 📚 Learning Focus

This is a training project to learn:

- Modular Python with FastAPI
- Multi-model orchestration
- Context-aware memory storage
- Full-stack AI assistant deployment
- Prompt engineering and UX for LLMs

---

## 🧠 Want to Extend?

Planned / optional features:

- [ ] Authentication with Supabase/Auth.js
- [ ] Persistent chat sessions with DB
- [ ] Model usage logging and analytics
- [ ] Admin dashboard and prompt metrics
- [ ] Export summaries as Markdown or PDF

---

## 📄 License

MIT – Use freely and fork to learn or build your own AI agent!
# auto-reindex test
