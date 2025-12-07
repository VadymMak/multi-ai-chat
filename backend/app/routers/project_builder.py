# File: backend/app/routers/project_builder.py
"""
Project Builder API - Generate individual files from project structure

UPDATED: Uses Claude Sonnet 4.5 with Smart Context for code generation
- Dependency context (already-generated files)
- pgvector semantic search (relevant past conversations)
- Memory summaries (architecture decisions)
- Project structure (Git file tree)
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging
import json
from datetime import datetime
from collections import Counter
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.memory.db import get_db
from app.memory.models import Project
from app.memory.manager import MemoryManager
from app.services.project_structure_parser import (
    parse_project_structure, 
    analyze_basic_dependencies
)
from app.services import vector_service

from app.deps import get_current_user
from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude
from app.services.dependency_graph import get_generation_order_from_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/project-builder", tags=["project-builder"])


# ====================================================================
# MODELS
# ====================================================================

class GenerateFileRequest(BaseModel):
    """Request to generate a single file"""
    project_structure: str
    file_number: int
    file_path: str
    project_name: Optional[str] = None
    tech_stack: Optional[str] = None


class GenerateFileResponse(BaseModel):
    """Response with generated file code"""
    file_number: int
    file_path: str
    code: str
    language: str
    tokens_used: int


class GenerateFileWithContextRequest(BaseModel):
    """Request to generate file WITH context from database"""
    project_id: int
    file_path: str
    use_smart_context: bool = True


class BatchGenerationStatus(BaseModel):
    """Status of batch generation"""
    project_id: int
    total_files: int
    files_generated: int
    files_failed: int
    current_file: Optional[str]
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[int]
    errors: List[str]


class BatchGenerationResponse(BaseModel):
    """Response from batch generation"""
    success: bool
    project_id: int
    project_name: str
    total_files: int
    generation_order: List[str]
    message: str


# ====================================================================
# SYSTEM PROMPTS
# ====================================================================

FILE_GENERATOR_SYSTEM = """You are a senior software engineer generating production-ready code.

CRITICAL RULES:
1. Generate COMPLETE, WORKING code - not stubs or placeholders
2. Include ALL necessary imports at the top
3. Use EXACT import paths from the context files provided
4. Do NOT redefine types/interfaces that already exist in context
5. Ensure compatibility with already-generated files
6. Add helpful comments for complex logic
7. Follow best practices for the given tech stack
8. Include error handling where appropriate
9. Use TypeScript types if applicable

Return ONLY the code for this file. No explanations, no markdown code blocks.
Start directly with the code content."""


FILE_GENERATOR_SYSTEM_WITH_CONTEXT = """You are a senior software engineer generating production-ready code.

You have access to:
1. ALREADY GENERATED FILES - Use their exports, types, and interfaces
2. RELEVANT CONTEXT - Past discussions and decisions about this project
3. PROJECT STRUCTURE - The full file tree

CRITICAL RULES:
1. Import from ALREADY GENERATED files using EXACT paths shown
2. Do NOT redefine types/interfaces - import them instead
3. Match coding style from existing files
4. Ensure all imports resolve correctly
5. Generate COMPLETE working code
6. Include error handling
7. Add comments for complex logic

