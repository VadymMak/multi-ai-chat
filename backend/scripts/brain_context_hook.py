#!/usr/bin/env python3
"""
Claude Code UserPromptSubmit hook — B-Lite inline injection.

Reads the hook payload from stdin (Claude Code provides JSON with `cwd`,
`prompt`, `session_id`, etc.) and:
  1. Calls Brain /api/brain/inject to get the top-1 relevant lesson/pitfall.
     If found (above score threshold), injects it as a system-reminder with
     the ACTUAL CONTENT — not a "please call a tool" reminder.
  2. Always appends the project-folder reminder so Claude still loads broader
     context via build_context_for_query.

Fail-open: any error or timeout → only the folder reminder prints, prompt
is NEVER blocked.

Environment variables (optional overrides):
  BRAIN_INJECT_ENABLED  - set to "false" to disable injection (default: true)
  BRAIN_INJECT_URL      - Brain server base URL
  BRAIN_INJECT_TOKEN    - Bearer token for Brain API
  BRAIN_INJECT_TIMEOUT  - HTTP timeout in seconds (default: 0.5)
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.parse
import urllib.request

# ── Config ────────────────────────────────────────────────────────────────────
_ENABLED: bool = os.environ.get("BRAIN_INJECT_ENABLED", "true").lower() not in (
    "false", "0", "no",
)
_BASE_URL: str = os.environ.get(
    "BRAIN_INJECT_URL",
    "https://multi-ai-chat-production.up.railway.app",
)
_TOKEN: str = os.environ.get(
    "BRAIN_INJECT_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxIiwiZXhwIjoxODA5MDYwMTA2fQ."
    "088PkzLccpsp4adsYxmqFyvbliqDGFAZRF_A1U0KF5s",
)
_TIMEOUT: float = float(os.environ.get("BRAIN_INJECT_TIMEOUT", "0.5"))

# ── Folder-context reminder (always injected) ─────────────────────────────────
_FOLDER_REMINDER = (
    "[Brain MCP] Active project folder: {folder!r}.\n"
    "Before answering:\n"
    "1. Call `build_context_for_query("
    "folder_identifier={folder!r}, query=<short summary of the user's ask>)` "
    "to fetch project context (recent files, prior decisions, session summaries). "
    "If the returned context contains a RELEVANT SKILLS/LESSONS section, "
    "follow those instructions before using general knowledge.\n"
    "2. Call `query_pitfalls(project_id=<id>)` to check for known mistakes "
    "before non-trivial work — avoids repeating past errors.\n"
    "Skip both only for trivial edits already in active scope."
)


def _ssl_ctx() -> ssl.SSLContext:
    """Return SSL context, using certifi if available (fixes macOS Python.org SSL)."""
    try:
        import certifi  # type: ignore[import]
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch_injection(prompt: str, folder: str) -> str:
    """Call /api/brain/inject. Returns injection string or '' on any error/timeout."""
    try:
        qs = urllib.parse.urlencode({"q": prompt[:300], "project": folder})
        url = f"{_BASE_URL}/api/brain/inject?{qs}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_ctx()) as resp:
            data = json.loads(resp.read())
        return data.get("injection", "") or ""
    except Exception:
        return ""  # fail-open: never block the prompt


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # silent on bad input

    cwd = payload.get("cwd") or os.getcwd()
    folder = os.path.basename(cwd.rstrip("/").rstrip("\\")) or "unknown"
    prompt = payload.get("prompt") or ""

    parts: list[str] = []

    # B-Lite: inject actual lesson content if Brain returns a match
    if _ENABLED:
        injection = _fetch_injection(prompt, folder)
        if injection:
            parts.append(injection)

    # Always inject project-folder reminder (context + pitfalls nudge)
    parts.append(_FOLDER_REMINDER.format(folder=folder))

    print("\n".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
