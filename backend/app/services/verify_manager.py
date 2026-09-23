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

import html as _html
import json
import logging
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional

import httpx

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
# STEP 3 — fetch source text.
# ─────────────────────────────────────────────────────────────────
_FETCH_TEXT_CAP = 200_000          # max chars to keep from a fetched document
_FETCH_TIMEOUT  = 20.0             # seconds per attempt
_FETCH_RETRIES  = 1                # one retry after the first attempt

# HTTP status → typed failure reason.
_STATUS_REASON: Dict[int, str] = {
    401: "robots_denied",
    402: "paywall",
    403: "robots_denied",
    404: "http_404",
}

# Fetch failure reasons (subset of unchecked reasons that count as fetch_failures).
_FETCH_FAILURE_REASONS = frozenset({
    "http_404", "timeout", "paywall", "robots_denied", "pdf_unparseable", "fetch_error",
})

_FETCH_UA = "Mozilla/5.0 (compatible; VerifyBot/1.0)"


def _extract_html_text(content: bytes, encoding: str = "utf-8") -> str:
    """Strip HTML tags/scripts/styles; return plain text capped at _FETCH_TEXT_CAP."""
    try:
        text = content.decode(encoding, errors="replace")
    except Exception:
        text = content.decode("latin-1", errors="replace")
    text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_FETCH_TEXT_CAP]


def _extract_pdf_text(content: bytes) -> Optional[str]:
    """Extract plain text from PDF bytes via PyMuPDF (already a dependency)."""
    try:
        import fitz  # type: ignore  # PyMuPDF
        doc = fitz.open(stream=content, filetype="pdf")
        parts = [page.get_text() for page in doc]
        text = "\n".join(parts).strip()
        return text[:_FETCH_TEXT_CAP] if text else None
    except Exception as exc:
        logger.debug("_extract_pdf_text failed: %s", exc)
        return None


def _fetch_text(url: str) -> Dict[str, Any]:
    """Fetch `url` and return extracted plain text or a typed failure reason.

    Returns {"ok": True, "text": <str>} or {"ok": False, "reason": <str>}.
    Failure reasons: "http_404", "timeout", "paywall", "robots_denied",
                     "pdf_unparseable", "fetch_error".
    One retry on network errors. Text capped at _FETCH_TEXT_CAP chars.
    Never infers content — no text means no verification.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(_FETCH_RETRIES + 1):
        try:
            with httpx.Client(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": _FETCH_UA})

            if resp.status_code in _STATUS_REASON:
                return {"ok": False, "reason": _STATUS_REASON[resp.status_code]}
            if resp.status_code != 200:
                return {"ok": False, "reason": "fetch_error"}

            content_type = resp.headers.get("content-type", "").lower()
            is_pdf = "pdf" in content_type or url.lower().split("?")[0].endswith(".pdf")

            if is_pdf:
                text = _extract_pdf_text(resp.content)
                if text is None:
                    return {"ok": False, "reason": "pdf_unparseable"}
                return {"ok": True, "text": text}

            text = _extract_html_text(resp.content, resp.encoding or "utf-8")
            if not text.strip():
                return {"ok": False, "reason": "fetch_error"}
            return {"ok": True, "text": text}

        except httpx.TimeoutException as exc:
            last_exc = exc
            logger.debug("_fetch_text timeout attempt %d for %s", attempt + 1, url)
        except Exception as exc:
            last_exc = exc
            logger.warning("_fetch_text error attempt %d for %s: %s", attempt + 1, url, exc)

    if isinstance(last_exc, httpx.TimeoutException):
        return {"ok": False, "reason": "timeout"}
    return {"ok": False, "reason": "fetch_error"}


# ─────────────────────────────────────────────────────────────────
# STEP 4 — quote gate (Phase 4, not yet implemented).
# TODO(phase 4): VERIFY_QUOTE_PROMPT on retrieval-narrowed text,
#   then quote_supported() against the FULL document (mechanical gate).
# ─────────────────────────────────────────────────────────────────
def _verify_sourced_claim(claim: str, source: str, high_assurance: bool = False) -> Dict[str, Any]:
    """Phase 3: resolve source + fetch text. Phase 4 (quote gate) not yet implemented.

    Returns a result dict. Fetch failures carry "_is_fetch_failure": True so
    the orchestrator can count them separately.
    A successfully fetched claim stays in `unchecked` until Phase 4 adds the gate.
    """
    resolved = _resolve_source(source)
    if resolved is None:
        return {"bucket": "unchecked", "reason": "source_unresolvable"}

    fetch_result = _fetch_text(resolved["url"])
    if not fetch_result["ok"]:
        return {
            "bucket": "unchecked",
            "reason": fetch_result["reason"],
            "_is_fetch_failure": True,
        }

    # Phase 4 (quote gate) not yet implemented — stash text for the next phase.
    return {
        "bucket": "unchecked",
        "reason": "quote_check_not_implemented",
        "_fetched_text": fetch_result["text"],
    }


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

    PHASE 3: extraction (step 1) + source resolution (step 2) + fetch (step 3)
    are live. Quote gate (step 4) not yet implemented — successfully fetched
    claims land in `unchecked/quote_check_not_implemented`. No claim is ever
    falsely `verified`.
      * no stated source              → unchecked/no_source_given
      * fetch disabled (fetch=False)  → unchecked/fetch_disabled
      * source unresolvable           → unchecked/source_unresolvable
      * fetch failure                 → unchecked/<fetch reason>; fetch_failures++
      * fetched, gate not impl.       → unchecked/quote_check_not_implemented
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

    fetch_failures = 0
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
                if result.get("_is_fetch_failure"):
                    fetch_failures += 1
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
        "fetch_failures": fetch_failures,
    }
    report["elapsed_s"] = round(time.perf_counter() - t0, 3)
    return report
