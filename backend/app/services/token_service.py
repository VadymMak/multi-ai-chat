# app/services/token_service.py
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from app.config.settings import get_thresholds


def estimate_tokens(text: str, model: Optional[str] = None) -> int:
    """
    Very fast, dependency-free token estimator.
    Rule of thumb: ~4 characters per token on average across English/code mixes.
    We round up so short strings don't undercount.
    """
    if not text:
        return 0
    # Cheap pre-trim to avoid counting trailing whitespace
    n = len(text.strip())
    return max(1, math.ceil(n / 4))


def estimate_tokens_batch(parts: List[str], model: Optional[str] = None) -> Tuple[int, List[int]]:
    """
    Returns (total, per_part_counts).
    """
    per = [estimate_tokens(p, model=model) for p in parts]
    return sum(per), per


def preflight(
    inputs: List[str],
    *,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict[str, object]:
    """
    Compute soft/hard threshold flags for one request.
    This is intentionally model/provider-agnostic and extremely fast.

    Returns dict like:
    {
      "total": 123,
      "parts": [10, 20, 93],
      "soft_limit": 1500,
      "hard_limit": 3000,
      "near_soft": false,   # >= 80% of soft
      "over_soft": false,   # >= soft
      "over_hard": false,   # >= hard
    }
    """
    soft, hard = get_thresholds(model=model, provider=provider)
    total, parts = estimate_tokens_batch(inputs, model=model)

    near_soft = total >= int(soft * 0.80)
    over_soft = total >= soft
    over_hard = total >= hard

    return {
      "total": total,
      "parts": parts,
      "soft_limit": soft,
      "hard_limit": hard,
      "near_soft": near_soft,
      "over_soft": over_soft,
      "over_hard": over_hard,
    }
