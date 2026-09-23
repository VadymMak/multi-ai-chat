"""
Verify Mode — manager.

Makes fabrication mechanically detectable. A claim is `verified` only when a
model returns a verbatim quote AND that quote is found by exact (normalized)
substring search in the actually-fetched source text. The model finds; the
mechanics decide. See verify-mode-spec-final.md.

PHASE 1 (this file): the single normalizer, claim extraction (step 1),
deterministic aggregation (step 5), and the orchestrator with the fetch=False
path. Steps 2–4 (resolve source / fetch / verify quote) are marked TODO and
currently route sourced claims to `unchecked` so nothing is ever falsely
`verified` before the gate exists.

Design notes carried from the spec / VesselManualBot prior art:
  * ONE normalizer, used for the source text, the claim, and the quote check.
    Three normalizers = three sets of false misses.
  * `verified` is narrow: source real, loadable, and containing a literal
    string the checker offered. It does NOT prove the quote entails the claim.
  * `refuted` means "not found in THIS source", NOT "the claim is false".
  * `unchecked` is mandatory and never collapses into the other two.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional

from app.providers.factory import ask_model
from app.config.verify_prompts import EXTRACT_CLAIMS_PROMPT

logger = logging.getLogger(__name__)

# Cheap, strong workhorse for the narrow steps (1 and, later, 4). Temp 0.
VERIFY_EXTRACT_MODEL = "gpt-4o-mini"

# ─────────────────────────────────────────────────────────────────
# The ONE normalizer — reuse for source text, claim, and quote check.
# ─────────────────────────────────────────────────────────────────
_SOFT_HYPHEN = "­"
_DASHES = {ord(c): "-" for c in "–—−‑‒―"}          # en/em/minus/figure/… → hyphen
_QUOTES = {
    ord("“"): '"', ord("”"): '"', ord("„"): '"', ord("‟"): '"',
    ord("‘"): "'", ord("’"): "'", ord("‚"): "'", ord("‛"): "'",
}


def normalize(text: Optional[str]) -> str:
    """Canonicalize text so a real quote survives PDF/unicode noise.

    Applied identically to the source document, the claim, and the candidate
    quote. Steps: NFKC → drop soft hyphens → unify dashes/quotes → join
    hyphenated line breaks → collapse all whitespace (incl. nbsp/narrow nbsp,
    which \\s matches in Python 3) → lowercase → strip.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text))
    t = t.replace(_SOFT_HYPHEN, "")
    t = t.translate(_DASHES)
    t = t.translate(_QUOTES)
    t = re.sub(r"(\w)-\s+(\w)", r"\1\2", t)   # "prop- er" / "prop-\ner" → "proper"
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def quote_supported(quote: Optional[str], document: Optional[str]) -> bool:
    """True iff the (normalized) quote is a substring of the (normalized) doc.

    This is the mechanical gate. It is deliberately not fuzzy: a model cannot
    talk its way past it. A too-short quote is rejected to avoid trivial matches.
    """
    nq = normalize(quote)
    if len(nq) < 8:          # guard against empty / trivially-present fragments
        return False
    return nq in normalize(document)


# ─────────────────────────────────────────────────────────────────
# JSON helpers — models sometimes wrap JSON in prose / fences.
# ─────────────────────────────────────────────────────────────────
def _loads_lenient(raw: str) -> Any:
    """Parse JSON, tolerating markdown fences and surrounding prose."""
    if raw is None:
        raise ValueError("empty model response")
    s = str(raw).strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        # last resort: grab the outermost [...] or {...}
        m = re.search(r"(\[.*\]|\{.*\})", s, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(1))


# ─────────────────────────────────────────────────────────────────
# STEP 1 — extract atomic claims
# ─────────────────────────────────────────────────────────────────
def extract_claims(text: str, model_key: str = VERIFY_EXTRACT_MODEL) -> List[Dict[str, Any]]:
    """Return a list of {claim, source|None, type: fact|opinion}.

    On unparseable model output, returns [] (logged). The caller reports the
    failure via stats rather than crashing.
    """
    prompt = EXTRACT_CLAIMS_PROMPT.format(text=text)
    raw = ask_model(
        messages=[{"role": "user", "content": prompt}],
        model_key=model_key,
        system_prompt=None,
        temperature=0.0,
        max_tokens=2000,
    )
    try:
        data = _loads_lenient(raw)
    except Exception as exc:
        logger.error("verify.extract_claims: JSON parse failed: %s | raw=%s", exc, str(raw)[:300])
        return []

    if not isinstance(data, list):
        logger.error("verify.extract_claims: expected list, got %s", type(data).__name__)
        return []

    out: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim", "")).strip()
        if not claim:
            continue
        src = item.get("source")
        src = str(src).strip() if src not in (None, "", "null") else None
        ctype = str(item.get("type", "fact")).strip().lower()
        ctype = "opinion" if ctype == "opinion" else "fact"
        out.append({"claim": claim, "source": src, "type": ctype})
    return out


