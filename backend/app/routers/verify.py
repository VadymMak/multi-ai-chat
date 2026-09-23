"""
Verify Router
Endpoint for Verify Mode — mechanical fact-checking of claims in a text.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional

from app.services.verify_manager import run_verify

router = APIRouter(tags=["Verify"])


class VerifyRequest(BaseModel):
    text: str
    max_claims: int = 20
    fetch: bool = True
    high_assurance: bool = False

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("text cannot be empty")
        return value

    @field_validator("max_claims")
    @classmethod
    def max_claims_valid(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_claims must be at least 1")
        if value > 50:
            raise ValueError("max_claims cannot exceed 50")
        return value


@router.post("/verify")
def verify(data: VerifyRequest):
    """
    Extract factual claims from `data.text` and check them against their sources.

    Returns a VerifyReport with three buckets (verified / refuted / unchecked)
    and a stats block carrying denominators. Manual, cost-bearing call — not for
    automatic use on every message.
    """
    try:
        return run_verify(
            text=data.text,
            max_claims=data.max_claims,
            fetch=data.fetch,
            high_assurance=data.high_assurance,
        )
    except Exception as e:
        print(f"❌ Error in /verify: {e}")
        raise HTTPException(status_code=500, detail=f"Verify failed: {str(e)}")
