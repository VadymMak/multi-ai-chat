#!/usr/bin/env python3
"""
Index local project directories into the Brain backend.

Walks each project folder, reads source files, and POSTs them to
/api/file-indexer/index-local on Railway in batches.

Usage:
  python3 index_local_projects.py                     # index all listed projects
  python3 index_local_projects.py --project-id 22     # index one project by id
  python3 index_local_projects.py --dry-run           # show what would be sent
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Iterator

BACKEND_URL = os.environ.get(
    "BRAIN_URL", "https://multi-ai-chat-production.up.railway.app"
)
AUTH_TOKEN = os.environ.get(
    "BRAIN_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxIiwiZXhwIjoxODA5MDYwMTA2fQ."
    "088PkzLccpsp4adsYxmqFyvbliqDGFAZRF_A1U0KF5s",
)
PROJECTS_ROOT = Path("/Users/vadymmak/Documents/projects")
BATCH_SIZE = 50
MAX_FILE_BYTES = 200_000  # 200 KB per file

SUPPORTED_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".py", ".json", ".css",
    ".scss", ".md", ".yaml", ".yml", ".sql", ".sh",
}

SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", ".turbo",
    "__pycache__", ".venv", "venv", ".cache", "coverage", ".nyc_output",
    "out", ".expo", "ios", "android",
}

SKIP_FILES = {".env", ".env.local", ".env.production", ".DS_Store"}

PROJECTS: list[dict] = [
    {"id": 19, "folder": "ak-portfolio"},
    {"id": 21, "folder": "smartcontext-v2"},
    {"id": 22, "folder": "vendly-storefront"},
    {"id": 23, "folder": "adriano-trencin"},
    {"id": 25, "folder": "krajina-trencin"},
    {"id": 26, "folder": "formaink"},
    {"id": 27, "folder": "barbershop-trencin"},
    {"id": 29, "folder": "mexc-trade-bot"},
    {"id": 30, "folder": "mamalog"},
    {"id": 44, "folder": "relocant-help"},
    {"id": 47, "folder": "smart-context-gallery"},
    {"id": 67, "folder": "transfer-gmbh-demo"},
    {"id": 68, "folder": "job-scanner"},
    {"id": 69, "folder": "vessel-manual-bot"},
    {"id": 70, "folder": "transfer-sk-eu"},
    {"id": 71, "folder": "tanks-sounding"},
]


def iter_files(root: Path) -> Iterator[dict]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if fname in SKIP_FILES or fname.startswith(".env"):
                continue
            ext = Path(fname).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            full = Path(dirpath) / fname
            try:
                size = full.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES or size == 0:
                continue
            try:
                content = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(full.relative_to(root))
            yield {"path": rel, "content": content}


def post_batch(project_id: int, files: list[dict], dry_run: bool) -> dict:
    if dry_run:
        print(f"  [dry-run] would POST {len(files)} files for project {project_id}")
        return {"indexed": len(files), "skipped": 0, "errors": 0}

    body = json.dumps({"project_id": project_id, "files": files}).encode()
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/file-indexer/index-local",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AUTH_TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def index_project(pid: int, folder: str, dry_run: bool) -> None:
    root = PROJECTS_ROOT / folder
    if not root.is_dir():
        print(f"  ⚠️  Folder not found: {root}")
        return

    batch: list[dict] = []
    total = {"indexed": 0, "skipped": 0, "errors": 0}
    file_count = 0

    for file_data in iter_files(root):
        file_count += 1
        batch.append(file_data)
        if len(batch) >= BATCH_SIZE:
            try:
                result = post_batch(pid, batch, dry_run)
                total["indexed"] += result.get("indexed", 0)
                total["skipped"] += result.get("skipped", 0)
                total["errors"] += result.get("errors", 0)
            except Exception as exc:
                print(f"  ❌ Batch error: {exc}")
                total["errors"] += len(batch)
            batch = []

    if batch:
        try:
            result = post_batch(pid, batch, dry_run)
            total["indexed"] += result.get("indexed", 0)
            total["skipped"] += result.get("skipped", 0)
            total["errors"] += result.get("errors", 0)
        except Exception as exc:
            print(f"  ❌ Batch error: {exc}")
            total["errors"] += len(batch)

    print(
        f"  ✅ project_id={pid} folder={folder}: "
        f"files_found={file_count} "
        f"indexed={total['indexed']} skipped={total['skipped']} errors={total['errors']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Index local projects into Brain")
    parser.add_argument("--project-id", type=int, help="Index only this project ID")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent")
    args = parser.parse_args()

    targets = PROJECTS
    if args.project_id:
        targets = [p for p in PROJECTS if p["id"] == args.project_id]
        if not targets:
            print(f"Project ID {args.project_id} not in list.")
            sys.exit(1)

    print(f"Indexing {len(targets)} project(s)...\n")
    for p in targets:
        print(f"→ [{p['id']}] {p['folder']}")
        index_project(p["id"], p["folder"], args.dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()
