"""
Prediction API Endpoints — structural impact analysis based on dependency graph.

File: backend/app/routers/prediction.py
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.deps import get_current_active_user, get_db
from app.memory.models import User
from app.services.prediction_service import PredictionService

router = APIRouter(prefix="/prediction", tags=["prediction"])


# ==================== REQUEST / RESPONSE MODELS ====================


class ImpactRequest(BaseModel):
    """Request for impact analysis"""
    project_id: int
    changed_files: List[str]


class ImpactResponse(BaseModel):
    """Response with impact analysis"""
    success: bool
    directly_affected: List[str]
    transitively_affected: List[str]
    risk_score: int
    suggestions: List[str]
    circular_warnings: List[str]
    history_id: Optional[int] = None


class ErrorRiskRequest(BaseModel):
    """Request for error-prone file analysis"""
    project_id: int
    changed_files: List[str]


class ErrorRiskItem(BaseModel):
    """Single file error risk entry"""
    file_path: str
    historical_errors: int
    common_error_types: List[str]
    last_solution: Optional[str] = None


class ErrorRiskResponse(BaseModel):
    """Response with error risk analysis"""
    success: bool
    risky_files: List[ErrorRiskItem]
    count: int


class SummaryRequest(BaseModel):
    """Request for AI-prompt summary"""
    project_id: int
    changed_files: List[str]


class SummaryResponse(BaseModel):
    """Response with formatted AI-prompt summary"""
    success: bool
    summary: str


class FeedbackRequest(BaseModel):
    """Record accuracy feedback for a past prediction"""
    history_id: int
    project_id: int
    accuracy_score: float  # 0.0 = wrong, 1.0 = correct


class FeedbackResponse(BaseModel):
    """Result of recording feedback"""
    success: bool
    recorded: bool


class PredictionStatsResponse(BaseModel):
    """Response with prediction usage statistics"""
    success: bool
    total_predictions: int
    avg_accuracy: Optional[float] = None
    last_prediction_at: Optional[str] = None
    active_cache_entries: int


# ==================== ENDPOINTS ====================


@router.post("/impact", response_model=ImpactResponse)
async def predict_impact(
    request: ImpactRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Predict which files are affected when the given files change.

    Uses the dependency graph to find:
    - directly_affected: files that directly import any changed file
    - transitively_affected: files reachable through the dependency chain
    - risk_score: 0-100 based on affected file counts
    - suggestions: which files to review
    - circular_warnings: if changes touch a circular dependency
    """
    try:
        service = PredictionService(db)

        impact = service.predict_impact(
            project_id=request.project_id,
            changed_files=request.changed_files,
        )

        # Persist to history
        history_id = service.save_prediction_history(
            project_id=request.project_id,
            changed_files=request.changed_files,
            predicted_impact=impact,
        )

        print(
            f"⚡ [Prediction] Impact request for project {request.project_id}: "
            f"{len(request.changed_files)} changed, "
            f"{len(impact['directly_affected'])} direct, "
            f"{len(impact['transitively_affected'])} transitive"
        )

        return ImpactResponse(
            success=True,
            directly_affected=impact["directly_affected"],
            transitively_affected=impact["transitively_affected"],
            risk_score=impact["risk_score"],
            suggestions=impact["suggestions"],
            circular_warnings=impact["circular_warnings"],
            history_id=history_id,
        )

    except Exception as e:
        print(f"❌ [Prediction] Impact analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/error-risk", response_model=ErrorRiskResponse)
async def predict_error_risk(
    request: ErrorRiskRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Cross-reference changed files with learned error history.
    Returns files that have historically been error-prone.
    """
    try:
        service = PredictionService(db)

        risky = service.predict_error_prone_files(
            project_id=request.project_id,
            changed_files=request.changed_files,
        )

        print(
            f"🔍 [Prediction] Error risk for project {request.project_id}: "
            f"{len(risky)}/{len(request.changed_files)} files flagged"
        )

        return ErrorRiskResponse(
            success=True,
            risky_files=[ErrorRiskItem(**item) for item in risky],
            count=len(risky),
        )

    except Exception as e:
        print(f"❌ [Prediction] Error risk analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/summary", response_model=SummaryResponse)
async def get_prediction_summary(
    request: SummaryRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Generate a human-readable prediction summary suitable for AI prompt injection.

    Combines impact analysis + error history into a concise text block
    that can be prepended to any AI prompt for context-aware assistance.
    """
    try:
        service = PredictionService(db)

        summary = service.get_change_summary(
            project_id=request.project_id,
            changed_files=request.changed_files,
        )

        print(
            f"📋 [Prediction] Summary generated for project {request.project_id}, "
            f"{len(request.changed_files)} changed files"
        )

        return SummaryResponse(success=True, summary=summary)

    except Exception as e:
        print(f"❌ [Prediction] Summary generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/{project_id}", response_model=PredictionStatsResponse)
async def get_prediction_stats(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get prediction usage statistics for a project.
    Shows total predictions made, average accuracy, and cache status.
    """
    try:
        service = PredictionService(db)
        stats = service.get_prediction_stats(project_id)

        return PredictionStatsResponse(
            success=True,
            total_predictions=stats["total_predictions"],
            avg_accuracy=stats["avg_accuracy"],
            last_prediction_at=stats["last_prediction_at"],
            active_cache_entries=stats["active_cache_entries"],
        )

    except Exception as e:
        print(f"❌ [Prediction] Stats fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/feedback", response_model=FeedbackResponse)
async def record_prediction_feedback(
    request: FeedbackRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Record accuracy feedback for a past prediction.

    Call this after you know the actual outcome of a change to close
    the feedback loop. accuracy_score: 0.0 = prediction was wrong,
    1.0 = prediction was fully correct.

    Requires the history_id returned by POST /prediction/impact.
    """
    try:
        service = PredictionService(db)
        recorded = service.record_feedback(
            history_id=request.history_id,
            project_id=request.project_id,
            accuracy_score=request.accuracy_score,
        )
        return FeedbackResponse(success=True, recorded=recorded)
    except Exception as e:
        print(f"❌ [Prediction] Feedback recording failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== INTEGRATION HELPER ====================


def get_prediction_summary_for_prompt(
    db: Session,
    project_id: int,
    changed_files: List[str],
) -> str:
    """
    Helper for other routers to inject prediction context into AI prompts.

    Usage in vscode.py or agentic.py:
        from app.routers.prediction import get_prediction_summary_for_prompt

        prediction = get_prediction_summary_for_prompt(db, project_id, [file_path])
        prompt += prediction
    """
    try:
        service = PredictionService(db)
        return service.get_change_summary(project_id, changed_files)
    except Exception as e:
        print(f"⚠️ [Prediction] Failed to generate prompt summary: {e}")
        return ""