Return ONLY the code. No markdown fences, no explanations."""


# ====================================================================
# HELPER FUNCTIONS
# ====================================================================

def detect_language(file_path: str) -> str:
    """Detect programming language from file extension"""
    ext_map = {
        ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript",
        ".py": "python", ".json": "json",
        ".css": "css", ".scss": "scss",
        ".html": "html", ".md": "markdown",
        ".yml": "yaml", ".yaml": "yaml",
        ".sh": "bash", ".sql": "sql",
        ".vue": "vue", ".svelte": "svelte",
        ".go": "go", ".rs": "rust",
        ".java": "java", ".kt": "kotlin",
    }
    
    for ext, lang in ext_map.items():
        if file_path.endswith(ext):
            return lang
    return "text"


def clean_code_output(code: str) -> str:
    """Remove markdown code fences if present"""
    lines = code.strip().split("\n")
    
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    
    return "\n".join(lines)


def load_dependency_context(
    db: Session,
    project_id: int,
    file_path: str
) -> dict:
    """
    Load context from already-generated dependencies
    
    Returns:
        {
            "dependencies": ["types.d.ts", "utils.ts"],
            "context_files": {
                "types.d.ts": {"code": "...", "language": "typescript"}
            }
        }
    """
    
    deps = db.execute(text("""
        SELECT target_file
        FROM file_dependencies
        WHERE project_id = :project_id 
          AND source_file = :file_path
    """), {
        "project_id": project_id,
        "file_path": file_path
    }).fetchall()
    
    dependency_files = [row[0] for row in deps]
    context_files = {}
    
    for dep_file in dependency_files:
        result = db.execute(text("""
            SELECT generated_code, language
            FROM file_specifications
            WHERE project_id = :project_id 
              AND file_path = :file_path
              AND generated_code IS NOT NULL
        """), {
            "project_id": project_id,
            "file_path": dep_file
        }).fetchone()
        
        if result and result[0]:
            context_files[dep_file] = {
                "code": result[0],
                "language": result[1]
            }
    
    logger.info(f"📦 Loaded {len(context_files)} dependency files for context")
    
    return {
        "dependencies": dependency_files,
        "context_files": context_files
    }

def resolve_import_to_file(
    import_path: str,
    source_file: str,
    all_project_files: List[str]
) -> Optional[str]:
    """
    Resolve import path to actual file path in project.
    
    Examples:
        import_path: "./types" or "../utils/helpers" or "@/components/Button"
        source_file: "src/services/logger.ts"
        all_project_files: ["src/types.ts", "src/types.d.ts", ...]
        
    Returns:
        Matching file path or None if not found
    """
    import os
    
    # Skip external packages (no ./ or ../ prefix, no @ alias)
    if not import_path.startswith(('./', '../', '@/')):
        if '/' not in import_path and not import_path.startswith('.'):
            return None  # External package like "react", "lodash"
    
    # Get directory of source file
    source_dir = os.path.dirname(source_file)
    
    # Handle @ alias (common in TypeScript projects)
    if import_path.startswith('@/'):
        import_path = 'src/' + import_path[2:]
        resolved_path = import_path
    elif import_path.startswith('./'):
        resolved_path = os.path.normpath(os.path.join(source_dir, import_path[2:]))
    elif import_path.startswith('../'):
        resolved_path = os.path.normpath(os.path.join(source_dir, import_path))
    else:
        resolved_path = os.path.normpath(os.path.join(source_dir, import_path))
    
    # Normalize path separators
    resolved_path = resolved_path.replace('\\', '/')
    
    # Try to find matching file with various extensions
    extensions = ['', '.ts', '.tsx', '.js', '.jsx', '.d.ts', '/index.ts', '/index.js']
    
    for ext in extensions:
        candidate = resolved_path + ext
        candidate_normalized = candidate.lstrip('./')
        
        for project_file in all_project_files:
            project_file_normalized = project_file.lstrip('./')
            if project_file_normalized == candidate_normalized:
                return project_file
    
    return None


def update_file_dependencies_from_code(
    db: Session,
    project_id: int,
    file_path: str,
    code: str,
    language: str,
    all_project_files: List[str]
) -> int:
    """
    Parse generated code and update file_dependencies with REAL imports.
    
    Returns:
        Number of dependencies added
    """
    from app.services.file_indexer import extract_metadata
    
    # Extract real imports from generated code
    metadata = extract_metadata(code, language)
    real_imports = metadata.get("imports", [])
    
    if not real_imports:
        logger.info(f"  📦 No imports found in {file_path}")
        return 0
    
    logger.info(f"  📦 Found {len(real_imports)} imports in {file_path}: {real_imports}")
    
    # Clear old heuristic dependencies for this file
    db.execute(text("""
        DELETE FROM file_dependencies 
        WHERE project_id = :project_id AND source_file = :file_path
    """), {"project_id": project_id, "file_path": file_path})
    
    # Add REAL dependencies based on parsed imports
    deps_added = 0
    for import_path in real_imports:
        target_file = resolve_import_to_file(import_path, file_path, all_project_files)
        
        if target_file:
            db.execute(text("""
                INSERT INTO file_dependencies 
                (project_id, source_file, target_file, dependency_type, created_at)
                VALUES (:project_id, :source_file, :target_file, 'import', :now)
                ON CONFLICT DO NOTHING
            """), {
                "project_id": project_id,
                "source_file": file_path,
                "target_file": target_file,
                "now": datetime.utcnow()
            })
            deps_added += 1
            logger.info(f"    ✅ {file_path} → {target_file}")
        else:
            logger.debug(f"    ⏭️ External/unresolved: {import_path}")
    
    db.commit()
    return deps_added


# ====================================================================
# 🆕 SMART CONTEXT CODE GENERATION (NEW!)
# ====================================================================

async def generate_file_with_smart_context(
    file_path: str,
    file_number: int,
    description: str,
    language: str,
    project_id: int,
    project_name: str,
    db: Session,
    anthropic_key: str,
    role_id: int = 9,  # Project Builder role
    chat_session_id: Optional[str] = None,
) -> str:
    """
    Generate file using Claude Sonnet 4.5 with FULL Smart Context:
    
    1. Dependency context (already-generated files)
    2. pgvector semantic search (relevant past conversations)
    3. Memory summaries (architecture decisions)
    4. Project structure (Git file tree)
    
    Returns: Generated code
    """
    from starlette.concurrency import run_in_threadpool
    
    logger.info(f"🎯 [Smart Context] Generating: {file_path}")
    
    # Initialize MemoryManager
    memory = MemoryManager(db)
    
    # ========== 1. DEPENDENCY CONTEXT ==========
    logger.info(f"  📦 Loading dependency context...")
    context_data = load_dependency_context(db, project_id, file_path)
    dep_count = len(context_data["context_files"])
    logger.info(f"  ✅ Loaded {dep_count} dependency files")
    
    # ========== 2. PGVECTOR SEMANTIC SEARCH ==========
    logger.info(f"  🔍 Running semantic search...")
    relevant_context = ""
    try:
        # Search for relevant past conversations about this file/feature
        search_query = f"Generate {file_path} {description} {language}"
        relevant_context = vector_service.get_relevant_context(
            db=db,
            query=search_query,
            session_id=chat_session_id or str(project_id),
            limit=3,
            max_chars_per_message=300
        )
        if relevant_context:
            logger.info(f"  ✅ Found relevant context ({len(relevant_context)} chars)")
        else:
            logger.info(f"  ℹ️ No relevant past conversations found")
    except Exception as e:
        logger.warning(f"  ⚠️ Semantic search failed: {e}")
    
    # ========== 3. MEMORY SUMMARIES ==========
    logger.info(f"  📝 Loading memory summaries...")
    summaries = []
    try:
        summaries = memory.load_recent_summaries(
            project_id=str(project_id),
            role_id=role_id,
            limit=3
        )
        if summaries:
            logger.info(f"  ✅ Loaded {len(summaries)} summaries")
        else:
            logger.info(f"  ℹ️ No summaries found")
    except Exception as e:
        logger.warning(f"  ⚠️ Summaries loading failed: {e}")
    
    # ========== 4. PROJECT STRUCTURE ==========
    logger.info(f"  📁 Loading project structure...")
    project_structure_text = ""
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project and project.project_structure:
            try:
                structure = json.loads(project.project_structure)
                files = structure.get("files", [])
                if files:
                    file_list = [f.get("path", "") for f in files[:100]]
                    project_structure_text = "\n".join([f"  - {f}" for f in file_list])
                    if len(files) > 100:
                        project_structure_text += f"\n  ... and {len(files) - 100} more files"
                    logger.info(f"  ✅ Loaded project structure ({len(files)} files)")
            except json.JSONDecodeError:
                # Raw text structure
                project_structure_text = project.project_structure[:2000]
                logger.info(f"  ✅ Loaded raw project structure")
    except Exception as e:
        logger.warning(f"  ⚠️ Project structure loading failed: {e}")
    
    # ========== BUILD PROMPT ==========
    logger.info(f"  🔧 Building prompt...")
    
    prompt_parts = []
    
    # Header
    prompt_parts.append(f"""## FILE TO GENERATE
