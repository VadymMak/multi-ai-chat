#!/usr/bin/env python3
"""
Auto-discover and index ALL local project folders into the Brain backend.

Usage:
  python3 index_local_projects.py              # discover + index all
  python3 index_local_projects.py --dry-run    # show what would happen, no HTTP writes
  python3 index_local_projects.py --folder vendly-storefront  # one specific folder
  python3 index_local_projects.py --report-only   # coverage report only, no indexing
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Iterator, Optional

# ────────────────────────────────────────────────
# Config
# ────────────────────────────────────────────────

BACKEND_URL = os.environ.get(
    "BRAIN_URL", "https://multi-ai-chat-production.up.railway.app"
)
AUTH_TOKEN = os.environ.get(
    "BRAIN_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxIiwiZXhwIjoxODA5MDYwMTA2fQ."
    "088PkzLccpsp4adsYxmqFyvbliqDGFAZRF_A1U0KF5s",
)
PROJECTS_ROOT = Path(os.path.expanduser("~/Documents/projects"))
BATCH_SIZE = 25
BATCH_SLEEP_S = 1.5
MAX_FILE_BYTES = 200_000

# Marker files — at least one must be present for a dir to count as a project
PROJECT_MARKERS = {
    ".git", "package.json", "pyproject.toml",
    "requirements.txt", "Cargo.toml", "go.mod",
}

SUPPORTED_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".py", ".json", ".css",
    ".scss", ".md", ".yaml", ".yml", ".sql", ".sh",
}

# dirs to never descend into while walking files
SKIP_WALK_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", ".turbo",
    "__pycache__", ".venv", "venv", ".cache", "coverage", ".nyc_output",
    "out", ".expo", "ios", "android",
}

# top-level folder names to skip from discovery entirely
SKIP_DISCOVERY = {
    "node_modules", ".git", "dist", "build", ".next", ".turbo",
    "__pycache__", ".venv", "venv", "coverage",
}

SKIP_FILES = {".env", ".env.local", ".env.production", ".DS_Store"}


# ────────────────────────────────────────────────
# Discovery
# ────────────────────────────────────────────────

def is_project_folder(path: Path) -> tuple[bool, str]:
    """Return (is_project, reason)."""
    if not path.is_dir():
        return False, "not a directory"
    if path.name.startswith("."):
        return False, "hidden directory"
    if path.name in SKIP_DISCOVERY:
        return False, f"in SKIP_DISCOVERY"
    # Check extension — reject things like "BRANDBOOK.pdf" (file, not dir, already handled above)
    for marker in PROJECT_MARKERS:
        if (path / marker).exists():
            return True, f"has {marker}"
    return False, "no project marker"


def discover_projects() -> list[dict]:
    """List immediate subdirs of PROJECTS_ROOT that look like code projects."""
    results = []
    if not PROJECTS_ROOT.is_dir():
        print(f"⚠️  PROJECTS_ROOT not found: {PROJECTS_ROOT}")
        return results
    for child in sorted(PROJECTS_ROOT.iterdir()):
        ok, reason = is_project_folder(child)
        results.append({
            "folder": child.name,
            "path": child,
            "is_project": ok,
            "reason": reason,
        })
    return results


def get_git_remote(path: Path) -> Optional[str]:
    """Return the first git remote URL, or None."""
    try:
        out = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=str(path),
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        url = out.decode().strip()
        # Convert SSH → HTTPS
        if url.startswith("git@github.com:"):
            url = "https://github.com/" + url[len("git@github.com:"):]
        return url or None
    except Exception:
        return None


def normalize_git_url(url: Optional[str]) -> Optional[str]:
    """Strip scheme, .git suffix, trailing slash — for matching."""
    if not url:
        return None
    u = url.strip().rstrip("/").rstrip(".git").lower()
    for prefix in ("https://", "http://"):
        if u.startswith(prefix):
            u = u[len(prefix):]
    return u


# ────────────────────────────────────────────────
# Brain API helpers
# ────────────────────────────────────────────────

def _api(method: str, path: str, body: Optional[dict] = None, timeout: int = 30) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BACKEND_URL}{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AUTH_TOKEN}",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            return {"_http_error": e.code, **json.loads(body_bytes)}
        except Exception:
            return {"_http_error": e.code, "detail": body_bytes.decode(errors="replace")[:300]}


def load_brain_projects() -> list[dict]:
    result = _api("GET", "/api/projects")
    if isinstance(result, list):
        return result
    return []


def get_project_files_count(project_id: int) -> int:
    r = _api("GET", f"/api/file-indexer/stats/{project_id}", timeout=15)
    if isinstance(r, dict):
        return r.get("total_files", 0) or r.get("files_count", 0) or 0
    return 0


def ensure_brain_project(folder_name: str, git_url: Optional[str],
                          brain_projects: list[dict]) -> Optional[int]:
    """
    Return project_id for this folder:
    1. Match by normalized git_url
    2. Match by folder name (exact, case-insensitive)
    3. Create a new project (idempotent — 400 = already exists, re-fetch)
    """
    norm_url = normalize_git_url(git_url)

    # Match by git URL
    if norm_url:
        for p in brain_projects:
            if normalize_git_url(p.get("git_url")) == norm_url:
                return p["id"]

    # Match by name
    lower_name = folder_name.lower()
    for p in brain_projects:
        if p.get("name", "").lower() == lower_name:
            return p["id"]

    # Create new project
    r = _api("POST", "/api/projects", {
        "name": folder_name,
        "description": f"Auto-indexed from {PROJECTS_ROOT / folder_name}",
    })
    if "_http_error" in r:
        if r["_http_error"] == 400:
            # Already exists with this name — re-fetch and match
            fresh = load_brain_projects()
            for p in fresh:
                if p.get("name", "").lower() == lower_name:
                    return p["id"]
        print(f"  ⚠️  Could not create project for {folder_name!r}: {r}")
        return None
    return r.get("id")


# ────────────────────────────────────────────────
# File walking + indexing
# ────────────────────────────────────────────────

def iter_files(root: Path) -> Iterator[dict]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_WALK_DIRS]
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
            yield {"path": str(full.relative_to(root)), "content": content}


def post_batch(project_id: int, files: list[dict], dry_run: bool) -> dict:
    if dry_run:
        return {"indexed": len(files), "skipped": 0, "errors": 0}
    r = _api("POST", "/api/file-indexer/index-local", {
        "project_id": project_id,
        "files": files,
        "skip_knowledge_extraction": True,
    }, timeout=90)
    if "_http_error" in r:
        raise RuntimeError(f"HTTP {r['_http_error']}: {r.get('detail','')[:120]}")
    return r


def index_project(pid: int, root: Path, dry_run: bool) -> dict:
    stats = {"file_count": 0, "indexed": 0, "skipped": 0, "errors": 0, "batches": 0}
    batch: list[dict] = []

    for file_data in iter_files(root):
        stats["file_count"] += 1
        batch.append(file_data)
        if len(batch) >= BATCH_SIZE:
            stats["batches"] += 1
            try:
                r = post_batch(pid, batch, dry_run)
                stats["indexed"] += r.get("indexed", 0)
                stats["skipped"] += r.get("skipped", 0)
                stats["errors"] += r.get("errors", 0)
            except Exception as exc:
                print(f"    ❌ batch {stats['batches']}: {exc}")
                stats["errors"] += len(batch)
            batch = []
            if not dry_run:
                time.sleep(BATCH_SLEEP_S)

    if batch:
        stats["batches"] += 1
        try:
            r = post_batch(pid, batch, dry_run)
            stats["indexed"] += r.get("indexed", 0)
            stats["skipped"] += r.get("skipped", 0)
            stats["errors"] += r.get("errors", 0)
        except Exception as exc:
            print(f"    ❌ batch {stats['batches']}: {exc}")
            stats["errors"] += len(batch)

    return stats


# ────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-discover and index all local projects")
    parser.add_argument("--dry-run", action="store_true", help="No writes — show what would happen")
    parser.add_argument("--folder", help="Index only this folder name")
    parser.add_argument("--report-only", action="store_true", help="Coverage report, no indexing")
    args = parser.parse_args()

    print(f"🔍 Discovering project folders in {PROJECTS_ROOT}...\n")
    all_dirs = discover_projects()
    projects = [d for d in all_dirs if d["is_project"]]
    skipped_dirs = [d for d in all_dirs if not d["is_project"]]

    if args.folder:
        projects = [p for p in projects if p["folder"] == args.folder]
        if not projects:
            print(f"Folder {args.folder!r} not found or not a project.")
            sys.exit(1)

    print(f"📂 Found {len(projects)} project(s), {len(skipped_dirs)} non-project dirs skipped.\n")

    # Load Brain project registry
    print("🧠 Loading Brain project registry...")
    brain_projects = load_brain_projects()
    print(f"   {len(brain_projects)} projects in Brain.\n")

    # Build report rows
    report: list[dict] = []

    for proj in projects:
        folder = proj["folder"]
        path = proj["path"]
        git_url = get_git_remote(path)

        print(f"→ {folder}", end="")
        if git_url:
            print(f"  [git: {git_url}]", end="")
        print()

        # Ensure Brain project exists
        if not args.dry_run and not args.report_only:
            pid = ensure_brain_project(folder, git_url, brain_projects)
        else:
            # Dry-run: still look up but don't create
            norm_url = normalize_git_url(git_url)
            pid = None
            if norm_url:
                for p in brain_projects:
                    if normalize_git_url(p.get("git_url")) == norm_url:
                        pid = p["id"]
                        break
            if pid is None:
                for p in brain_projects:
                    if p.get("name", "").lower() == folder.lower():
                        pid = p["id"]
                        break

        if pid is None:
            print(f"  ⚠️  No Brain project — skipping")
            report.append({"folder": folder, "project_id": None,
                            "status": "no_project", "files_indexed": 0, "errors": 0})
            print()
            continue

        # Get current files_count
        files_before = get_project_files_count(pid) if not args.dry_run else 0

        status = "already_indexed" if files_before > 0 else "not_indexed"

        if args.report_only:
            print(f"  project_id={pid}  files_count={files_before}  status={status}")
            report.append({"folder": folder, "project_id": pid,
                            "status": status, "files_indexed": files_before, "errors": 0})
            print()
            continue

        # Index
        print(f"  project_id={pid}  files_before={files_before}")
        try:
            idx = index_project(pid, path, args.dry_run)
            files_after = get_project_files_count(pid) if not args.dry_run else idx["indexed"]
            print(
                f"  ✅ files_found={idx['file_count']} indexed={idx['indexed']} "
                f"skipped={idx['skipped']} errors={idx['errors']}  "
                f"brain_total={files_after}"
            )
            report.append({
                "folder": folder,
                "project_id": pid,
                "status": "newly_indexed" if files_before == 0 else "updated",
                "files_indexed": files_after,
                "errors": idx["errors"],
            })
        except Exception as exc:
            print(f"  ❌ Project failed: {exc}")
            report.append({"folder": folder, "project_id": pid,
                            "status": "error", "files_indexed": 0, "errors": 1})
        print()

    # ── Coverage Report ──────────────────────────────────────────────
    print("=" * 65)
    print("COVERAGE REPORT")
    print("=" * 65)
    print(f"Folders discovered:     {len(projects)}")
    already = sum(1 for r in report if r["status"] == "already_indexed")
    newly = sum(1 for r in report if r["status"] in ("newly_indexed", "updated"))
    errors = sum(1 for r in report if r["status"] == "error")
    no_proj = sum(1 for r in report if r["status"] == "no_project")
    print(f"Already indexed:        {already}")
    print(f"Newly indexed/updated:  {newly}")
    print(f"No Brain project:       {no_proj}")
    print(f"Errors:                 {errors}")
    print()
    print(f"{'Folder':<35} {'PID':>5}  {'files':>6}  {'status'}")
    print("-" * 65)
    for r in sorted(report, key=lambda x: x["folder"]):
        pid_str = str(r["project_id"]) if r["project_id"] else "—"
        print(f"  {r['folder']:<33} {pid_str:>5}  {r['files_indexed']:>6}  {r['status']}")

    print()
    if skipped_dirs:
        print(f"Non-project dirs skipped ({len(skipped_dirs)}):")
        for d in skipped_dirs:
            print(f"  {d['folder']!r}  — {d['reason']}")

    print("\nDone.")


if __name__ == "__main__":
    main()
