# File: backend/app/routers/project_builder.py
"""
Project Builder API - Generate individual files from project structure
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import logging
from datetime import datetime
from collections import Counter
from sqlalchemy.orm import Session

from app.memory.db import get_db
from app.memory.models import Project
from app.services.project_structure_parser import (
    parse_project_structure, 
    analyze_basic_dependencies
)

from app.deps import get_current_user
from app.providers.openai_provider import ask_openai

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
        if code.startswith("[OpenAI Error]"):
            logger.error(f"❌ OpenAI error for {request.file_path}: {code}")
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
        "DELETE FROM file_specifications WHERE project_id = :project_id",
        {"project_id": project_id}
    )
    db.execute(
        "DELETE FROM file_dependencies WHERE project_id = :project_id",
        {"project_id": project_id}
    )
    db.commit()
    
    # 4. Save file specifications
    files_saved = 0
    for spec in file_specs:
        db.execute("""
            INSERT INTO file_specifications 
            (project_id, file_path, file_number, description, language, status, created_at, updated_at)
            VALUES (:project_id, :file_path, :file_number, :description, :language, 'pending', :now, :now)
        """, {
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
            db.execute("""
                INSERT INTO file_dependencies
                (project_id, source_file, target_file, dependency_type, created_at)
                VALUES (:project_id, :source_file, :target_file, 'import', :now)
            """, {
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