"""
Fetch all projects from Brain API and update the projects table in ~/.claude/CLAUDE.md.

Usage:
    python update_claude_md.py [--api-url URL] [--token TOKEN]

Defaults:
    --api-url  https://multi-ai-chat-production.up.railway.app
    --token    BRAIN_API_TOKEN env var or hardcoded internal token
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import httpx

CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"

DEFAULT_API_URL = "https://multi-ai-chat-production.up.railway.app"
DEFAULT_TOKEN = os.getenv(
    "BRAIN_API_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIxIiwiZXhwIjoxODA2NDkxNTc2fQ"
    ".oBu_Vg9wW34TE1LUlYpwB3v9uPNjKuIMXcQu_S6k-8o",
)

# Matches the ## 👤 Мои проекты section through the next --- separator (or EOF).
_SECTION_RE = re.compile(
    r"(## 👤 Мои проекты\s*\n)"      # section header (group 1)
    r".*?"                             # existing table (non-greedy)
    r"(?=\n---|\Z)",                   # stop before next --- or EOF
    re.DOTALL,
)


def fetch_projects(api_url: str, token: str) -> list[dict]:
    url = f"{api_url.rstrip('/')}/api/projects"
    resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    # API may return a list directly or {"projects": [...]}
    return data if isinstance(data, list) else data.get("projects", data.get("items", []))


def build_table(projects: list[dict]) -> str:
    lines = [
        "| id | Название | Описание | Файлов |",
        "|----|----------|----------|--------|",
    ]
    for p in sorted(projects, key=lambda x: int(x.get("id", 0))):
        pid = p.get("id", "")
        name = str(p.get("name", "")).replace("|", "\\|")
        desc = str(p.get("description") or "").replace("|", "\\|").strip()
        files = p.get("files_count", 0) or 0
        lines.append(f"| {pid} | {name} | {desc} | {files} |")
    return "\n".join(lines)


def update_claude_md(table: str) -> None:
    if not CLAUDE_MD.exists():
        print(f"ERROR: {CLAUDE_MD} not found", file=sys.stderr)
        sys.exit(1)

    content = CLAUDE_MD.read_text(encoding="utf-8")
    replacement = f"## 👤 Мои проекты\n\n{table}\n"

    new_content, n = _SECTION_RE.subn(replacement, content)
    if n == 0:
        print(
            "WARNING: Could not find '## 👤 Мои проекты' section — appending at end.",
            file=sys.stderr,
        )
        new_content = content.rstrip() + f"\n\n{replacement}"

    CLAUDE_MD.write_text(new_content, encoding="utf-8")
    print(f"Updated {CLAUDE_MD}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync projects table into ~/.claude/CLAUDE.md")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    args = parser.parse_args()

    print(f"Fetching projects from {args.api_url} ...")
    try:
        projects = fetch_projects(args.api_url, args.token)
    except httpx.HTTPStatusError as exc:
        print(f"ERROR: API returned {exc.response.status_code}: {exc.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Got {len(projects)} projects")
    table = build_table(projects)
    print("\nNew table preview:")
    print(table)
    print()

    update_claude_md(table)

    print(
        "\n# Cron job hint (run daily to keep CLAUDE.md in sync):\n"
        "# 0 9 * * * cd /path/to/multi-ai-chat && python backend/scripts/update_claude_md.py\n"
        "# Or add to ~/.zshrc as an alias: alias sync-brain='python ~/projects/multi-ai-chat/backend/scripts/update_claude_md.py'"
    )


if __name__ == "__main__":
    main()
