"""
Auto-Learning API Endpoints for VS Code Extension.
Add this to backend/app/routers/vscode.py or create new file.

File: backend/app/routers/auto_learning.py
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.deps import get_current_active_user, get_db
from app.memory.models import User
from app.services.auto_learning import AutoLearningService

router = APIRouter(prefix="/vscode", tags=["auto-learning"])


# ==================== REQUEST/RESPONSE MODELS ====================

class ReportErrorRequest(BaseModel):
    """Request to report a code error"""
    project_id: int
    error_pattern: str           # "Cannot find module './UserService'"
    error_type: str              # 'import', 'type', 'syntax', 'runtime', 'lint'
    error_code: Optional[str] = None     # 'TS2307', 'ESLint/no-unused-vars'
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None


class ReportErrorResponse(BaseModel):
    """Response from error report"""
    success: bool
    error_id: int
    is_new: bool
    occurrence_count: int
    message: str


class ReportFixRequest(BaseModel):
    """Request to report that an error was fixed"""
    error_id: int
    original_code: Optional[str] = None
    fixed_code: Optional[str] = None
    fix_method: str = "manual"   # 'manual', 'ai_edit', 'auto_import'
    solution_pattern: Optional[str] = None


class ReportFixResponse(BaseModel):
    """Response from fix report"""
    success: bool
    message: str


class GetWarningsRequest(BaseModel):
    """Request to get warnings for AI prompt"""
    project_id: int
    file_path: Optional[str] = None
    limit: int = 5


class GetWarningsResponse(BaseModel):
    """Response with warnings for AI prompt"""
    success: bool
    warnings: List[dict]
    prompt_text: str            # Formatted text to add to AI prompt
    count: int


class ReportBreakingChangeRequest(BaseModel):
    """Request to report a file rename/delete"""
    project_id: int
    old_path: str
    new_path: Optional[str] = None  # None if file was deleted
    change_type: str = "rename"     # 'rename', 'remove', 'move'


class ReportBreakingChangeResponse(BaseModel):
    """Response from breaking change report"""
    success: bool
    recorded: bool
    change_id: Optional[int] = None
    broken_files: List[str] = []
    broken_count: int = 0
    message: str


class ProjectStatsResponse(BaseModel):
    """Response with project learning statistics"""
    success: bool
    errors: dict
    breaking_changes: dict
    top_errors: List[dict]


# ==================== ENDPOINTS ====================

@router.post("/report-error", response_model=ReportErrorResponse)
async def report_error(
    request: ReportErrorRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Report a code error from VS Code Extension.
    Called when TypeScript/ESLint errors are detected.
    
    The system will:
    1. Check if similar error exists
    2. If yes - increment occurrence_count
    3. If no - create new error entry
    4. Return error_id for tracking
    """
    
    try:
        service = AutoLearningService(db)
        
        result = service.report_error(
            project_id=request.project_id,
            error_pattern=request.error_pattern,
            error_type=request.error_type,
            error_code=request.error_code,
            file_path=request.file_path,
            line_number=request.line_number,
            code_snippet=request.code_snippet
        )
        
        if result["is_new"]:
            message = f"New error pattern recorded"
        else:
            message = f"Error seen {result['occurrence_count']} times"
        
        print(f"🎓 [AutoLearn] {message}: {request.error_pattern[:50]}...")
        
        return ReportErrorResponse(
            success=True,
            error_id=result["error_id"],
            is_new=result["is_new"],
            occurrence_count=result["occurrence_count"],
            message=message
        )
        
    except Exception as e:
        print(f"❌ [AutoLearn] Report error failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/report-fix", response_model=ReportFixResponse)