- Path: {file_path}
- Number: [{file_number}]
- Language: {language}
- Project: {project_name}
- Description: {description or 'No description'}
""")
    
    # Dependency context (CRITICAL!)
    if context_data["context_files"]:
        prompt_parts.append("\n## 📦 ALREADY GENERATED FILES (USE THESE!)\n")
        prompt_parts.append("Import types and functions from these files. Do NOT redefine them!\n")
        
        for dep_file, dep_data in context_data["context_files"].items():
            dep_lang = dep_data["language"] or "text"
            dep_code = dep_data["code"]
            
            # Truncate very long files but keep important parts
            if len(dep_code) > 4000:
                # Keep first 2000 and last 1000 chars
                dep_code = dep_code[:2000] + "\n\n// ... (middle truncated) ...\n\n" + dep_code[-1000:]
            
            prompt_parts.append(f"""
### File: {dep_file}
```{dep_lang}
{dep_code}
```
""")
    
    # Semantic search context
    if relevant_context:
        prompt_parts.append(f"""
## 🔍 RELEVANT PAST CONTEXT
{relevant_context}
""")
    
    # Memory summaries
    if summaries:
        summaries_text = "\n".join([f"- {s[:500]}" for s in summaries[:3]])
        prompt_parts.append(f"""
## 📝 PROJECT DECISIONS & SUMMARIES
{summaries_text}
""")
    
    # Project structure
    if project_structure_text:
        prompt_parts.append(f"""
