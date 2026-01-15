# app/routers/ask_ai_to_ai.py
# REFACTORED v2: Intent-based routing
# - SIMPLE: Single model response (fast, cheap)
# - DEBATE: Multi-model discussion (thorough)
# - BUILD: Project Builder / Code generation
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from typing import Literal, Optional, Union, List, Dict, Any, Tuple, Iterable
from uuid import uuid4
import asyncio
import re
import json

from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.memory.db import get_db
from app.memory.manager import MemoryManager
from app.memory.models import Project, User
from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude
from app.services.youtube_http import perform_youtube_search
from app.services.web_search_service import perform_google_search
from app.prompts.prompt_builder import build_full_prompt
from app.config.settings import settings
from app.deps import get_current_active_user
from app.utils.api_key_resolver import get_openai_key, get_anthropic_key

# ✅ Import unified build_smart_context
from app.services.smart_context import build_smart_context

from app.config.debate_prompts import get_round_config, get_mode_info

router = APIRouter(tags=["Chat"])

# ---- Tunables ----
HISTORY_MAX_TOKENS = getattr(settings, "HISTORY_MAX_TOKENS", 1800)
HISTORY_FETCH_LIMIT = getattr(settings, "HISTORY_FETCH_LIMIT", 200)
CANON_TOPK = int(getattr(settings, "CANON_TOPK", 6))
ENABLE_CANON = bool(getattr(settings, "ENABLE_CANON", False))


# ============================================================
# 🎯 INTENT CLASSIFICATION
# ============================================================

# Keywords for each intent type
SIMPLE_KEYWORDS = [
    # Questions
    "show me", "what is", "what are", "list", "explain", "describe",
    "how does", "how do", "where is", "tell me", "summarize", "summary",
    "find", "search", "look for", "get", "fetch", "retrieve",
    # Information requests
    "which", "when", "who", "why", "can you", "could you",
    "help me understand", "what's the", "give me", "i need to know",
    # Structure/navigation
    "structure", "folder", "file", "directory", "path", "location",
    "show", "display", "view", "see", "check", "look at",
]

BUILD_KEYWORDS = [
    # Creation
    "create", "generate", "build", "make", "implement", "develop",
    "write code", "new project", "scaffold", "setup", "initialize",
    # Code generation
    "add feature", "add function", "add component", "add service",
    "create file", "create class", "create module", "create api",
    # Project building
    "project structure", "file structure", "generate structure",
    "build project", "create project", "new application",
    "implement feature", "code for", "write a",
]

DEBATE_KEYWORDS = [
    # Comparison/analysis
    "compare", "versus", "vs", "difference between", "pros and cons",
    "advantages", "disadvantages", "trade-offs", "tradeoffs",
    # Complex decisions
    "should i", "best approach", "best practice", "recommend",
    "which is better", "what's the best", "optimal", "strategy",
    # Discussion topics
    "debate", "discuss", "analyze", "evaluate", "assess",
    "opinion on", "thoughts on", "perspective on",
    # Architecture decisions
    "architecture", "design pattern", "approach for",
]


