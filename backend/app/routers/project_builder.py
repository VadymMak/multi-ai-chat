# File: backend/app/routers/project_builder.py
"""
Project Builder API - Generate individual files from project structure
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import logging

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