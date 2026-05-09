#!/usr/bin/env python3
"""
Claude Code UserPromptSubmit hook — injects a Brain MCP reminder.

Reads the hook payload from stdin (Claude Code provides JSON with `cwd`,
`prompt`, `session_id`, etc.) and prints a short system-reminder to stdout
which Claude Code appends to the user prompt as additional context.

The reminder tells Claude which project folder is active and that it should
call `build_context_for_query(folder_identifier=..., query=...)` before
answering. This deterministic nudge does not depend on Claude reading and
following CLAUDE.md instructions, so it lifts brain_usage_pct close to 100%
for project-aware tasks.

Self-contained: stdlib only (no pip deps). Safe to copy to any machine.
"""
from __future__ import annotations

import json
import os
import sys


_REMINDER_TEMPLATE = (
    "[Brain MCP] Active project folder: {folder!r}.\n"
    "Before answering, call `build_context_for_query("
    "folder_identifier={folder!r}, query=<short summary of the user's ask>)` "
    "to fetch project context (recent files, prior decisions, session summaries). "
    "Skip only for trivial edits already in active scope."
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # silent on bad input — never block the prompt

    cwd = payload.get("cwd") or os.getcwd()
    folder = os.path.basename(cwd.rstrip("/").rstrip("\\")) or "unknown"

    print(_REMINDER_TEMPLATE.format(folder=folder))
    return 0


if __name__ == "__main__":
    sys.exit(main())