def classify_intent(topic: str, role_id: int = 1) -> Literal["simple", "debate", "build"]:
    """
    Classify user intent based on message content.
    
    Returns:
    - "simple": Quick single-model response (questions, lookups, explanations)
    - "debate": Multi-model discussion (comparisons, decisions, complex topics)
    - "build": Code/project generation (create, generate, implement)
    
    Priority: BUILD > DEBATE > SIMPLE
    """
    
    topic_lower = topic.lower().strip()
    
    # Role-based override: Project Builder role always builds
    if role_id == 9:
        print(f"🎯 [Intent] Role 9 (Project Builder) → BUILD")
        return "build"
    
    # Check for BUILD keywords first (highest priority)
    build_score = sum(1 for kw in BUILD_KEYWORDS if kw in topic_lower)
    
    # Check for DEBATE keywords
    debate_score = sum(1 for kw in DEBATE_KEYWORDS if kw in topic_lower)
    
    # Check for SIMPLE keywords
    simple_score = sum(1 for kw in SIMPLE_KEYWORDS if kw in topic_lower)
    
    # Additional heuristics
    
    # Short questions are usually simple
    word_count = len(topic.split())
    if word_count <= 10 and simple_score > 0 and build_score == 0:
        print(f"🎯 [Intent] Short question ({word_count} words) + simple keywords → SIMPLE")
        return "simple"
    
    # Questions starting with interrogatives are usually simple
    interrogatives = ["what", "where", "when", "which", "who", "how", "why", "can", "could", "is", "are", "do", "does"]
    first_word = topic_lower.split()[0] if topic_lower else ""
    if first_word in interrogatives and build_score == 0 and debate_score == 0:
        print(f"🎯 [Intent] Interrogative '{first_word}' + no build/debate → SIMPLE")
        return "simple"
    
    # Score-based decision
    print(f"🎯 [Intent] Scores: build={build_score}, debate={debate_score}, simple={simple_score}")
    
    if build_score > 0 and build_score >= debate_score:
        print(f"🎯 [Intent] BUILD (score={build_score})")
        return "build"
    
    if debate_score > 0 and debate_score > simple_score:
        print(f"🎯 [Intent] DEBATE (score={debate_score})")
        return "debate"
    
    # Default to simple for most queries
    print(f"🎯 [Intent] SIMPLE (default, score={simple_score})")
    return "simple"


# ============================================================
# PYDANTIC MODELS
# ============================================================

class AiToAiRequest(BaseModel):
    topic: str
    starter: Literal["openai", "anthropic"] = "openai"
    role: Union[int, str] = 1
    project_id: Union[int, str]
    chat_session_id: Optional[str] = None

    # ✅ NEW: Intent can be specified by frontend or auto-detected
    intent: Optional[Literal["simple", "debate", "build"]] = None
    
    # Mode selection (legacy, now derived from intent)
    mode: Literal["debate", "project-builder"] = "debate"

    # Rendering options
    output_mode: Optional[Literal["code", "doc", "plain"]] = None
    language: Optional[str] = None
    presentation: Optional[Literal["default", "poem_plain", "poem_code"]] = "default"
    
    # Search toggles
    web_search: bool = False
    youtube_search: bool = False

    @field_validator("role", mode="before")
    @classmethod
    def convert_role(cls, v):
        try:
            v2 = int(v)
            if v2 <= 0:
                raise ValueError
            return v2
        except Exception:
            raise ValueError("role must be a positive integer")

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id(cls, v):
        s = "0" if v in (None, "", "default") else str(v).strip()
        if not s.isdigit() or int(s) <= 0:
            raise ValueError("project_id must be a positive integer")
        return s


# ============================================================
# HELPER FUNCTIONS
# ============================================================

_LANG_HINTS = {
    "c#": "csharp", "csharp": "csharp", "python": "python", "javascript": "javascript",
    "typescript": "typescript", "java": "java", "php": "php", "ruby": "ruby",
    "rust": "rust", "kotlin": "kotlin", "swift": "swift", "sql": "sql",
    "bash": "bash", "powershell": "powershell", "go": "go",
}
_CODE_FENCE_RE = re.compile(r"```([a-zA-Z0-9#.+-]*)\n([\s\S]*?)```", re.MULTILINE)
_LIST_LINE_RE = re.compile(r"^\s*(?:[-*•·]|(?:\d+)[.)])\s+\S+", re.MULTILINE)


def _get_or_create_session_id(memory: MemoryManager, role_id: int, project_id: str, provided: Optional[str]) -> str:
    """Use provided id; else reuse last or mint a new uuid4."""
    if provided and provided.strip():
        return provided.strip()
    try:
        if hasattr(memory, "get_or_create_chat_session_id"):
            return memory.get_or_create_chat_session_id(role_id, project_id)
    except Exception as e:
        print(f"[get_or_create_chat_session_id error] {e}")
    last = memory.get_last_session(role_id=role_id, project_id=project_id)
    if last and (last.get("chat_session_id") or "").strip():
        return str(last["chat_session_id"]).strip()
    return str(uuid4())


