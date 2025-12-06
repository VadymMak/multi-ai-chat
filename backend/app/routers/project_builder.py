# File: backend/app/routers/project_builder.py
"""
Project Builder API - Generate individual files from project structure
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
import logging
from datetime import datetime
from collections import Counter
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.memory.db import get_db
from app.memory.models import Project
from app.services.project_structure_parser import (
    parse_project_structure, 
    analyze_basic_dependencies
)

from app.deps import get_current_user
from app.providers.openai_provider import ask_openai
from app.services.dependency_graph import get_generation_order_from_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/project-builder", tags=["project-builder"])


class GenerateFileRequest(BaseModel):
    """Request to generate a single file"""
    project_structure: str  # The full project structure text
    file_number: int        # Which file to generate [1], [2], etc.
    file_path: str          # Path of the file to generate
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
    project_id: int         # Which project
    file_path: str          # Path of file to generate
    use_smart_context: bool = True  # Use Smart Context?


# System prompt for file generation
FILE_GENERATOR_SYSTEM = """You are a senior software engineer generating production-ready code.
Generate COMPLETE, WORKING code - not stubs or placeholders.
Include all necessary imports at the top.
Add helpful comments for complex logic.
Follow best practices for the given tech stack.
Ensure compatibility with other files in the project.
Include error handling where appropriate.
Use TypeScript types if applicable.
Return ONLY the code for this file. No explanations, no markdown code blocks.
Start directly with the code content."""


FILE_GENERATOR_PROMPT = """PROJECT CONTEXT:
{project_structure}

FILE TO GENERATE:
- Number: [{file_number}]
- Path: {file_path}
- Project: {project_name}
- Tech Stack: {tech_stack}

GENERATE THE COMPLETE CODE FOR: {file_path}"""


@router.post("/generate-file", response_model=GenerateFileResponse)
async def generate_file(
    request: GenerateFileRequest,
    current_user = Depends(get_current_user)
):
    """
    Generate code for a single file based on project structure.
    Uses GPT-4o for fast, high-quality code generation.
    """
    logger.info(f"🔧 Generating file [{request.file_number}]: {request.file_path}")
    
    # Build the prompt
    user_prompt = FILE_GENERATOR_PROMPT.format(
        project_structure=request.project_structure,
        file_number=request.file_number,
        file_path=request.file_path,
        project_name=request.project_name or "Project",
        tech_stack=request.tech_stack or "TypeScript"
    )
    
    try:
        # Use GPT-4o for code generation (fast and good quality)
        messages = [
            {"role": "user", "content": user_prompt}
        ]
        
        code = ask_openai(
            messages=messages,
            model="gpt-4o",
            max_tokens=4000,
            temperature=0.3,  # Lower temperature for more consistent code
            system_prompt=FILE_GENERATOR_SYSTEM
        )
        
        # Check for error response
        if code.startswith("[OpenAI Error]") or code.startswith("[Claude Error]"):
            logger.error(f"❌ AI error for {request.file_path}: {code}")
            raise HTTPException(status_code=500, detail=code)
        
        # Detect language from file extension
        language = detect_language(request.file_path)
        
        # Clean up code (remove markdown fences if present)
        code = clean_code_output(code)
        
        # Estimate tokens (rough: 4 chars = 1 token)
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
        raise HTTPException(status_code=500, detail=f"Failed to generate file: {str(e)}")


def detect_language(file_path: str) -> str:
    """Detect programming language from file extension"""
    ext_map = {
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".py": "python",
        ".json": "json",
        ".css": "css",
        ".scss": "scss",
        ".html": "html",
        ".md": "markdown",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".sh": "bash",
        ".bash": "bash",
        ".sql": "sql",
        ".graphql": "graphql",
        ".vue": "vue",
        ".svelte": "svelte",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".swift": "swift",
        ".rb": "ruby",
        ".php": "php",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
    }
    
    for ext, lang in ext_map.items():
        if file_path.endswith(ext):
            return lang
    
    return "text"

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
                "types.d.ts": "interface Logger {...}",
                "utils.ts": "export function helper() {...}"
            }
        }
    """
    
    # Find dependencies for this file
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
    
    # Load already-generated code from dependencies
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


def clean_code_output(code: str) -> str:
    """Remove markdown code fences if present"""
    lines = code.strip().split("\n")
    
    # Check if wrapped in ```
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    
    return "\n".join(lines)

