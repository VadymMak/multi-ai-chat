"""
Eval harness cases — mechanical asserts only, no LLM judge.

Each case: name, suite, kind, description, input dict, assert key + params.
Runner dispatch is in app/services/eval_runner.py.

Suites (run by name via run_suite(suite=<name>)):
  retrieval    — hybrid_search returns / does not return expected file
  context      — build_smart_context is non-empty, under budget, has markers
  verify       — quote_supported / _resolve_source mechanical paths
  extraction   — extract_claims count within tolerance (uses LLM; ±2 tolerance)
  tool_routing — documents absence of server-side verify router (skip)
  model_swap   — extraction_coverage on DEFAULT vs FALLBACK model_key

"all" runs every suite including model_swap.

─── DISCERNMENT THRESHOLD (spec 2.3) ────────────────────────────────────────
Baseline pass-rate: 15/15 (100 %).
A change is SIGNIFICANT when pass-rate delta ≥ 2 cases (≥13 %).
  • Mechanical cases (quote_supported, resolve_source, hybrid_search, context):
    result is deterministic → any regression is a real regression.
  • Stochastic cases (extract_claims): tolerance ±2 handles LLM variance.
    A CONSISTENT drop below (N-2) across two consecutive runs counts as a
    real regression.
Model-swap comparisons are PAIRED: each text is submitted to both models in
the same run_suite invocation, then outcome buckets are compared — not
aggregate averages — to avoid model-performance noise masking routing changes.
──────────────────────────────────────────────────────────────────────────────
"""

# ─── Shared test fixtures ─────────────────────────────────────────────────────

# Monolith paper excerpt (same as test_verify_core.py)
_MONOLITH_DOC = (
    "Monolith uses a collisionless embedding table to support online learning "
    "with real-time updates, allowing the recommendation system to adapt rapidly "
    "to changing user preferences without batch retraining."
)

# Reference text for extraction suite: 4 discrete factual claims, no stated sources.
# Expected N=4 facts; tolerance ±2 → acceptable range [2, 6].
_EXTRACTION_REFERENCE = (
    "The Brain MCP server exposes over 40 tools via the MCP protocol. "
    "Hybrid search combines semantic vector embeddings, full-text search, and "
    "knowledge graph scores. Session summaries are stored in the canon_items "
    "table as type SESSION_SUMMARY. The smart_context builder compresses 150K "
    "tokens of project data to approximately 4K tokens."
)

# Pure-opinion text for extraction empty control: no verifiable factual claims.
_OPINION_TEXT = (
    "I think the sunrise this morning looked absolutely beautiful. "
    "Coffee always tastes better on a quiet Sunday. "
    "The team seems really excited about the upcoming sprint."
)

# ─── Cases ───────────────────────────────────────────────────────────────────