async def report_fix(
    request: ReportFixRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Report that an error was fixed.
    Used to learn solutions and improve future suggestions.
    """
    
    try:
        service = AutoLearningService(db)
        
        success = service.report_fix(
            error_id=request.error_id,
            original_code=request.original_code,
            fixed_code=request.fixed_code,
            fix_method=request.fix_method,
            solution_pattern=request.solution_pattern
        )
        
        if success:
            print(f"✅ [AutoLearn] Error {request.error_id} marked as fixed")
            return ReportFixResponse(
                success=True,
                message="Fix recorded successfully"
            )
        else:
            return ReportFixResponse(
                success=False,
                message="Failed to record fix"
            )
        
    except Exception as e:
        print(f"❌ [AutoLearn] Report fix failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/get-warnings", response_model=GetWarningsResponse)
async def get_warnings(
    request: GetWarningsRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get learned warnings to include in AI prompt.
    Returns both structured data and formatted prompt text.
    """
    
    try:
        service = AutoLearningService(db)
        
        warnings = service.get_warnings_for_prompt(
            project_id=request.project_id,
            file_path=request.file_path,
            limit=request.limit
        )
        
        prompt_text = service.format_warnings_for_prompt(
            project_id=request.project_id,
            file_path=request.file_path
        )
        
        print(f"📋 [AutoLearn] Returning {len(warnings)} warnings for project {request.project_id}")
        
        return GetWarningsResponse(
            success=True,
            warnings=warnings,
            prompt_text=prompt_text,
            count=len(warnings)
        )
        
    except Exception as e:
        print(f"❌ [AutoLearn] Get warnings failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learned-warnings/{project_id}")
async def get_learned_warnings(
    project_id: int,
    file_path: Optional[str] = None,
    limit: int = 5,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    GET endpoint for warnings (simpler than POST).
    Returns formatted prompt text for AI.
    """
    
    try:
        service = AutoLearningService(db)
        
        warnings = service.get_warnings_for_prompt(
            project_id=project_id,
            file_path=file_path,
            limit=limit
        )
        
        prompt_text = service.format_warnings_for_prompt(
            project_id=project_id,
            file_path=file_path
        )
        
        return {
            "success": True,
            "warnings": warnings,
            "prompt_text": prompt_text,
            "count": len(warnings)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/report-breaking-change", response_model=ReportBreakingChangeResponse)
async def report_breaking_change(
    request: ReportBreakingChangeRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Report a file rename/delete that might break imports.
    System will find all files that import the old path.
    """
    
    try:
        service = AutoLearningService(db)
        
        result = service.detect_breaking_change(
            project_id=request.project_id,
            old_path=request.old_path,
            new_path=request.new_path,
            change_type=request.change_type
        )
        
        if result["recorded"]:
            print(f"⚠️ [AutoLearn] Breaking change: {request.old_path} affects {result['broken_count']} files")
            return ReportBreakingChangeResponse(
                success=True,
                recorded=True,
                change_id=result.get("change_id"),
                broken_files=result.get("broken_files", []),
                broken_count=result.get("broken_count", 0),
                message=f"Breaking change recorded. {result['broken_count']} files affected."
            )
        else:
            return ReportBreakingChangeResponse(
                success=True,
                recorded=False,
                message=result.get("reason", "No files affected")
            )
        
    except Exception as e:
        print(f"❌ [AutoLearn] Report breaking change failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learning-stats/{project_id}", response_model=ProjectStatsResponse)
async def get_learning_stats(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get learning statistics for a project.
    Shows how much the system has learned.
    """
    
    try:
        service = AutoLearningService(db)
        
        stats = service.get_project_stats(project_id)
        
        return ProjectStatsResponse(
            success=True,
            errors=stats["errors"],
            breaking_changes=stats["breaking_changes"],
            top_errors=stats["top_errors"]
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/breaking-changes/{project_id}")
async def get_breaking_changes(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get unresolved breaking changes for a project.
    """
    
    try:
        service = AutoLearningService(db)
        
        changes = service.get_unresolved_breaking_changes(project_id)
        
        return {
            "success": True,
            "breaking_changes": changes,
            "count": len(changes)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== INTEGRATION HELPER ====================

def get_warnings_for_ai_prompt(
    db: Session,
    project_id: int,
    file_path: Optional[str] = None
) -> str:
    """
    Helper function to get warnings for AI prompt.
    Call this from edit_file_with_ai() and create_file_with_ai().
    
    Usage in vscode.py:
        from app.routers.auto_learning import get_warnings_for_ai_prompt
        
        warnings = get_warnings_for_ai_prompt(db, project_id, file_path)
        prompt += warnings
    """
    
    try:
        service = AutoLearningService(db)
        return service.format_warnings_for_prompt(project_id, file_path)
    except Exception as e:
        print(f"⚠️ [AutoLearn] Failed to get warnings: {e}")
        return ""