# ====================================================================
# 🆕 GENERATE FILE WITH CONTEXT (Phase 0 Week 1 Day 2)
# ====================================================================

@router.post("/generate-file-with-context", response_model=GenerateFileResponse)
async def generate_file_with_context(
    request: GenerateFileWithContextRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate code WITH CONTEXT from database
    
    NEW FLOW:
    1. Load file spec from file_specifications
    2. Load dependencies from file_dependencies
    3. Load already-generated files (context!)
    4. Build enhanced prompt with context
    5. Generate with GPT-4o
    6. Save to database
    """
    
    logger.info(f"🔧 [WITH CONTEXT] Generating: {request.file_path}")
    
    # 1. Load file spec from database
    file_spec = db.execute(text("""
        SELECT file_number, description, language, specification
        FROM file_specifications
        WHERE project_id = :project_id 
          AND file_path = :file_path
    """), {
        "project_id": request.project_id,
        "file_path": request.file_path
    }).fetchone()
    
    if not file_spec:
        raise HTTPException(
            status_code=404,
            detail=f"File spec not found. Run /save-structure first!"
        )
    
    file_number = file_spec[0]
    description = file_spec[1]
    language = file_spec[2] or detect_language(request.file_path)
    
    # 2. Load project info
    project = db.query(Project).filter(
        Project.id == request.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # 3. Load dependency context
    context_data = load_dependency_context(
        db=db,
        project_id=request.project_id,
        file_path=request.file_path
    )
    
    # 4. Build ENHANCED prompt with context
    prompt_parts = []
    
    # Project info
    prompt_parts.append(f"""PROJECT: {project.name}
FILE TO GENERATE: {request.file_path}
FILE NUMBER: [{file_number}]
LANGUAGE: {language}
""")
    
    if description:
        prompt_parts.append(f"DESCRIPTION: {description}\n")
    
    # CRITICAL: Add context from already-generated files
    if context_data["context_files"]:
        prompt_parts.append("\n=== ALREADY GENERATED FILES (USE THESE!) ===\n")
        
        for dep_file, dep_data in context_data["context_files"].items():
            dep_lang = dep_data["language"] or "text"
            dep_code = dep_data["code"]
            
            prompt_parts.append(f"""
File: {dep_file}
```{dep_lang}
{dep_code}
```
""")
        
        prompt_parts.append("""
CRITICAL RULES:
1. Import types/functions from files above using CORRECT paths
2. Do NOT redefine types that already exist above
3. Ensure compatibility with files above
4. Use EXACT import paths shown in file structure
""")
    
    prompt_parts.append(f"\nGENERATE COMPLETE CODE FOR: {request.file_path}")
    
    user_prompt = "\n".join(prompt_parts)
    
    logger.info(f"📝 Prompt size: {len(user_prompt)} chars, Context files: {len(context_data['context_files'])}")
    
    try:
        # 5. Generate with GPT-4o
        messages = [
            {"role": "user", "content": user_prompt}
        ]
        
        code = ask_openai(
            messages=messages,
            model="gpt-4o",
            max_tokens=4000,
            temperature=0.3,
            system_prompt=FILE_GENERATOR_SYSTEM
        )
        
        if code.startswith("[OpenAI Error]"):
            logger.error(f"❌ OpenAI error: {code}")
            raise HTTPException(status_code=500, detail=code)
        
        # Clean up
        code = clean_code_output(code)
        
        # 6. Save to database
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
        
        logger.info(f"✅ Generated {request.file_path} ({len(code)} chars) WITH CONTEXT!")
        
        return GenerateFileResponse(
            file_number=file_number,
            file_path=request.file_path,
            code=code,
            language=language,
            tokens_used=len(code) // 4
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ Failed to generate {request.file_path}")
        raise HTTPException(status_code=500, detail=f"Failed to generate: {str(e)}")
    

# ====================================================================
# 🆕 BATCH GENERATION - ALL FILES IN ORDER (Phase 0 Week 2)
# ====================================================================




class BatchGenerationStatus(BaseModel):
    """Status of batch generation"""
    project_id: int
    total_files: int
    files_generated: int
    files_failed: int
    current_file: Optional[str]
    status: str  # 'running', 'completed', 'failed'
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


@router.post("/generate-all-in-order/{project_id}", response_model=BatchGenerationResponse)
async def generate_all_files_in_order(
    project_id: int,
    background_tasks: BackgroundTasks,
    use_debate: bool = False,  # ← ADD THIS
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate ALL files in correct dependency order
    
    NEW: Supports debate mode (3-step) for higher quality!
    - use_debate=True: GPT-4o → Sonnet → Sonnet 4.5 (slower, better quality)
    - use_debate=False: GPT-4o only (faster, cheaper)
    """
    
    logger.info(f"🚀 Starting batch generation for project {project_id}")
    
    # 1. Load project
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # 2. Check if files exist
    files_count = db.execute(text("""
        SELECT COUNT(*) 
        FROM file_specifications 
        WHERE project_id = :project_id
    """), {"project_id": project_id}).scalar()
    
    if files_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No files found. Run /save-structure first!"
        )
    
    # Get API keys if debate mode is enabled
    openai_key = None
    anthropic_key = None
    
    if use_debate:
        from app.utils.api_key_resolver import get_openai_key, get_anthropic_key
        try:
            openai_key = get_openai_key(current_user, db, required=True)
            anthropic_key = get_anthropic_key(current_user, db, required=True)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Debate mode requires API keys: {str(e)}"
            )
    
    # 3. Get generation order
    try:
        generation_order = get_generation_order_from_db(project_id, db)
    except ValueError as e:
        # Circular dependencies
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to get generation order: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to determine generation order: {str(e)}"
        )
    
    logger.info(f"📊 Generation order: {len(generation_order)} files")
    
    # 4. Reset all statuses to 'pending'
    db.execute(text("""
        UPDATE file_specifications
        SET status = 'pending',
            generated_code = NULL,
            updated_at = :now
        WHERE project_id = :project_id
    """), {
        "project_id": project_id,
        "now": datetime.utcnow()
    })
    db.commit()
    
    # 5. Start background generation
    background_tasks.add_task(
        generate_files_background,
        project_id=project_id,
        generation_order=generation_order,
        user_id=current_user.id,
        use_debate=use_debate,  # ← ADD THIS
        openai_key=openai_key,  # ← ADD THIS
        anthropic_key=anthropic_key  # ← ADD THIS
    )
    
    logger.info(f"✅ Batch generation started for project {project_id}")
    
    return BatchGenerationResponse(
        success=True,
        project_id=project_id,
        project_name=project.name,
        total_files=len(generation_order),
        generation_order=generation_order,
        message=f"Batch generation started for {len(generation_order)} files. Check /generation-status/{project_id} for progress."
    )