async def claude_with_retry(
    messages: List[Dict[str, str]], 
    system: Optional[str] = None,
    retries: int = 2,
    api_key: Optional[str] = None,
    model: str = "claude-sonnet-4-20250514"
) -> str:
    """Claude wrapper with simple retries/backoff"""
    filtered_messages = [m for m in messages if m.get("role") != "system"]
    
    if system is None:
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
                break
    
    last = ""
    for attempt in range(retries + 1):
        try:
            ans = await run_in_threadpool(
                ask_claude, 
                filtered_messages, 
                system=system,
                model=model,
                api_key=api_key
            )
            last = ans or ""
            if ans and "[Claude Error]" not in ans and "overloaded" not in ans.lower():
                return ans
        except Exception as e:
            last = f"[Claude Exception] {e}"
        await asyncio.sleep(1.5 + attempt)
    return last or "[Claude Retry Failed]"


# ============================================================
# 🚀 SIMPLE MODE HANDLER (Single Model - Fast & Cheap)
# ============================================================

async def _handle_simple_mode(
    data: AiToAiRequest,
    memory: MemoryManager,
    db: Session,
    smart_context: str,
    role_id: int,
    project_id: str,
    chat_session_id: str,
    openai_key: str,
    anthropic_key: str,
) -> JSONResponse:
    """
    SIMPLE mode: Single model response for questions, lookups, explanations.
    
    - Fast: 1 API call instead of 3
    - Cheap: ~3x less tokens
    - Perfect for: "show me X", "what is Y", "explain Z"
    """
    
    print(f"💬 [SIMPLE] Processing with single model...")
    
    # Build prompt with context
    system_prompt = """You are a helpful AI assistant. Provide clear, concise answers.

When answering:
- Be direct and to the point
- Use markdown formatting for readability
- Include code examples when relevant
- Reference specific files/functions from the context when applicable

You have access to project context - use it to give accurate, specific answers."""

    user_prompt = f"""Project Context:
{smart_context}

User Question:
{data.topic}

Provide a helpful, focused answer:"""

    # Choose model based on starter preference
    try:
        if data.starter == "anthropic":
            response = await claude_with_retry(
                messages=[{"role": "user", "content": user_prompt}],
                system=system_prompt,
                api_key=anthropic_key
            )
            model_used = "anthropic"
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            response = await run_in_threadpool(ask_openai, messages, api_key=openai_key)
            model_used = "openai"
            
    except Exception as e:
        print(f"❌ [SIMPLE] Model error: {e}")
        raise HTTPException(status_code=502, detail=f"Model failed: {e}")
    
    response = response.strip()
    
    # Store in memory
    memory.store_chat_message(project_id, role_id, chat_session_id, "user", data.topic, is_ai_to_ai=False)
    memory.store_chat_message(project_id, role_id, chat_session_id, model_used, response, is_ai_to_ai=False)
    
    print(f"✅ [SIMPLE] Response: {len(response)} chars from {model_used}")
    
    return JSONResponse(content={
        "mode": "simple",
        "intent": "simple",
        "messages": [
            {"sender": model_used, "answer": response}
        ],
        "summary": response,  # For compatibility with frontend
        "chat_session_id": chat_session_id,
        "model_used": model_used,
    })


# ============================================================
# 🔄 DEBATE MODE HANDLER (Multi-Model Discussion)
# ============================================================