# ─────────────────────────────────────────────────────────────────
# STEP 2 — deterministic source resolution (no model, no network).
# ─────────────────────────────────────────────────────────────────
# arXiv: YYMM.NNNN[N][vN], with optional "arXiv:" / "arxiv " prefix.
_ARXIV_RE = re.compile(
    r"^(?:arxiv[:\s/]+)?(\d{4}\.\d{4,5}(?:v\d+)?)$",
    re.IGNORECASE,
)
# DOI: starts with "10." followed by registrant / suffix.
_DOI_RE = re.compile(r"^10\.\d{4,9}/.+$", re.IGNORECASE)
# Bare http(s) URL.
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _resolve_source(source: str) -> Optional[Dict[str, Any]]:
    """Turn a stated source into a fetchable URL deterministically.

    Returns {"url": <url>, "origin": "stated"} or None when the source
    cannot be resolved to a URL (caller must mark the claim unchecked,
    reason "source_unresolvable").

    Rules:
    - We verify against the STATED source only. We never search for a
      "better" one (no confirmation-shopping). Searched URLs are tagged
      origin="search" — but that is a Phase 2b concern; here origin is
      always "stated".
    - arXiv → ar5iv HTML (full text), NOT arxiv.org/abs (abstract only).
    - No model call; fully deterministic.
    """
    s = (source or "").strip()
    if not s:
        return None

    # Bare http(s) URL — use as-is.
    if _URL_RE.match(s):
        return {"url": s, "origin": "stated"}

    # arXiv id: "2209.07663", "arXiv:2209.07663", "arxiv: 2209.07663", …
    m = _ARXIV_RE.match(s)
    if m:
        arxiv_id = m.group(1)
        return {"url": f"https://ar5iv.org/abs/{arxiv_id}", "origin": "stated"}

    # DOI: "10.1145/3123456.789"
    if _DOI_RE.match(s):
        return {"url": f"https://doi.org/{s}", "origin": "stated"}

    # Bare paper title or anything else → unresolvable (Phase 2b optional).
    return None


# ─────────────────────────────────────────────────────────────────
# STEPS 3–4 — fetch source text / verify quote.
# TODO(phase 3): fetch via httpx; failures → unchecked with reason.
# TODO(phase 4): VERIFY_QUOTE_PROMPT on retrieval-narrowed text,
#   then quote_supported() against the FULL document (mechanical gate).
# Until phase 3 is implemented, a resolved claim stays in `unchecked`
# — nothing is ever falsely `verified` before the gate exists.
# ─────────────────────────────────────────────────────────────────
def _verify_sourced_claim(claim: str, source: str, high_assurance: bool = False) -> Optional[Dict[str, Any]]:
    """Phase 2: resolve source. Phases 3-4 not yet implemented.

    Returns a result dict (never None) so the orchestrator can read the
    reason. A resolved-but-unfetched claim always lands in `unchecked`.
    """
    resolved = _resolve_source(source)
    if resolved is None:
        return {"bucket": "unchecked", "reason": "source_unresolvable"}
    # Phase 3 (fetch) not yet implemented.
    return {"bucket": "unchecked", "reason": "fetch_not_implemented", "resolved_url": resolved["url"]}


# ─────────────────────────────────────────────────────────────────
# STEP 5 — deterministic aggregation (no model)
# ─────────────────────────────────────────────────────────────────
def _empty_report(source_text_echo: str) -> Dict[str, Any]:
    return {
        "verified": [],
        "refuted": [],
        "unchecked": [],
        "stats": {
            "claims_total": 0,
            "verified": 0,
            "refuted": 0,
            "unchecked": 0,
            "opinions_skipped": 0,
            "fetch_failures": 0,
        },
        "source_text_echo": source_text_echo,
        "cost_usd": None,        # not tracked in phase 1
        "elapsed_s": 0.0,
    }


# ─────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────
def run_verify(
    text: str,
    max_claims: int = 20,
    fetch: bool = True,
    high_assurance: bool = False,
) -> Dict[str, Any]:
    """Verify factual claims in `text`. Returns a VerifyReport dict.

    PHASE 2: extraction (step 1) + source resolution (step 2) are live.
    Fetch/quote-gate (steps 3–4) not yet implemented — sourced claims land
    in `unchecked` with reason "fetch_not_implemented" or
    "source_unresolvable". No claim is ever falsely `verified`.
      * no stated source             → reason "no_source_given"
      * fetch disabled (fetch=False) → reason "fetch_disabled"
      * source unresolvable          → reason "source_unresolvable"
      * resolved but unfetched       → reason "fetch_not_implemented"
    """
    t0 = time.perf_counter()
    text = (text or "").strip()
    report = _empty_report(source_text_echo=text)
    if not text:
        report["elapsed_s"] = round(time.perf_counter() - t0, 3)
        return report

    claims = extract_claims(text)
    opinions = [c for c in claims if c["type"] == "opinion"]
    facts = [c for c in claims if c["type"] == "fact"]

    if len(facts) > max_claims:
        facts = facts[:max_claims]

    for c in facts:
        claim, source = c["claim"], c["source"]

        if source and fetch:
            result = _verify_sourced_claim(claim, source, high_assurance=high_assurance)
            if result["bucket"] == "verified":
                report["verified"].append({
                    "claim": claim, "source": source,
                    "quote": result["quote"],
                    "source_origin": result.get("source_origin", "stated"),
                })
            elif result["bucket"] == "refuted":
                report["refuted"].append({
                    "claim": claim, "source": source,
                    "reason": "not_found_in_text",
                })
            else:
                report["unchecked"].append({
                    "claim": claim, "source": source,
                    "reason": result.get("reason", "unchecked"),
                })
        elif source and not fetch:
            report["unchecked"].append({
                "claim": claim, "source": source, "reason": "fetch_disabled",
            })
        else:
            report["unchecked"].append({
                "claim": claim, "source": None, "reason": "no_source_given",
            })

    report["stats"] = {
        "claims_total": len(facts),
        "verified": len(report["verified"]),
        "refuted": len(report["refuted"]),
        "unchecked": len(report["unchecked"]),
        "opinions_skipped": len(opinions),
        "fetch_failures": 0,     # populated once step 3 exists
    }
    report["elapsed_s"] = round(time.perf_counter() - t0, 3)
    return report