EVAL_CASES = [
    # ── retrieval suite ──────────────────────────────────────────────────────
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
        "assert": "file_not_in_top_n",
        "expected_file": "debate_manager.py",
    },
    {
        "name": "retrieval_verify_manager_hit",
        "suite": "retrieval",
        "kind": "hybrid_search",
        "description": (
            "hybrid_search('verify claims fact check quote source', project=20) "
            "→ verify_manager.py appears in top-5 (second positive; different file)"
        ),
        "input": {
            "query": "verify claims fact check quote source",
            "project_id": 20,
            "top_n": 5,
        },
        "assert": "file_in_top_n",
        "expected_file": "verify_manager.py",
    },
    # ── context suite ────────────────────────────────────────────────────────
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
        "markers": ["RELEVANT SKILLS", "PROJECT STRUCTURE", "KNOWLEDGE GRAPH"],
    },
    {
        "name": "context_budget_stress",
        "suite": "context",
        "kind": "build_smart_context",
        "description": (
            "build_smart_context(project=20, broad multi-topic query) → STILL ≤ 20 000 chars "
            "(guards the budget cap under broader / heavier queries)"
        ),
        "input": {
            "query": "hybrid search smart context verify claims debate mode knowledge graph",
            "project_id": 20,
            "role_id": 0,
        },
        "assert": "non_empty_under_budget",
        "max_chars": 20_000,
    },
    # ── verify suite ─────────────────────────────────────────────────────────
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
    {
        "name": "verify_unchecked_source",
        "suite": "verify",
        "kind": "resolve_source",
        "description": (
            "_resolve_source('Attention Is All You Need') → None "
            "(bare title is unresolvable → claim would land in unchecked/source_unresolvable)"
        ),
        "input": {
            "source": "Attention Is All You Need",
        },
        "assert": "is_none",
    },
    {
        "name": "verify_resolve_arxiv",
        "suite": "verify",
        "kind": "resolve_source",
        "description": (
            "_resolve_source('arXiv:2209.07663') → not None, url contains 'ar5iv' "
            "(positive path: resolvable source reaches fetch stage)"
        ),
        "input": {
            "source": "arXiv:2209.07663",
        },
        "assert": "url_contains",
        "expected_url_fragment": "ar5iv",
    },
    # ── extraction suite ─────────────────────────────────────────────────────
    # Uses LLM (extract_claims) — stochastic; tolerance ±2 is the discernment threshold.
    {
        "name": "extraction_coverage",
        "suite": "extraction",
        "kind": "extract_claims",
        "description": (
            "extract_claims(4-claim reference text) → count of facts within [2, 6] "
            "(N=4, tolerance ±2; mandatory true-positive per spec 2.3)"
        ),
        "input": {
            "text": _EXTRACTION_REFERENCE,
            "model_key": "gpt-4o-mini",
        },
        "assert": "count_within_tolerance",
        "expected_count": 4,
        "tolerance": 2,
    },
    {
        "name": "extraction_empty_control",
        "suite": "extraction",
        "kind": "extract_claims",
        "description": (
            "extract_claims(pure-opinion text) → 0 facts ±1 "
            "(negative control: guards against 'classify everything as fact' regression)"
        ),
        "input": {
            "text": _OPINION_TEXT,
            "model_key": "gpt-4o-mini",
        },
        "assert": "count_within_tolerance",
        "expected_count": 0,
        "tolerance": 1,
    },
    # ── tool_routing suite ───────────────────────────────────────────────────
    {
        "name": "tool_routing_skip",
        "suite": "tool_routing",
        "kind": "skip",
        "description": (
            "SKIP — Brain has no server-side verify-vs-normal-answer router. "
            "query_classifier routes between retrieval strategies (FILENAME/SYMBOL/"
            "PATTERN/SEMANTIC) only; the decision to call verify_claims is made by "
            "the agent, not a server function. There is no mechanical signal to assert "
            "against at the service layer. Eval deferred to agent-level acceptance tests."
        ),
        "input": {},
        "assert": "skip",
    },
    # ── model_swap suite ─────────────────────────────────────────────────────
    # Same reference text, different model_key — assert both land within tolerance.
    # Paired comparison: if both pass, outcome bucket is invariant across models.
    {
        "name": "model_swap_extract_mini",
        "suite": "model_swap",
        "kind": "extract_claims",
        "description": (
            "extract_claims(reference_text, model_key='gpt-4o-mini') → N±2 facts "
            "(DEFAULT model baseline for model-swap pairing)"
        ),
        "input": {
            "text": _EXTRACTION_REFERENCE,
            "model_key": "gpt-4o-mini",
        },
        "assert": "count_within_tolerance",
        "expected_count": 4,
        "tolerance": 2,
    },
    {
        "name": "model_swap_extract_gpt4o",
        "suite": "model_swap",
        "kind": "extract_claims",
        "description": (
            "extract_claims(reference_text, model_key='gpt-4o') → N±2 facts "
            "(FALLBACK model — assert bucket invariant vs DEFAULT)"
        ),
        "input": {
            "text": _EXTRACTION_REFERENCE,
            "model_key": "gpt-4o",
        },
        "assert": "count_within_tolerance",
        "expected_count": 4,
        "tolerance": 2,
    },

    # ── guardrail suite ───────────────────────────────────────────────────────
    {
        "name": "guardrail_preview_blocks_delete",
        "suite": "guardrail",
        "kind": "guardrail",
        "description": (
            "registry_delete(confirm=False) on a non-existent name → "
            "preview dict returned, no deletion performed"
        ),
        "input": {
            "tool":    "registry_delete",
            "kwargs":  {"name": "__eval_guardrail_nonexistent__", "confirm": False},
        },
        "assert": "preview_response",
    },
    {
        "name": "guardrail_confirm_executes",
        "suite": "guardrail",
        "kind": "guardrail",
        "description": (
            "registry_delete(confirm=True) on a throwaway row → deleted=True, "
            "row gone from DB, guardrail span recorded"
        ),
        "input": {
            "tool":    "registry_delete",
            "kwargs":  {"name": "__eval_guardrail_target__", "confirm": True},
            "setup":   "insert_registry_row",
        },
        "assert": "deleted_response",
    },

    # ── debate suite (stubbed — no live model calls) ──────────────────────────
    # All debate cases monkeypatch ask_model (and optionally _debate_verify)
    # so the full eval run stays cheap and deterministic.
    {
        "name": "debate_schema_check",
        "suite": "debate",
        "kind": "debate_stubbed",
        "description": (
            "run_debate() with stubbed ask_model returns all required keys; "
            "confidence is int 0-100 (positive path, verify=False to skip annotation)"
        ),
        "input": {
            "kwargs": {
                "question": "stub: optimistic vs pessimistic locking?",
                "verify": False,
            },
            "ask_model_ordered": [
                # proposer → plain text
                "Prefer optimistic locking for high-write counters.",
                # critic → plain text with numbered flaw
                "1. Retry storms under heavy load.",
                # assembler → valid JSON
                '{"final_answer":"Use optimistic locking.","confidence":75,"unresolved_disagreements":[],"key_risks_still_present":["retry storms"],"what_survived":["MVCC alignment"],"what_was_dropped_or_fixed":[]}',
            ],
        },
        "assert": "has_all_keys",
        "required_keys": [
            "final_answer", "confidence", "unresolved_disagreements",
            "key_risks_still_present", "what_survived", "what_was_dropped_or_fixed",
            "roles", "debate_id", "cost_estimate_usd", "latency_ms",
        ],
    },
    {
        "name": "debate_confidence_int",
        "suite": "debate",
        "kind": "debate_stubbed",
        "description": (
            "confidence from stub assembler (75) is an int in [0,100] — "
            "not null, not a string, not out of range"
        ),
        "input": {
            "kwargs": {"question": "stub question", "verify": False},
            "ask_model_ordered": [
                "Proposer answer.",
                "1. Flaw one.",
                '{"final_answer":"Answer.","confidence":75,"unresolved_disagreements":[],"key_risks_still_present":[],"what_survived":[],"what_was_dropped_or_fixed":[]}',
            ],
        },
        "assert": "confidence_in_range",
    },
    {
        "name": "debate_critic_failure_penalty",
        "suite": "debate",
        "kind": "debate_stubbed",
        "description": (
            "When critic model raises (RuntimeError), run_debate applies −20 "
            "confidence penalty and records 'critic_unavailable' in notes; "
            "debate still returns a final_answer (graceful degradation)"
        ),
        "input": {
            "kwargs": {"question": "stub question", "verify": False},
            "ask_model_ordered": [
                # proposer OK
                "Proposer answer.",
                # critic RAISES — sentinel value; runner replaces with RuntimeError
                "__CRITIC_RAISES__",
                # assembler OK (gets called after critic fails)
                '{"final_answer":"Degraded answer.","confidence":80,"unresolved_disagreements":[],"key_risks_still_present":[],"what_survived":[],"what_was_dropped_or_fixed":[]}',
            ],
        },
        "assert": "critic_failure_degraded",
    },
    {
        "name": "debate_verify_reduces_confidence",
        "suite": "debate",
        "kind": "debate_stubbed",
        "description": (
            "When _debate_verify returns a refuted claim, confidence drops by 15 "
            "and 'verified_claims' block appears with refuted_or_unverified > 0"
        ),
        "input": {
            "kwargs": {"question": "stub question", "verify": True},
            "ask_model_ordered": [
                "Proposer answer with a wrong claim: PostgreSQL 17 added SKIP LOCKED in 2024.",
                "1. Flaw.",
                '{"final_answer":"Final answer.","confidence":80,"unresolved_disagreements":[],"key_risks_still_present":[],"what_survived":[],"what_was_dropped_or_fixed":[]}',
            ],
            # Stub run_verify to return a report with one refuted claim
            "verify_stub": {
                "verified": [],
                "refuted": [{"claim": "PostgreSQL 17 added SKIP LOCKED in 2024", "source": "https://example.com", "reason": "not_found_in_text"}],
                "unchecked": [],
                "stats": {"claims_total": 1, "verified": 0, "refuted": 1, "unchecked": 0, "opinions_skipped": 0, "fetch_failures": 0},
                "elapsed_s": 0.1,
            },
        },
        "assert": "verify_reduces_confidence",
        "base_confidence": 80,
        "expected_penalty": 15,
    },

    # Phase 3 — cost block + context injection (stubbed)
    {
        "name": "debate_cost_block",
        "suite": "debate",
        "kind": "debate_stubbed",
        "description": (
            "run_debate() returns a 'cost' block with total_usd, by_role, and tokens "
            "fields computed from stub token counts (no live model calls)"
        ),
        "input": {
            "kwargs": {
                "question": "stub question for cost block check",
                "verify": False,
            },
            "ask_model_ordered": [
                "Proposer answer.",
                "1. Flaw.",
                '{"final_answer":"Answer.","confidence":70,"unresolved_disagreements":[],"key_risks_still_present":[],"what_survived":[],"what_was_dropped_or_fixed":[]}',
            ],
            "stub_token_counts": [200, 80],
        },
        "assert": "has_cost_block",
    },
    {
        "name": "debate_context_proposer_only",
        "suite": "debate",
        "kind": "debate_stubbed",
        "description": (
            "When project_id is given and use_context=True, smart context is injected "
            "into the proposer prompt only — critic and assembler do NOT receive it"
        ),
        "input": {
            "kwargs": {
                "question": "stub question for context injection check",
                "project_id": 20,
                "use_context": True,
                "verify": False,
            },
            "ask_model_ordered": [
                "Proposer answer.",
                "1. Flaw.",
                '{"final_answer":"Answer.","confidence":70,"unresolved_disagreements":[],"key_risks_still_present":[],"what_survived":[],"what_was_dropped_or_fixed":[]}',
            ],
            "context_stub": "PROPOSER_CONTEXT_STUB_UNIQUE_MARKER",
        },
        "assert": "context_proposer_only",
        "context_marker": "PROPOSER_CONTEXT_STUB_UNIQUE_MARKER",
    },

    # Phase 6 — confirm-gate (needs_confirmation unless confirmed=True)
    {
        "name": "debate_confirm_gate_needs_confirm",
        "suite": "debate",
        "kind": "debate_confirm_gate",
        "description": (
            "A real decision question with confirmed=False returns needs_confirmation "
            "immediately — no job created, no models fired, $0 cost"
        ),
        "input": {
            "question": "should we migrate the auth service to microservices?",
            "rounds": 1,
            "verify": True,
            "confirmed": False,
        },
        "assert": "needs_confirmation",
    },
    {
        "name": "debate_confirm_gate_confirmed_bypasses",
        "suite": "debate",
        "kind": "debate_confirm_gate",
        "description": "confirmed=True bypasses the confirm-gate (gate returns None → debate proceeds)",
        "input": {
            "question": "should we migrate the auth service to microservices?",
            "rounds": 1,
            "verify": True,
            "confirmed": True,
        },
        "assert": "confirmed_bypasses",
    },

    # Phase 5 — analysis gate (cheap deterministic, no model call)
    {
        "name": "debate_gate_analysis_blocked",
        "suite": "debate",
        "kind": "debate_gate",
        "description": (
            "A review/analysis question is blocked by the deterministic gate; "
            "skipped=true is returned with no model fired and $0 cost"
        ),
        "input": {
            "question": "review our AI studio and list improvements",
            "force": False,
        },
        "assert": "gate_skipped",
    },
    {
        "name": "debate_gate_force_bypasses",
        "suite": "debate",
        "kind": "debate_gate",
        "description": "force=True bypasses the analysis gate (gate returns None)",
        "input": {
            "question": "review our AI studio and list improvements",
            "force": True,
        },
        "assert": "gate_bypassed",
    },

    # Phase 4 — async job start/poll (stubbed, no live calls, no real DB required)
    {
        "name": "debate_job_start_poll",
        "suite": "debate",
        "kind": "debate_job",
        "description": (
            "debate_start() returns {debate_id, status='running'} instantly; "
            "polling debate_result() after completion returns status='done' "
            "with full result schema (cost block, final_answer, roles)"
        ),
        "input": {
            "kwargs": {
                "question": "stub job question",
                "rounds": 1,
                "verify": False,
            },
            "stub_result": {
                "final_answer": "stubbed answer",
                "confidence": 70,
                "unresolved_disagreements": [],
                "key_risks_still_present": [],
                "what_survived": [],
                "what_was_dropped_or_fixed": [],
                "roles": {"proposer": {}, "critic": {}, "assembler": {}},
                "debate_id": "stub-id",
                "cost": {
                    "total_usd": 0.001,
                    "by_role": {
                        "proposer_usd": 0.0005, "critic_usd": 0.0003,
                        "assembler_usd": 0.0002, "verify_usd": 0.0,
                    },
                    "tokens": {
                        "proposer_in": 100, "proposer_out": 50,
                        "critic_in": 80,   "critic_out":  30,
                        "assembler_in": 60, "assembler_out": 20,
                    },
                    "latency_ms": 100,
                },
                "cost_estimate_usd": 0.001,
                "latency_ms": 100,
                "notes": [],
            },
        },
        "assert": "job_start_and_poll",
    },
    {
        "name": "debate_job_timeout",
        "suite": "debate",
        "kind": "debate_job",
        "description": (
            "When run_debate() hangs longer than DEBATE_JOB_MAX_S, "
            "the job transitions to status='timeout' without crashing the worker"
        ),
        "input": {
            "kwargs": {
                "question": "stub timeout question",
                "rounds": 1,
                "verify": False,
            },
            "stub_hang": True,
            "job_max_s_override": 0.05,
        },
        "assert": "job_timeout",
    },
]