async def _handle_debate_mode(
    data: AiToAiRequest,
    memory: MemoryManager,
    db: Session,
    smart_context: str,
    role_id: int,
    project_id: str,
    chat_session_id: str,
    openai_key: str,
    anthropic_key: str,
    project: Optional[Project] = None,
) -> JSONResponse:
    """
    DEBATE mode: Multi-model discussion for complex topics.
    
    Flow:
    1. Starter model provides initial answer
    2. Claude reviews and critiques
    3. Final synthesis combines both perspectives
    
    Perfect for: comparisons, architecture decisions, best practices
    """
    
    print(f"🔄 [DEBATE] Starting multi-model discussion...")
    
    # System prompt for debate
    base_system = """You are a thoughtful assistant participating in a multi-model discussion.
Provide well-reasoned, balanced perspectives. Consider multiple angles."""

    # ---- Round 1: Starter model ----
    print(f"🔄 [DEBATE] Round 1: {data.starter} generating initial response...")
    
    starter_prompt = f"""Context:
{smart_context}

Topic for discussion:
{data.topic}

Provide a thorough, well-structured response:"""

    try:
        if data.starter == "openai":
            first_reply = await run_in_threadpool(
                ask_openai,
                [
                    {"role": "system", "content": base_system},
                    {"role": "user", "content": starter_prompt}
                ],
                api_key=openai_key
            )
            starter_sender = "openai"
        else:
            first_reply = await claude_with_retry(
                [{"role": "user", "content": starter_prompt}],
                system=base_system,
                api_key=anthropic_key
            )
            starter_sender = "anthropic"
    except Exception as e:
        print(f"❌ [DEBATE] Starter error: {e}")
        raise HTTPException(status_code=502, detail="Starter model failed")
    
    first_reply = first_reply.strip()
    memory.store_chat_message(project_id, role_id, chat_session_id, starter_sender, first_reply, is_ai_to_ai=True)
    print(f"✅ [DEBATE] Round 1 complete: {len(first_reply)} chars")

    # ---- Round 2: Claude review ----
    print(f"🔄 [DEBATE] Round 2: Claude reviewing...")
    
    review_prompt = f"""Topic: {data.topic}

Initial Response from {starter_sender}:
{first_reply}

Please review this response:
1. What points are well-made?
2. What's missing or could be improved?
3. Any alternative perspectives to consider?

Be constructive and thorough:"""

    try:
        claude_review = await claude_with_retry(
            [{"role": "user", "content": review_prompt}],
            system="You are a thoughtful reviewer. Provide constructive feedback and additional perspectives.",
            api_key=anthropic_key
        )
    except Exception as e:
        print(f"❌ [DEBATE] Review error: {e}")
        raise HTTPException(status_code=502, detail="Review model failed")
    
    claude_review = claude_review.strip()
    memory.store_chat_message(project_id, role_id, chat_session_id, "anthropic", claude_review, is_ai_to_ai=True)
    print(f"✅ [DEBATE] Round 2 complete: {len(claude_review)} chars")

    # ---- Round 3: Final synthesis ----
    print(f"🔄 [DEBATE] Final: Synthesizing...")
    
    synthesis_prompt = f"""Topic: {data.topic}

Initial Response:
{first_reply}

Review & Additional Perspectives:
{claude_review}

Create a final, comprehensive response that:
1. Incorporates the best points from both
2. Addresses any gaps identified
3. Provides a clear, actionable conclusion

Format with clear markdown headings and structure:"""

    try:
        final_reply = await claude_with_retry(
            [{"role": "user", "content": synthesis_prompt}],
            system="You are synthesizing multiple perspectives into a comprehensive final answer.",
            model="claude-sonnet-4-5-20250929",  # Use best model for synthesis
            api_key=anthropic_key
        )
    except Exception as e:
        print(f"❌ [DEBATE] Synthesis error: {e}")
        raise HTTPException(status_code=502, detail="Synthesis failed")
    
    final_reply = final_reply.strip()
    memory.store_chat_message(project_id, role_id, chat_session_id, "final", final_reply, is_ai_to_ai=True)
    print(f"✅ [DEBATE] Complete!")

    return JSONResponse(content={
        "mode": "debate",
        "intent": "debate",
        "messages": [
            {"sender": starter_sender, "answer": first_reply, "role": "initial"},
            {"sender": "anthropic", "answer": claude_review, "role": "review"},
        ],
        "summary": final_reply,
        "chat_session_id": chat_session_id,
    })


