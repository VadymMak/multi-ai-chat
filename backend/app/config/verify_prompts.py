"""
Verify Mode prompts.

Verify Mode makes fabrication mechanically detectable: a claim is only marked
`verified` when a model returns a VERBATIM quote AND that quote is found by exact
(normalized) substring search in the actually-fetched source text. The model is a
suspect, not a judge — see verify-mode-spec-final.md.

Two model-facing prompts:
  * EXTRACT_CLAIMS_PROMPT — step 1: split arbitrary text into atomic factual
    propositions, tag opinions (skipped), capture the stated source if any.
  * VERIFY_QUOTE_PROMPT  — step 4 (later phase): given a source text + one claim,
    return a verbatim supporting quote or "not_found". The quote is then checked
    by substring search in the pipeline, NOT trusted from the model.

Both run at temperature 0 and MUST return strict JSON.
"""

# =============================================================================
# STEP 1 — claim extraction
# =============================================================================

EXTRACT_CLAIMS_PROMPT = """You extract checkable factual claims from a piece of text.

Rules:
- One claim = one atomic, verifiable proposition. Split compound sentences.
- Opinions, recommendations, predictions and value judgements are NOT facts.
  Include them but mark them so they can be skipped, never verified.
- Capture the source ONLY if it is stated in the text for that claim:
  a URL, DOI, arXiv id, paper title, or document name. If no source is stated,
  set "source" to null. A missing source is a state, not an error — never invent one.
- Do not rephrase numbers; copy them exactly as written.
- Output STRICT JSON only. No prose, no markdown fences.

Output shape — a JSON array, each item:
{{
  "claim": "<the proposition, one sentence>",
  "source": "<url / doi / arxiv id / title / document name, or null>",
  "type": "fact" | "opinion"
}}

If there are no claims, return [].

TEXT TO ANALYZE:
---
{text}
---

Return the JSON array now."""


# =============================================================================
# STEP 4 — quote verification (used from a later phase)
# =============================================================================

VERIFY_QUOTE_PROMPT = """You check whether a source document supports a single claim.

You may ONLY support the claim by quoting the document verbatim. You may not
reason the claim into being supported. If the document does not contain text that
directly supports the claim, answer "not_found".

Rules:
- "quote" MUST be copied character-for-character from the document text below.
  Do not paraphrase, summarize, translate, or fix it.
- If no supporting passage exists, return {{"verdict": "not_found", "quote": ""}}.
- Output STRICT JSON only. No prose, no markdown fences.

Output shape:
{{"verdict": "supported" | "not_found", "quote": "<verbatim text from the document>"}}

CLAIM:
{claim}

DOCUMENT TEXT:
---
{document}
---

Return the JSON object now."""
