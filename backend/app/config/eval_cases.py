"""
Eval harness cases — mechanical asserts only, no LLM judge.

Each case: name, suite, kind, description, input dict, assert key + params.
Runner dispatch is in app/services/eval_runner.py.

Suites:
  retrieval  — hybrid_search returns expected file / does not return noise file
  context    — build_smart_context is non-empty, under budget, has structure markers
  verify     — quote_supported discriminates fabricated vs. real verbatim quotes
"""

# Shared document used for verify suite (Monolith paper excerpt, same as test_verify_core.py)
_MONOLITH_DOC = (
    "Monolith uses a collisionless embedding table to support online learning "
    "with real-time updates, allowing the recommendation system to adapt rapidly "
    "to changing user preferences without batch retraining."
)

EVAL_CASES = [
    # ─── retrieval suite ─────────────────────────────────────────────────────
    {
        "name": "retrieval_debate_hit",
        "suite": "retrieval",
        "kind": "hybrid_search",
        "description": (
            "hybrid_search('debate mode orchestration manager', project=20) "
            "→ debate_manager.py appears in top-5 results"
        ),
        "input": {
            "query": "debate mode orchestration manager",
            "project_id": 20,
            "top_n": 5,
        },
        # assert: any of the top-N file_path values contains expected_file
        "assert": "file_in_top_n",
        "expected_file": "debate_manager.py",
    },
    {
        "name": "retrieval_miss_control",
        "suite": "retrieval",
        "kind": "hybrid_search",
        "description": (
            "hybrid_search on a nonsense query → debate_manager.py is NOT in top-5 "
            "(guards against 'everything matches' regression)"
        ),
        "input": {
            "query": "completely unrelated xyzzy quantum blockchain frobnicate",
            "project_id": 20,
            "top_n": 5,
        },
        # assert: none of the top-N file_path values contains expected_file
        "assert": "file_not_in_top_n",
        "expected_file": "debate_manager.py",
    },
    # ─── context suite ───────────────────────────────────────────────────────
    {
        "name": "context_budget",
        "suite": "context",
        "kind": "build_smart_context",
        "description": (
            "build_smart_context(project=20) → result is non-empty AND ≤ 20 000 chars "
            "(≈5 000 tokens; confirms the context engine trims to budget)"
        ),
        "input": {
            "query": "how does debate mode work",
            "project_id": 20,
            "role_id": 0,
        },
        "assert": "non_empty_under_budget",
        "max_chars": 20_000,
    },
    {
        "name": "context_has_structure",
        "suite": "context",
        "kind": "build_smart_context",
        "description": (
            "build_smart_context(project=20) → output contains at least one structural "
            "section marker (RELEVANT SKILLS / PROJECT STRUCTURE / KNOWLEDGE GRAPH)"
        ),
        "input": {
            "query": "how does debate mode work",
            "project_id": 20,
            "role_id": 0,
        },
        "assert": "contains_markers",
        # at least one marker must appear in the returned context string
        "markers": ["RELEVANT SKILLS", "PROJECT STRUCTURE", "KNOWLEDGE GRAPH"],
    },
    # ─── verify suite ────────────────────────────────────────────────────────
    {
        "name": "verify_refuted",
        "suite": "verify",
        "kind": "quote_supported",
        "description": (
            "quote_supported(Gemini-fabricated claim, Monolith doc) → False "
            "(the fabricated passage is not present in the source text)"
        ),
        "input": {
            "quote": "guaranteed impression pool of 300-500 via a multi-armed bandit",
            "document": _MONOLITH_DOC,
        },
        "assert": "is_false",
    },
    {
        "name": "verify_verified",
        "suite": "verify",
        "kind": "quote_supported",
        "description": (
            "quote_supported(verbatim excerpt, Monolith doc) → True "
            "(the real quote IS present — mandatory true-positive per spec 2.3)"
        ),
        "input": {
            "quote": "collisionless embedding table to support online learning",
            "document": _MONOLITH_DOC,
        },
        "assert": "is_true",
    },
]