# ============================================================
# 🏗️ BUILD MODE HANDLER (Project/Code Generation)
# ============================================================

async def _handle_build_mode(
    data: AiToAiRequest,
    memory: MemoryManager,
    db: Session,
    smart_context: str,
    role_id: int,
    project_id: str,
    chat_session_id: str,
    openai_key: str,
    anthropic_key: str,
    user_id: int,
) -> JSONResponse:
    """
    BUILD mode: Project structure and code generation.
    
    Flow:
    1. GPT-4o generates initial structure/code
    2. Claude Sonnet reviews for issues
    3. Claude Sonnet 4.5 creates final optimized version
    
    Perfect for: "create X", "generate Y", "build Z"
    """
    
    print(f"🏗️ [BUILD] Starting code generation pipeline...")
    
    # Get round configurations
    round1_config = get_round_config(1, "project-builder")
    round2_config = get_round_config(2, "project-builder")
    final_config = get_round_config("final", "project-builder")

    # ---- Round 1: Generate Structure (GPT-4o) ----
    print(f"🏗️ [BUILD] Round 1: GPT-4o generating structure...")
    
    generator_prompt = round1_config["prompt_template"].format(topic=data.topic)
    
    # Add smart context
    full_prompt = f"""Project Context:
{smart_context}

{generator_prompt}"""
    
    try:
        first_reply = await run_in_threadpool(
            ask_openai,
            [
                {"role": "system", "content": "You are an expert software architect. Generate clean, well-organized project structures."},
                {"role": "user", "content": full_prompt}
            ],
            api_key=openai_key
        )
    except Exception as e:
        print(f"❌ [BUILD] Generator error: {e}")
        raise HTTPException(status_code=502, detail="Project structure generation failed")
    
    first_reply = first_reply.strip()
    memory.store_chat_message(project_id, role_id, chat_session_id, "openai", first_reply, is_ai_to_ai=True)
    print(f"✅ [BUILD] Round 1 complete: {len(first_reply)} chars")

    # ---- Round 2: Review & Enhance (Claude Sonnet) ----
    print(f"🏗️ [BUILD] Round 2: Claude reviewing...")
    
    reviewer_prompt = round2_config["prompt_template"].format(previous_solution=first_reply)
    
    try:
        claude_review = await claude_with_retry(
            [{"role": "user", "content": reviewer_prompt}],
            system="You are a thorough code reviewer. Identify issues and suggest improvements.",
            api_key=anthropic_key
        )
    except Exception as e:
        print(f"❌ [BUILD] Reviewer error: {e}")
        raise HTTPException(status_code=502, detail="Project structure review failed")
    
    claude_review = claude_review.strip()
    memory.store_chat_message(project_id, role_id, chat_session_id, "anthropic", claude_review, is_ai_to_ai=True)
    print(f"✅ [BUILD] Round 2 complete: {len(claude_review)} chars")

    # ---- Final: Merge (Claude Sonnet 4.5) ----
    print(f"🏗️ [BUILD] Final: Claude Sonnet 4.5 creating final structure...")
    
    merger_prompt = final_config["prompt_template"].format(
        topic=data.topic,
        round1=first_reply,
        round2=claude_review
    )

    try:
        final_reply = await claude_with_retry(
            [{"role": "user", "content": merger_prompt}],
            system="You are a project architecture expert. Create the best possible final structure.",
            model="claude-sonnet-4-5-20250929",
            api_key=anthropic_key
        )
    except Exception as e:
        print(f"❌ [BUILD] Merger error: {e}")
        raise HTTPException(status_code=502, detail="Final structure merge failed")
    
    final_reply = final_reply.strip()
    memory.store_chat_message(project_id, role_id, chat_session_id, "final", final_reply, is_ai_to_ai=True)
    print(f"✅ [BUILD] Project Builder completed!")

    # ---- Auto-save structure if detected ----
    generation_started = False
    files_count = 0
    
    try:
        if "===FINAL_STRUCTURE_END===" in final_reply or "```" in final_reply:
            print(f"📦 [BUILD] Detected project structure, auto-saving...")
            
            proj_id_int = int(project_id) if str(project_id).isdigit() else None
            if proj_id_int:
                from sqlalchemy import text
                from app.services.project_structure_parser import parse_project_structure, analyze_basic_dependencies
                from datetime import datetime
                
                project_obj = db.query(Project).filter(Project.id == proj_id_int).first()
                
                if project_obj:
                    project_obj.project_structure = final_reply
                    db.commit()
                    print(f"✅ [BUILD] Saved structure to project")
                    
                    try:
                        file_specs = parse_project_structure(final_reply)
                        
                        if file_specs:
                            db.execute(text("DELETE FROM file_specifications WHERE project_id = :pid"), {"pid": proj_id_int})
                            db.execute(text("DELETE FROM file_dependencies WHERE project_id = :pid"), {"pid": proj_id_int})
                            db.commit()
                            
                            seen_paths = set()
                            for spec in file_specs:
                                if not spec.file_path or len(spec.file_path) < 3:
                                    continue
                                if spec.file_path in seen_paths:
                                    continue
                                if not any(c.isalnum() for c in spec.file_path):
                                    continue
                                seen_paths.add(spec.file_path)
                                
                                db.execute(text("""
                                    INSERT INTO file_specifications 
                                    (project_id, file_path, file_number, description, language, status, created_at, updated_at)
                                    VALUES (:project_id, :file_path, :file_number, :description, :language, 'pending', :now, :now)
                                """), {
                                    "project_id": proj_id_int,
                                    "file_path": spec.file_path,
                                    "file_number": spec.file_number,
                                    "description": spec.description,
                                    "language": spec.language,
                                    "now": datetime.utcnow()
                                })
                            db.commit()
                            
                            dependencies = analyze_basic_dependencies(file_specs)
                            for source_file, targets in dependencies.items():
                                for target_file in targets:
                                    db.execute(text("""
                                        INSERT INTO file_dependencies (project_id, source_file, target_file, dependency_type, created_at)
                                        VALUES (:project_id, :source_file, :target_file, 'import', :now)
                                    """), {
                                        "project_id": proj_id_int,
                                        "source_file": source_file,
                                        "target_file": target_file,
                                        "now": datetime.utcnow()
                                    })
                            db.commit()
                            
                            files_count = len(file_specs)
                            print(f"✅ [BUILD] Saved {files_count} file specs")
                            
                            # Start background generation
                            try:
                                from app.services.dependency_graph import get_generation_order_from_db
                                from app.routers.project_builder import generate_files_background
                                import asyncio
                                
                                generation_order = get_generation_order_from_db(proj_id_int, db)
                                
                                if generation_order:
                                    asyncio.create_task(
                                        generate_files_background(
                                            project_id=proj_id_int,
                                            generation_order=generation_order,
                                            user_id=user_id,
                                            use_smart_context=True,
                                            anthropic_key=anthropic_key,
                                        )
                                    )
                                    generation_started = True
                                    print(f"🚀 [BUILD] Started background generation for {len(generation_order)} files")
                            except Exception as gen_err:
                                print(f"⚠️ [BUILD] Auto-generation failed: {gen_err}")
                                
                    except Exception as parse_err:
                        print(f"⚠️ [BUILD] Parse failed: {parse_err}")
                        
    except Exception as auto_save_err:
        print(f"⚠️ [BUILD] Auto-save failed: {auto_save_err}")

    return JSONResponse(content={
        "mode": "project-builder",
        "intent": "build",
        "messages": [
            {"sender": "openai", "answer": first_reply, "role": "generator"},
            {"sender": "anthropic", "answer": claude_review, "role": "reviewer"},
        ],
        "summary": final_reply,
        "chat_session_id": chat_session_id,
        "generation_started": generation_started,
        "files_count": files_count,
    })


