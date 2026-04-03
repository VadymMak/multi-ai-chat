"""
Pattern Analyzer API Endpoints — error categorization and cross-project learning.
File: backend/app/routers/pattern_analyzer.py
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.deps import get_current_active_user, get_db
from app.memory.models import User
from app.services.pattern_analyzer import PatternAnalyzer

router = APIRouter(prefix="/learning", tags=["self-learning"])


# ==================== REQUEST / RESPONSE MODELS ====================


class CategoryInfo(BaseModel):
    """Stats for a single error category"""
    count: int
    resolved: int
    top_files: List[str]


class CategoriesResponse(BaseModel):
    """Response with error category breakdown"""
    success: bool
    categories: dict                         # category_name → CategoryInfo
    most_problematic_category: Optional[str]
    overall_resolution_rate: float


class RecurringItem(BaseModel):
    """Single recurring error pattern"""
    error_id: int
    pattern: str
    error_type: Optional[str]
    occurrence_count: int
    resolved_count: int
    recurrence_ratio: float
    file_path: Optional[str]
    suggested_action: str


class RecurringResponse(BaseModel):
    """Response with recurring / zombie error patterns"""
    success: bool
    recurring_patterns: List[RecurringItem]
    count: int


class CrossProjectSearchRequest(BaseModel):
    """Request to search other projects for a solution to this error"""
    error_pattern: str
    exclude_project_id: int


class CrossProjectSolution(BaseModel):
    """A solution found in another project"""
    project_id: int
    project_name: str
    error_pattern: str
    solution_pattern: str
    solution_example: Optional[str]
    occurrence_count: int
    resolved_count: int


class CrossProjectSearchResponse(BaseModel):
    """Response with cross-project solutions"""
    success: bool
    solutions: List[CrossProjectSolution]
    count: int


class InsightsResponse(BaseModel):
    """Response with formatted learning insights text"""
    success: bool
    insights: str


# ==================== ENDPOINTS ====================


@router.get("/categories/{project_id}", response_model=CategoriesResponse)
async def get_error_categories(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Return error categories breakdown for a project.

    Groups all learned_errors by error_type and returns:
    - per-category counts and resolution stats
    - the most problematic category
    - overall resolution rate across all errors

    Results are cached for 1 hour in error_categories table.
    """
    try:
        analyzer = PatternAnalyzer(db)
        result = analyzer.categorize_errors(project_id)

        print(
            f"🗂️ [PatternAnalyzer] Categories returned for project {project_id}: "
            f"{len(result['categories'])} categories, "
            f"top={result['most_problematic_category']}"
        )

        return CategoriesResponse(
            success=True,
            categories=result["categories"],
            most_problematic_category=result["most_problematic_category"],
            overall_resolution_rate=result["overall_resolution_rate"],
        )

    except Exception as e:
        print(f"❌ [PatternAnalyzer] categories failed for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recurring/{project_id}", response_model=RecurringResponse)
async def get_recurring_patterns(
    project_id: int,
    min_occurrences: int = 3,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Return recurring "zombie" error patterns for a project.

    These are errors that have been fixed at least once but keep coming back.
    Sorted by recurrence_ratio (occurrence_count / resolved_count) descending.

    Query param:
    - min_occurrences (default 3): minimum occurrence_count to be included
    """
    try:
        analyzer = PatternAnalyzer(db)
        patterns = analyzer.find_recurring_patterns(project_id, min_occurrences)

        print(
            f"🔁 [PatternAnalyzer] Recurring patterns for project {project_id}: "
            f"{len(patterns)} found (min={min_occurrences})"
        )

        return RecurringResponse(
            success=True,
            recurring_patterns=[RecurringItem(**p) for p in patterns],
            count=len(patterns),
        )

    except Exception as e:
        print(f"❌ [PatternAnalyzer] recurring failed for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cross-project-search", response_model=CrossProjectSearchResponse)
async def cross_project_search(
    request: CrossProjectSearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Search all other projects for similar errors that already have a solution.

    Normalizes the error_pattern before matching (strips specific paths, types, line numbers).
    Returns up to 5 solutions from other projects, sorted by resolved_count descending.
    """
    try:
        analyzer = PatternAnalyzer(db)
        solutions = analyzer.cross_project_search(
            error_pattern=request.error_pattern,
            exclude_project_id=request.exclude_project_id,
        )

        print(
            f"🌐 [PatternAnalyzer] Cross-project search: {len(solutions)} solutions "
            f"(excluded project {request.exclude_project_id})"
        )

        return CrossProjectSearchResponse(
            success=True,
            solutions=[CrossProjectSolution(**s) for s in solutions],
            count=len(solutions),
        )

    except Exception as e:
        print(f"❌ [PatternAnalyzer] cross-project-search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/insights/{project_id}", response_model=InsightsResponse)
async def get_project_insights(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Return a formatted learning insights report for a project.

    Combines error categorization + recurring pattern detection into a concise
    text block (≤ 500 chars) ready for AI prompt injection.

    Returns an empty insights string if no data is available yet.
    """
    try:
        analyzer = PatternAnalyzer(db)
        insights = analyzer.generate_project_insights(project_id)

        print(
            f"🧠 [PatternAnalyzer] Insights generated for project {project_id} "
            f"({len(insights)} chars)"
        )

        return InsightsResponse(success=True, insights=insights)

    except Exception as e:
        print(f"❌ [PatternAnalyzer] insights failed for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
