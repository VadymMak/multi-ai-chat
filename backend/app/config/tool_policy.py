"""
Tool policy registry — classifies every MCP tool by risk level.

Classes:
  read        — free, no span, no gate
  write       — allowed automatically; should emit a tool span
  destructive — confirm-gate required; confirm=False → preview only

Anything not listed defaults to "read" IF obviously read-only by name,
otherwise "write" (fail-safe).
"""

from __future__ import annotations

TOOL_CLASS: dict[str, str] = {
    # ── read ─────────────────────────────────────────────────────────────────
    "search_project_files":       "read",
    "get_file_content":           "read",
    "get_file_dependencies":      "read",
    "search_conversation_memory": "read",
    "list_canon_items":           "read",
    "get_project_stats":          "read",
    "get_file_versions":          "read",
    "build_context_for_query":    "read",
    "get_active_project":         "read",
    "hybrid_search_files":        "read",
    "get_developer_patterns":     "read",
    "get_session_summaries":      "read",
    "search_session_memory":      "read",
    "get_index_status":           "read",
    "get_usage_stats":            "read",
    "get_total_cost":             "read",
    "get_cache_efficiency":       "read",
    "brain_help":                 "read",
    "get_skill":                  "read",
    "list_skills":                "read",
    "query_pitfalls":             "read",
    "query_knowledge_graph":      "read",
    "get_brain_effectiveness":    "read",
    "registry_list":              "read",
    "registry_get":               "read",
    "list_traces":                "read",
    "get_trace":                  "read",
    "run_evals":                  "read",
    "verify_claims":              "read",
    "predict_impact":             "read",

    # ── write ─────────────────────────────────────────────────────────────────
    "save_session_summary":       "write",
    "record_error":               "write",
    "record_fix":                 "write",
    "registry_upsert":            "write",
    # save_skill is "write" for NEW skills; overwriting a manual skill is
    # handled inside the tool itself (confirm-gate at the function level)
    "save_skill":                 "write",
    "ensure_project_indexed":     "write",
    "index_local_project":        "write",
    "create_project_with_index":  "write",
    "sync_usage_logs":            "write",
    "upload_local_usage":         "write",
    "sync_projects_to_claude_md": "write",
    "setup_local_sync":           "write",
    "setup_prompt_hook":          "write",
    "extract_knowledge_for_project": "write",
    "distill_skills":             "write",
    "run_effectiveness_backfill": "write",
    "update_site_media":          "write",
    "generate_image":             "write",
    "generate_character_image":   "write",
    "create_talking_avatar":      "write",
    "remove_background":          "write",
    "upscale_image":              "write",
    "generate_voiceover":         "write",
    "extend_video":               "write",
    "create_video":               "write",

    # ── destructive ───────────────────────────────────────────────────────────
    "registry_delete":            "destructive",
    "delete_skill":               "destructive",
}

# Tools not in TOOL_CLASS default to "write" (safer than read for unknowns).
DEFAULT_CLASS = "write"


def get_tool_class(tool_name: str) -> str:
    """Return the risk class for a tool name."""
    return TOOL_CLASS.get(tool_name, DEFAULT_CLASS)


# ── Summary counts ────────────────────────────────────────────────────────────
_counts = {"read": 0, "write": 0, "destructive": 0}
for _v in TOOL_CLASS.values():
    _counts[_v] = _counts.get(_v, 0) + 1

TOOL_CLASS_SUMMARY: dict[str, int] = dict(_counts)