async def generate_files_background(
    project_id: int,
    generation_order: List[str],
    user_id: int,
    use_debate: bool = True,  # ← ADD THIS
    openai_key: Optional[str] = None,  # ← ADD THIS
    anthropic_key: Optional[str] = None  # ← ADD THIS
):
    """
    Background task to generate all files
    
    This runs AFTER the API response is sent.
    Generates files one by one, tracking progress in database.
    """
    from app.memory.db import SessionLocal
    
    db = SessionLocal()
    
    try:
        mode_name = "Debate Mode (3-step)" if use_debate else "Fast Mode (GPT-4o)"
        logger.info(f"🔄 Background generation started for project {project_id}")
        logger.info(f"🎯 Mode: {mode_name}")
        
        started_at = datetime.utcnow()
        files_generated = 0
        files_failed = 0
        errors = []
        
        for i, file_path in enumerate(generation_order, 1):
            logger.info(f"📝 [{i}/{len(generation_order)}] Generating: {file_path}")
            
            try:
                # Load file spec
                file_spec = db.execute(text("""
                    SELECT file_number, description, language
                    FROM file_specifications
                    WHERE project_id = :project_id 
                      AND file_path = :file_path
                """), {
                    "project_id": project_id,
                    "file_path": file_path
                }).fetchone()
                
                if not file_spec:
                    logger.error(f"❌ File spec not found: {file_path}")
                    files_failed += 1
                    errors.append(f"{file_path}: Spec not found")
                    continue
                
                file_number = file_spec[0]
                description = file_spec[1]
                language = file_spec[2] or detect_language(file_path)
                
                # Load project
                project = db.query(Project).filter(Project.id == project_id).first()
                
                # Load dependency context
                context_data = load_dependency_context(
                    db=db,
                    project_id=project_id,
                    file_path=file_path
                )
                
                # ========== DEBATE MODE OR FAST MODE ==========
                if use_debate and openai_key and anthropic_key:
                    # Use 3-step debate mode
                    logger.info(f"  🎯 Using Debate Mode (3-step)")
                    code = await generate_file_with_debate(
                        file_path=file_path,
                        file_number=file_number,
                        description=description,
                        language=language,
                        project_name=project.name,
                        context_files=context_data["context_files"],
                        openai_key=openai_key,
                        anthropic_key=anthropic_key
                    )
                else:
                    # Fast mode: GPT-4o only
                    logger.info(f"  ⚡ Using Fast Mode (GPT-4o)")
                    
                    # Build prompt
                    prompt_parts = []
                    
                    prompt_parts.append(f"""PROJECT: {project.name}
FILE TO GENERATE: {file_path}
FILE NUMBER: [{file_number}]
LANGUAGE: {language}
""")
                    
                    if description:
                        prompt_parts.append(f"DESCRIPTION: {description}\n")
                    
                    # Add context from already-generated files
                    if context_data["context_files"]:
                        prompt_parts.append("\n=== ALREADY GENERATED FILES (USE THESE!) ===\n")
                        
                        for dep_file, dep_data in context_data["context_files"].items():
                            dep_lang = dep_data["language"] or "text"
                            dep_code = dep_data["code"]
                            
                            # Truncate very long files
                            if len(dep_code) > 3000:
                                dep_code = dep_code[:3000] + "\n\n// ... (truncated)"
                            
                            prompt_parts.append(f"""
File: {dep_file}
```{dep_lang}
{dep_code}
```
""")
                        
                        prompt_parts.append("""
CRITICAL RULES:
1. Import types/functions from files above using CORRECT paths
2. Do NOT redefine types that already exist above
3. Ensure compatibility with files above
4. Use EXACT import paths shown in file structure
""")
                    
                    prompt_parts.append(f"\nGENERATE COMPLETE CODE FOR: {file_path}")
                    
                    user_prompt = "\n".join(prompt_parts)
                    
                    # Generate with GPT-4o
                    messages = [{"role": "user", "content": user_prompt}]
                    
                    code = ask_openai(
                        messages=messages,
                        model="gpt-4o",
                        max_tokens=4000,
                        temperature=0.3,
                        system_prompt=FILE_GENERATOR_SYSTEM
                    )
                # ========== END MODE SELECTION ==========
                
                if code.startswith("[OpenAI Error]") or code.startswith("[Claude Error]"):
                    logger.error(f"❌ AI error for {file_path}: {code}")
                    files_failed += 1
                    errors.append(f"{file_path}: {code}")
                    
                    # Mark as failed
                    db.execute(text("""
                        UPDATE file_specifications
                        SET status = 'failed',
                            updated_at = :now
                        WHERE project_id = :project_id
                          AND file_path = :file_path
                    """), {
                        "now": datetime.utcnow(),
                        "project_id": project_id,
                        "file_path": file_path
                    })
                    db.commit()
                    continue
                
                # Clean up
                code = clean_code_output(code)
                
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
                    "project_id": project_id,
                    "file_path": file_path
                })
                db.commit()
                
                files_generated += 1
                logger.info(f"✅ [{i}/{len(generation_order)}] Generated {file_path} ({len(code)} chars)")
                
            except Exception as e:
                logger.exception(f"❌ Failed to generate {file_path}")
                files_failed += 1
                errors.append(f"{file_path}: {str(e)}")
                
                # Mark as failed
                try:
                    db.execute(text("""
                        UPDATE file_specifications
                        SET status = 'failed',
                            updated_at = :now
                        WHERE project_id = :project_id
                          AND file_path = :file_path
                    """), {
                        "now": datetime.utcnow(),
                        "project_id": project_id,
                        "file_path": file_path
                    })
                    db.commit()
                except:
                    pass
        
        # Final summary
        completed_at = datetime.utcnow()
        duration = (completed_at - started_at).total_seconds()
        
        logger.info(f"""
🎉 Batch generation completed for project {project_id}:
   Mode: {mode_name}
   Total files: {len(generation_order)}
   Generated: {files_generated}
   Failed: {files_failed}
   Duration: {duration:.1f}s
   Errors: {len(errors)}
""")
        
        if errors:
            for error in errors[:5]:  # Log first 5 errors
                logger.error(f"  - {error}")
        
    except Exception as e:
        logger.exception(f"❌ Batch generation failed for project {project_id}")
    finally:
        db.close()