## 📁 PROJECT STRUCTURE
{project_structure_text}
""")
    
    # Final instruction
    prompt_parts.append(f"""
## 🎯 GENERATE CODE

Generate COMPLETE, WORKING code for: {file_path}

Requirements:
1. Use imports from files shown above (exact paths!)
2. Match coding style from existing files
3. Include all necessary imports
4. Add error handling
5. Include helpful comments

Return ONLY the code, no explanations.""")
    
    user_prompt = "\n".join(prompt_parts)
    
    # Log prompt size
    prompt_tokens = memory.count_tokens(user_prompt)
    logger.info(f"  📊 Prompt size: {prompt_tokens} tokens")
    
    # ========== GENERATE WITH CLAUDE SONNET 4.5 ==========
    logger.info(f"  🚀 Generating with Claude Sonnet 4.5...")
    
    try:
        code = await run_in_threadpool(
            ask_claude,
            [{"role": "user", "content": user_prompt}],
            system=FILE_GENERATOR_SYSTEM_WITH_CONTEXT,
            model="claude-sonnet-4-5-20250929",  # ← STRONGEST MODEL!
            max_tokens=8192,
            api_key=anthropic_key
        )
        
        if code.startswith("[Claude Error]"):
            logger.error(f"  ❌ Claude error: {code}")
            raise Exception(code)
        
        code = clean_code_output(code)
        
        code_tokens = memory.count_tokens(code)
        logger.info(f"  ✅ Generated {file_path} ({len(code)} chars, {code_tokens} tokens)")
        
        return code
        
    except Exception as e:
        logger.exception(f"  ❌ Generation failed: {e}")
        raise


# ====================================================================
# ENDPOINTS
# ====================================================================

@router.post("/generate-file", response_model=GenerateFileResponse)
async def generate_file(
    request: GenerateFileRequest,
    current_user = Depends(get_current_user)
):
    """
    Generate code for a single file (simple mode, no context).
    Uses GPT-4o for fast generation.
    """
    logger.info(f"🔧 Generating file [{request.file_number}]: {request.file_path}")
    
    user_prompt = f"""PROJECT CONTEXT:
{request.project_structure}

