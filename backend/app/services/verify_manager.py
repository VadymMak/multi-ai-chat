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
from app.config.verify_prompts import EXTRACT_CLAIMS_PROMPT, VERIFY_QUOTE_PROMPT

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
# STEP 4 — the mechanical quote gate.
# ─────────────────────────────────────────────────────────────────
_SMALL_DOC_CHARS = 6_000    # pass whole to model below this; chunk above
_NARROW_BUDGET   = 6_000    # target chars sent to model when narrowing
_CHUNK_SIZE      = 1_200    # chars per chunk
_CHUNK_OVERLAP   = 200      # overlap between adjacent chunks

# Minimal English stop-words for salient-term scoring.
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "shall", "must", "can", "that", "this", "these", "those", "it", "its",
    "as", "if", "so", "not", "no", "nor",
})


def _salient_words(text: str) -> frozenset:
    """Normalised meaningful words (len>3, not stop-words)."""
    return frozenset(w for w in normalize(text).split() if len(w) > 3 and w not in _STOP_WORDS)


def _narrow_to_relevant(document: str, claim: str) -> tuple:
    """Return (narrowed_text, used_narrowing: bool).

    Small documents are passed whole. For large ones, overlapping chunks are
    scored by keyword overlap with the claim and the top chunks (up to
    _NARROW_BUDGET chars) are returned in document order.
    The full document is never modified — this only affects what the MODEL sees.
    The gate always runs on the FULL document.
    """
    if len(document) <= _SMALL_DOC_CHARS:
        return document, False

    claim_words = _salient_words(claim)

    # Build overlapping chunks.
    chunks: List[str] = []
    start = 0
    while start < len(document):
        end = min(start + _CHUNK_SIZE, len(document))
        chunks.append(document[start:end])
        if end == len(document):
            break
        start += _CHUNK_SIZE - _CHUNK_OVERLAP

    # Score chunks by keyword overlap; select top ones up to _NARROW_BUDGET.
    scored = sorted(
        enumerate(chunks),
        key=lambda iv: -len(claim_words & frozenset(normalize(iv[1]).split())),
    )
    selected_idx: List[int] = []
    total = 0
    for idx, chunk in scored:
        if total >= _NARROW_BUDGET:
            break
        selected_idx.append(idx)
        total += len(chunk)

    if not selected_idx:
        return document[:_NARROW_BUDGET], True

    selected_idx.sort()                         # restore document order
    narrowed = "\n\n[…]\n\n".join(chunks[i] for i in selected_idx)
    return narrowed, True


def _find_quote(claim: str, document: str) -> Optional[str]:
    """Find a verbatim quote supporting `claim` in `document`.

    Steps:
    1. Narrow what the MODEL sees to relevant passages (or pass whole if small).
    2. Call ask_model with VERIFY_QUOTE_PROMPT at temperature 0.
    3. THE GATE: accept the returned quote ONLY if quote_supported(quote, document)
       is True — where `document` is the FULL fetched text, never the narrowed
       passages. A model cannot pass this gate by hallucinating.

    Returns the verbatim quote string or None.
    """
    context, _ = _narrow_to_relevant(document, claim)

    prompt = VERIFY_QUOTE_PROMPT.format(claim=claim, document=context)
    raw = ask_model(
        messages=[{"role": "user", "content": prompt}],
        model_key="gpt-4o-mini",
        system_prompt=None,
        temperature=0.0,
        max_tokens=500,
    )

    try:
        data = _loads_lenient(raw)
    except Exception as exc:
        logger.error("_find_quote: JSON parse failed: %s | raw=%s", exc, str(raw)[:300])
        return None

    verdict = str(data.get("verdict", "")).strip()
    quote   = str(data.get("quote",   "")).strip()

    # THE GATE — checked against the FULL document, not the narrowed context.
    if verdict == "supported" and quote_supported(quote, document):
        return quote
    return None


def _verify_sourced_claim(claim: str, source: str, high_assurance: bool = False) -> Dict[str, Any]:
    """All phases active: resolve → fetch → quote gate.

    Fetch failures carry "_is_fetch_failure": True for stats counting.
    A claim is `verified` only when the mechanical gate passes.
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

    full_text = fetch_result["text"]
    used_narrowing = len(full_text) > _SMALL_DOC_CHARS

    quote = _find_quote(claim, full_text)

    if quote is not None:
        return {"bucket": "verified", "quote": quote, "source_origin": resolved["origin"]}

    # Fallback: keyword scan validates the refutation when narrowing was used.
    # If none of the claim's salient terms appear in the FULL text at all,
    # the refutation is definitive; if they do appear, we still refute because
    # the quote gate failed — but the scan gives confidence the refusal is sound.
    if used_narrowing:
        salient = _salient_words(claim)
        full_norm = normalize(full_text)
        if salient and not any(w in full_norm for w in salient):
            logger.debug("_verify_sourced_claim: salient terms absent from full text (clean refutation)")

    return {"bucket": "refuted", "reason": "not_found_in_text"}


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

    ALL FOUR PHASES ACTIVE: extraction → source resolution → fetch → quote gate.
    A claim reaches `verified` only when a model-returned verbatim quote passes
    the mechanical substring gate against the full fetched source text.
      * no stated source              → unchecked/no_source_given
      * fetch disabled (fetch=False)  → unchecked/fetch_disabled
      * source unresolvable           → unchecked/source_unresolvable
      * fetch failure                 → unchecked/<fetch reason>; fetch_failures++
      * quote gate fails              → refuted/not_found_in_text
      * quote gate passes             → verified with verbatim quote
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