@router.get("/generation-status/{project_id}")
async def get_generation_status(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current status of batch generation
    
    Returns progress, current file, completion status, etc.
    """
    
    # Check project exists
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get counts by status
    status_counts = db.execute(text("""
        SELECT 
            status,
            COUNT(*) as count
        FROM file_specifications
        WHERE project_id = :project_id
        GROUP BY status
    """), {"project_id": project_id}).fetchall()
    
    total = sum(row[1] for row in status_counts)
    generated = sum(row[1] for row in status_counts if row[0] == 'generated')
    failed = sum(row[1] for row in status_counts if row[0] == 'failed')
    pending = sum(row[1] for row in status_counts if row[0] == 'pending')
    
    # Get currently generating file (if any)
    # (In this simple version, we don't track "currently generating")
    # Could add a 'generating' status if needed
    
    # Determine overall status
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
        "summary": {
            status: count 
            for status, count in status_counts
        }
    }

# ====================================================================
# 🆕 DEBATE MODE FILE GENERATION (Phase 0.5)
# ====================================================================

async def generate_file_with_debate(
    file_path: str,
    file_number: int,
    description: str,
    language: str,
    project_name: str,
    context_files: dict,
    openai_key: str,
    anthropic_key: str
) -> str:
    """
    Generate file using 3-step debate process:
    
    Step 1: GPT-4o generates initial code
    Step 2: Claude Sonnet reviews and critiques
    Step 3: Claude Opus creates final version
    
    Returns: Final code
    """
    from app.providers.claude_provider import ask_claude
    from starlette.concurrency import run_in_threadpool
    
    logger.info(f"🎯 Debate Mode: Generating {file_path}")
    
    # ---- STEP 1: GPT-4o generates initial version ----
    logger.info(f"  📝 Step 1/3: GPT-4o initial generation...")
    
    step1_prompt_parts = [
        f"Generate {language} code for: {file_path}",
        f"Description: {description}",
        f"Project: {project_name}",
    ]
    
    if context_files:
        step1_prompt_parts.append("\n=== CONTEXT FROM OTHER FILES ===\n")
        for dep_file, dep_data in context_files.items():
            code_preview = dep_data["code"][:500] + "..." if len(dep_data["code"]) > 500 else dep_data["code"]
            step1_prompt_parts.append(f"File: {dep_file}\n```\n{code_preview}\n```\n")
    
    step1_prompt_parts.append(f"\nGenerate COMPLETE code for {file_path}")
    step1_prompt = "\n".join(step1_prompt_parts)
    
    try:
        step1_code = await run_in_threadpool(
            ask_openai,
            [{"role": "user", "content": step1_prompt}],
            model="gpt-4o",
            max_tokens=4000,
            temperature=0.3,
            system_prompt=FILE_GENERATOR_SYSTEM,
            api_key=openai_key
        )
    except Exception as e:
        logger.error(f"❌ Step 1 failed: {e}")
        raise
    
    step1_code = clean_code_output(step1_code)
    logger.info(f"  ✅ Step 1 complete: {len(step1_code)} chars")
    
    # ---- STEP 2: Claude Sonnet reviews ----
    logger.info(f"  🔍 Step 2/3: Claude Sonnet review...")
    
    step2_prompt = f"""Review this generated code and provide critique:

File: {file_path}
Language: {language}

Generated Code:
```{language}
{step1_code}
```

Check for:
1. Import errors
2. Type errors  
3. Missing dependencies
4. Best practices violations
5. Compatibility issues

Provide constructive feedback and suggestions for improvement."""
    
    try:
        step2_review = await run_in_threadpool(
            ask_claude,
            [{"role": "user", "content": step2_prompt}],
            system="You are a code reviewer. Be constructive and helpful.",
            api_key=anthropic_key
        )
    except Exception as e:
        logger.error(f"❌ Step 2 failed: {e}")
        # Fallback: use step1 code if review fails
        logger.warning(f"⚠️ Using GPT-4o code without review")
        return step1_code
    
    logger.info(f"  ✅ Step 2 complete: {len(step2_review)} chars")
    
    # ---- STEP 3: Claude Opus final version ----
    logger.info(f"  🎯 Step 3/3: Claude Opus final synthesis...")
    
    step3_prompt = f"""Create the FINAL, BEST version of this code.

File: {file_path}  
Language: {language}
Description: {description}

Initial Code (GPT-4o):
```{language}
{step1_code}
```

Review Feedback (Sonnet):
{step2_review}

Context Files Available:
{", ".join(context_files.keys()) if context_files else "None"}

Generate the FINAL, IMPROVED code incorporating the review feedback.
Return ONLY the code, no explanations."""
    
    try:
        step3_final = await run_in_threadpool(
            ask_claude,
            [{"role": "user", "content": step3_prompt}],
            system="You are an expert developer. Create the best possible final code.",
            model="claude-sonnet-4-5-20250929",
            api_key=anthropic_key
        )
    except Exception as e:
        logger.error(f"❌ Step 3 failed: {e}")
        # Fallback: use step1 code if final fails
        logger.warning(f"⚠️ Using GPT-4o code as fallback")
        return step1_code
    
    step3_final = clean_code_output(step3_final)
    logger.info(f"  ✅ Step 3 complete: {len(step3_final)} chars")
    logger.info(f"🎉 Debate Mode complete for {file_path}")
    
    return step3_final

# ====================================================================
# 🆕 SAVE STRUCTURE ENDPOINT (Phase 0 Week 1)
# ====================================================================

@router.post("/save-structure/{project_id}")
async def save_project_structure(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Parse project_structure and save to file_specifications table
    
    This endpoint:
    1. Loads project.project_structure (TEXT)
    2. Parses it (supports JSON/Markdown/Plain)
    3. Saves each file to file_specifications
    4. Analyzes and saves basic dependencies
    """
    
    # 1. Load project
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if not project.project_structure:
        raise HTTPException(
            status_code=400, 
            detail="Project has no structure. Generate with Debate Mode or sync Git first."
        )
    
    # 2. Parse structure
    try:
        file_specs = parse_project_structure(project.project_structure)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse project_structure: {str(e)}"
        )
    
    if not file_specs:
        raise HTTPException(
            status_code=400,
            detail="No files found in project_structure"
        )
    
    # 3. Clear existing specifications for this project
    db.execute(
    text("DELETE FROM file_specifications WHERE project_id = :project_id"),
    {"project_id": project_id}
)
    db.execute(
    text("DELETE FROM file_dependencies WHERE project_id = :project_id"),
    {"project_id": project_id}
)
    db.commit()
    
    # 4. Save file specifications
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
    
    # 5. Analyze and save dependencies
    dependencies = analyze_basic_dependencies(file_specs)
    dependencies_saved = 0
    
    for source_file, targets in dependencies.items():
        for target_file in targets:
            db.execute(text("""
                INSERT INTO file_dependencies
                (project_id, source_file, target_file, dependency_type, created_at)
                VALUES (:project_id, :source_file, :target_file, 'import', :now)
            """), {
                "project_id": project_id,
                "source_file": source_file,
                "target_file": target_file,
                "now": datetime.utcnow()
            })
            dependencies_saved += 1
    
    db.commit()
    
    # 6. Language distribution
    lang_count = Counter(f.language for f in file_specs)
    
    logger.info(f"✅ Saved {files_saved} files and {dependencies_saved} dependencies for project {project_id}")
    
    return {
        "success": True,
        "project_id": project_id,
        "project_name": project.name,
        "files_saved": files_saved,
        "dependencies_saved": dependencies_saved,
        "languages": dict(lang_count),
        "sample_files": [
            {
                "file_path": spec.file_path,
                "language": spec.language,
                "description": spec.description
            }
            for spec in file_specs[:5]
        ]
    }