FILE TO GENERATE:
- Number: [{request.file_number}]
- Path: {request.file_path}
- Project: {request.project_name or "Project"}
- Tech Stack: {request.tech_stack or "TypeScript"}

GENERATE THE COMPLETE CODE FOR: {request.file_path}"""
    
    try:
        messages = [{"role": "user", "content": user_prompt}]
        
        code = ask_openai(
            messages=messages,
            model="gpt-4o",
            max_tokens=4000,
            temperature=0.3,
            system_prompt=FILE_GENERATOR_SYSTEM
        )
        
        if code.startswith("[OpenAI Error]"):
            raise HTTPException(status_code=500, detail=code)
        
        language = detect_language(request.file_path)
        code = clean_code_output(code)
        tokens_used = len(code) // 4
        
        logger.info(f"✅ Generated {request.file_path} ({len(code)} chars)")
        
        return GenerateFileResponse(
            file_number=request.file_number,
            file_path=request.file_path,
            code=code,
            language=language,
            tokens_used=tokens_used
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate {request.file_path}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-file-with-context", response_model=GenerateFileResponse)
async def generate_file_with_context_endpoint(
    request: GenerateFileWithContextRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate code WITH Smart Context (Sonnet 4.5 + pgvector + dependencies)
    """
    from app.utils.api_key_resolver import get_anthropic_key
    
    logger.info(f"🔧 [WITH CONTEXT] Generating: {request.file_path}")
    
    # Load file spec
    file_spec = db.execute(text("""
        SELECT file_number, description, language
        FROM file_specifications
        WHERE project_id = :project_id 
          AND file_path = :file_path
    """), {
        "project_id": request.project_id,
        "file_path": request.file_path
    }).fetchone()
    
    if not file_spec:
        raise HTTPException(404, "File spec not found. Run /save-structure first!")
    
    # Load project
    project = db.query(Project).filter(
        Project.id == request.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    # Get API key
    anthropic_key = get_anthropic_key(current_user, db, required=True)
    
    # Generate with Smart Context
    code = await generate_file_with_smart_context(
        file_path=request.file_path,
        file_number=file_spec[0],
        description=file_spec[1] or "",
        language=file_spec[2] or detect_language(request.file_path),
        project_id=request.project_id,
        project_name=project.name,
        db=db,
        anthropic_key=anthropic_key,
    )
    
    # Save to database
    db.execute(text("""
        UPDATE file_specifications
        SET generated_code = :code,
            status = 'generated',
            updated_at = :now
        WHERE project_id = :project_id
          AND file_path = :file_path
    """), {
        "code": code,
        "now": datetime.utcnow(),
        "project_id": request.project_id,
        "file_path": request.file_path
    })
    db.commit()
    
    return GenerateFileResponse(
        file_number=file_spec[0],
        file_path=request.file_path,
        code=code,
        language=file_spec[2] or detect_language(request.file_path),
        tokens_used=len(code) // 4
    )


@router.post("/generate-all-in-order/{project_id}", response_model=BatchGenerationResponse)
async def generate_all_files_in_order(
    project_id: int,
    background_tasks: BackgroundTasks,
    use_smart_context: bool = True,  # ← NEW: Default to Smart Context
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate ALL files in correct dependency order.
    
    - use_smart_context=True (default): Claude Sonnet 4.5 + pgvector + dependencies
    - use_smart_context=False: GPT-4o only (faster, cheaper, less quality)
    """
    
    logger.info(f"🚀 Starting batch generation for project {project_id}")
    
    # Load project
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    # Check files exist
    files_count = db.execute(text("""
        SELECT COUNT(*) FROM file_specifications WHERE project_id = :project_id
    """), {"project_id": project_id}).scalar()
    
    if files_count == 0:
        raise HTTPException(400, "No files found. Run /save-structure first!")
    
    # Get API keys
    anthropic_key = None
    if use_smart_context:
        from app.utils.api_key_resolver import get_anthropic_key
        try:
            anthropic_key = get_anthropic_key(current_user, db, required=True)
        except Exception as e:
            raise HTTPException(400, f"Smart Context requires Anthropic API key: {e}")
    
    # Get generation order
    try:
        generation_order = get_generation_order_from_db(project_id, db)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to determine generation order: {e}")
    
    logger.info(f"📊 Generation order: {len(generation_order)} files")
    
    # Reset statuses
    db.execute(text("""
        UPDATE file_specifications
        SET status = 'pending', generated_code = NULL, updated_at = :now
        WHERE project_id = :project_id
    """), {"project_id": project_id, "now": datetime.utcnow()})
    db.commit()
    
    # Start background generation
    background_tasks.add_task(
        generate_files_background,
        project_id=project_id,
        generation_order=generation_order,
        user_id=current_user.id,
        use_smart_context=use_smart_context,
        anthropic_key=anthropic_key,
    )
    
    mode_name = "Smart Context (Sonnet 4.5)" if use_smart_context else "Fast Mode (GPT-4o)"
    
    return BatchGenerationResponse(
        success=True,
        project_id=project_id,
        project_name=project.name,
        total_files=len(generation_order),
        generation_order=generation_order,
        message=f"Batch generation started with {mode_name}. Check /generation-status/{project_id}"
    )


async def generate_files_background(
    project_id: int,
    generation_order: List[str],
    user_id: int,
    use_smart_context: bool = True,
    anthropic_key: Optional[str] = None,
):
    """
    Background task to generate all files.
    
    - use_smart_context=True: Claude Sonnet 4.5 with full context
    - use_smart_context=False: GPT-4o only (fast mode)
    """
    from app.memory.db import SessionLocal
    
    db = SessionLocal()
    
    try:
        mode_name = "Smart Context (Sonnet 4.5)" if use_smart_context else "Fast Mode (GPT-4o)"
        logger.info(f"🔄 Background generation started for project {project_id}")
        logger.info(f"🎯 Mode: {mode_name}")
        
        started_at = datetime.utcnow()
        files_generated = 0
        files_failed = 0
        errors = []
        
        # Load project once
        project = db.query(Project).filter(Project.id == project_id).first()
        
        for i, file_path in enumerate(generation_order, 1):
            logger.info(f"📝 [{i}/{len(generation_order)}] Generating: {file_path}")
            
            try:
                # Load file spec
                file_spec = db.execute(text("""
                    SELECT file_number, description, language
                    FROM file_specifications
                    WHERE project_id = :project_id AND file_path = :file_path
                """), {"project_id": project_id, "file_path": file_path}).fetchone()
                
                if not file_spec:
                    logger.error(f"❌ File spec not found: {file_path}")
                    files_failed += 1
                    errors.append(f"{file_path}: Spec not found")
                    continue
                
                file_number = file_spec[0]
                description = file_spec[1] or ""
                language = file_spec[2] or detect_language(file_path)
                
                # ========== GENERATE CODE ==========
                if use_smart_context and anthropic_key:
                    # Smart Context Mode: Claude Sonnet 4.5
                    code = await generate_file_with_smart_context(
                        file_path=file_path,
                        file_number=file_number,
                        description=description,
                        language=language,
                        project_id=project_id,
                        project_name=project.name,
                        db=db,
                        anthropic_key=anthropic_key,
                    )
                else:
                    # Fast Mode: GPT-4o only
                    context_data = load_dependency_context(db, project_id, file_path)
                    
                    prompt_parts = [f"""PROJECT: {project.name}
FILE TO GENERATE: {file_path}
FILE NUMBER: [{file_number}]
LANGUAGE: {language}
DESCRIPTION: {description}
"""]
                    
                    if context_data["context_files"]:
                        prompt_parts.append("\n=== ALREADY GENERATED FILES ===\n")
                        for dep_file, dep_data in context_data["context_files"].items():
                            dep_code = dep_data["code"]
                            if len(dep_code) > 3000:
                                dep_code = dep_code[:3000] + "\n// ... truncated"
                            prompt_parts.append(f"File: {dep_file}\n```\n{dep_code}\n```\n")
                    
                    prompt_parts.append(f"\nGENERATE COMPLETE CODE FOR: {file_path}")
                    
                    code = ask_openai(
                        messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
                        model="gpt-4o",
                        max_tokens=4000,
                        temperature=0.3,
                        system_prompt=FILE_GENERATOR_SYSTEM
                    )
                
                # Check for errors
                if code.startswith("[OpenAI Error]") or code.startswith("[Claude Error]"):
                    logger.error(f"❌ AI error for {file_path}: {code}")
                    files_failed += 1
                    errors.append(f"{file_path}: {code[:100]}")
                    
                    db.execute(text("""
                        UPDATE file_specifications SET status = 'failed', updated_at = :now
                        WHERE project_id = :project_id AND file_path = :file_path
                    """), {"now": datetime.utcnow(), "project_id": project_id, "file_path": file_path})
                    db.commit()
                    continue
                
                # Clean and save
                code = clean_code_output(code)
                
                db.execute(text("""
                    UPDATE file_specifications
                    SET generated_code = :code, status = 'generated', updated_at = :now
                    WHERE project_id = :project_id AND file_path = :file_path
                """), {
                    "code": code,
                    "now": datetime.utcnow(),
                    "project_id": project_id,
                    "file_path": file_path
                })
                db.commit()
                
                # 🆕 UPDATE DEPENDENCIES FROM REAL IMPORTS
                try:
                    deps_count = update_file_dependencies_from_code(
                        db=db,
                        project_id=project_id,
                        file_path=file_path,
                        code=code,
                        language=language,
                        all_project_files=generation_order  # ← All files in project
                    )
                    if deps_count > 0:
                        logger.info(f"  📦 Updated {deps_count} real dependencies for {file_path}")
                except Exception as dep_error:
                    logger.warning(f"  ⚠️ Failed to update dependencies: {dep_error}")
                
                files_generated += 1
                logger.info(f"✅ [{i}/{len(generation_order)}] Generated {file_path} ({len(code)} chars)")
                
            except Exception as e:
                logger.exception(f"❌ Failed to generate {file_path}")
                files_failed += 1
                errors.append(f"{file_path}: {str(e)[:100]}")
                
                try:
                    db.execute(text("""
                        UPDATE file_specifications SET status = 'failed', updated_at = :now
                        WHERE project_id = :project_id AND file_path = :file_path
                    """), {"now": datetime.utcnow(), "project_id": project_id, "file_path": file_path})
                    db.commit()
                except:
                    pass
        
        # Summary
        completed_at = datetime.utcnow()
        duration = (completed_at - started_at).total_seconds()
        
        logger.info(f"""
🎉 Batch generation completed for project {project_id}:
   Mode: {mode_name}
   Total: {len(generation_order)} files
   Generated: {files_generated}
   Failed: {files_failed}
   Duration: {duration:.1f}s
   Errors: {len(errors)}
""")
        
    except Exception as e:
        logger.exception(f"❌ Batch generation failed: {e}")
    finally:
        db.close()


@router.get("/generation-status/{project_id}")
async def get_generation_status(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current status of batch generation"""
    
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    status_counts = db.execute(text("""
        SELECT status, COUNT(*) as count
        FROM file_specifications
        WHERE project_id = :project_id
        GROUP BY status
    """), {"project_id": project_id}).fetchall()
    
    total = sum(row[1] for row in status_counts)
    generated = sum(row[1] for row in status_counts if row[0] == 'generated')
    failed = sum(row[1] for row in status_counts if row[0] == 'failed')
    pending = sum(row[1] for row in status_counts if row[0] == 'pending')
    
    if pending == 0 and failed == 0:
        overall_status = "completed"
    elif pending > 0:
        overall_status = "running"
    else:
        overall_status = "completed_with_errors"
    
    return {
        "project_id": project_id,
        "project_name": project.name,
        "status": overall_status,
        "total_files": total,
        "files_generated": generated,
        "files_failed": failed,
        "files_pending": pending,
        "progress_percent": int((generated / total * 100) if total > 0 else 0),
    }


@router.get("/projects/{project_id}/all-generated-files")
async def get_all_generated_files(
    project_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get ALL generated files for download"""
    
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    files = db.execute(text("""
        SELECT file_path, generated_code, language
        FROM file_specifications
        WHERE project_id = :project_id AND status = 'generated'
        ORDER BY file_number
    """), {"project_id": project_id}).fetchall()
    
    file_list = [{
        "file_path": f[0],
        "content": f[1],
        "language": f[2],
        "size": len(f[1]) if f[1] else 0
    } for f in files]
    
    return {
        "project_id": project_id,
        "project_name": project.name,
        "total_files": len(file_list),
        "files": file_list
    }


@router.post("/save-structure/{project_id}")
async def save_project_structure(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Parse project_structure and save to file_specifications table"""
    
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    if not project.project_structure:
        raise HTTPException(400, "Project has no structure. Generate with Debate Mode first.")
    
    try:
        file_specs = parse_project_structure(project.project_structure)
    except Exception as e:
        raise HTTPException(400, f"Failed to parse: {e}")
    
    if not file_specs:
        raise HTTPException(400, "No files found in project_structure")
    
    # Clear existing
    db.execute(text("DELETE FROM file_specifications WHERE project_id = :project_id"), {"project_id": project_id})
    db.execute(text("DELETE FROM file_dependencies WHERE project_id = :project_id"), {"project_id": project_id})
    db.commit()
    
    # Save files
    files_saved = 0
    for spec in file_specs:
        db.execute(text("""
            INSERT INTO file_specifications 
            (project_id, file_path, file_number, description, language, status, created_at, updated_at)
            VALUES (:project_id, :file_path, :file_number, :description, :language, 'pending', :now, :now)
        """), {
            "project_id": project_id,
            "file_path": spec.file_path,
            "file_number": spec.file_number,
            "description": spec.description,
            "language": spec.language,
            "now": datetime.utcnow()
        })
        files_saved += 1
    db.commit()
    
    # Save dependencies
    dependencies = analyze_basic_dependencies(file_specs)
    deps_saved = 0
    for source_file, targets in dependencies.items():
        for target_file in targets:
            db.execute(text("""
                INSERT INTO file_dependencies (project_id, source_file, target_file, dependency_type, created_at)
                VALUES (:project_id, :source_file, :target_file, 'import', :now)
            """), {
                "project_id": project_id,
                "source_file": source_file,
                "target_file": target_file,
                "now": datetime.utcnow()
            })
            deps_saved += 1
    db.commit()
    
    lang_count = Counter(f.language for f in file_specs)
    
    logger.info(f"✅ Saved {files_saved} files and {deps_saved} dependencies")
    
    return {
        "success": True,
        "project_id": project_id,
        "files_saved": files_saved,
        "dependencies_saved": deps_saved,
        "languages": dict(lang_count),
    }


@router.post("/test-smart-context-generation")
async def test_smart_context_generation(
    project_id: int,
    file_path: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    TEST endpoint - generate ONE file with Smart Context
    """
    from app.utils.api_key_resolver import get_anthropic_key
    
    anthropic_key = get_anthropic_key(current_user, db, required=True)
    
    file_spec = db.execute(text("""
        SELECT file_number, description, language
        FROM file_specifications
        WHERE project_id = :project_id AND file_path = :file_path
    """), {"project_id": project_id, "file_path": file_path}).fetchone()
    
    if not file_spec:
        raise HTTPException(404, "File not found")
    
    project = db.query(Project).filter(Project.id == project_id).first()
    
    code = await generate_file_with_smart_context(
        file_path=file_path,
        file_number=file_spec[0],
        description=file_spec[1] or "",
        language=file_spec[2] or "typescript",
        project_id=project_id,
        project_name=project.name,
        db=db,
        anthropic_key=anthropic_key,
    )
    
    return {
        "success": True,
        "file_path": file_path,
        "code": code,
        "code_length": len(code),
        "mode": "Smart Context (Sonnet 4.5)"
    }