# ============================================================
# 🎯 MAIN ROUTE
# ============================================================

@router.post("/ask-ai-to-ai")
async def ask_ai_to_ai_route(
    data: AiToAiRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Smart AI Chat with Intent-Based Routing.
    
    Intents:
    - SIMPLE: Single model for questions/lookups (fast, cheap)
    - DEBATE: Multi-model for complex discussions (thorough)
    - BUILD: Code/project generation (comprehensive)
    
    Intent can be:
    1. Specified by frontend via `intent` parameter
    2. Auto-detected from message content
    """
    
    memory = MemoryManager(db)
    role_id = data.role
    project_id = data.project_id
    chat_session_id = _get_or_create_session_id(memory, role_id, project_id, data.chat_session_id)

    # Get user API keys
    openai_key = get_openai_key(current_user, db, required=True)
    anthropic_key = get_anthropic_key(current_user, db, required=True)

    # ============================================================
    # 🎯 INTENT DETECTION
    # ============================================================
    
    if data.intent:
        # Frontend specified intent
        intent = data.intent
        print(f"🎯 [Route] Frontend specified intent: {intent}")
    else:
        # Auto-detect intent from message
        intent = classify_intent(data.topic, role_id)
        print(f"🎯 [Route] Auto-detected intent: {intent}")
    
    # Legacy mode override for backwards compatibility
    if data.mode == "project-builder" or role_id == 9:
        intent = "build"
        print(f"🎯 [Route] Override to BUILD (legacy mode or role_id=9)")

    print(f"⚙️ [{intent.upper()}] topic='{data.topic[:80]}...' | role={role_id} | project={project_id}")

    # ============================================================
    # BUILD SMART CONTEXT
    # ============================================================
    
    try:
        proj_id_int = int(project_id) if str(project_id).isdigit() else None
        project: Optional[Project] = db.query(Project).filter_by(id=proj_id_int).first() if proj_id_int else None
        if project:
            db.refresh(project)
    except Exception as e:
        print(f"[Project lookup error] {e}")
        project = None
    
    print("🚀 Building Smart Context...")
    try:
        smart_context = await build_smart_context(
            project_id=proj_id_int or 0,
            role_id=role_id,
            query=data.topic,
            session_id=chat_session_id,
            db=db,
            memory=memory
        )
        print(f"✅ Smart context ready (~{len(smart_context) // 4} tokens)")
    except Exception as e:
        print(f"⚠️ Smart context failed: {e}")
        smart_context = "No project context available."

    # Store user message
    memory.store_chat_message(project_id, role_id, chat_session_id, "user", data.topic, is_ai_to_ai=(intent != "simple"))

    # ============================================================
    # ROUTE TO APPROPRIATE HANDLER
    # ============================================================
    
    if intent == "simple":
        return await _handle_simple_mode(
            data=data,
            memory=memory,
            db=db,
            smart_context=smart_context,
            role_id=role_id,
            project_id=project_id,
            chat_session_id=chat_session_id,
            openai_key=openai_key,
            anthropic_key=anthropic_key,
        )
    
    elif intent == "debate":
        return await _handle_debate_mode(
            data=data,
            memory=memory,
            db=db,
            smart_context=smart_context,
            role_id=role_id,
            project_id=project_id,
            chat_session_id=chat_session_id,
            openai_key=openai_key,
            anthropic_key=anthropic_key,
            project=project,
        )
    
    else:  # intent == "build"
        return await _handle_build_mode(
            data=data,
            memory=memory,
            db=db,
            smart_context=smart_context,
            role_id=role_id,
            project_id=project_id,
            chat_session_id=chat_session_id,
            openai_key=openai_key,
            anthropic_key=anthropic_key,
            user_id=current_user.id,
        )