@router.post("/test-debate-generation")
async def test_debate_generation(
    project_id: int,
    file_path: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    TEST endpoint - generate ONE file with debate mode
    """
    from app.utils.api_key_resolver import get_openai_key, get_anthropic_key
    
    # Get API keys
    openai_key = get_openai_key(current_user, db, required=True)
    anthropic_key = get_anthropic_key(current_user, db, required=True)
    
    # Load file spec
    file_spec = db.execute(text("""
        SELECT file_number, description, language
        FROM file_specifications
        WHERE project_id = :project_id 
          AND file_path = :file_path
    """), {
        "project_id": project_id,
        "file_path": file_path
    }).fetchone()
    
    if not file_spec:
        raise HTTPException(404, "File not found")
    
    # Load project
    project = db.query(Project).filter(Project.id == project_id).first()
    
    # Load context
    context_data = load_dependency_context(db, project_id, file_path)
    
    # Generate with debate
    code = await generate_file_with_debate(
        file_path=file_path,
        file_number=file_spec[0],
        description=file_spec[1],
        language=file_spec[2] or "typescript",
        project_name=project.name,
        context_files=context_data["context_files"],
        openai_key=openai_key,
        anthropic_key=anthropic_key
    )
    
    return {
        "success": True,
        "file_path": file_path,
        "code": code,
        "code_length": len(code)
    }