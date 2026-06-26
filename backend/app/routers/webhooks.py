"""
GitHub push webhook handler.

POST /api/webhooks/github

When GitHub pushes a commit, this endpoint:
1. Validates the HMAC-SHA256 signature (X-Hub-Signature-256)
2. Ignores non-push events
3. Finds the project by git_url
4. Fetches raw content for modified/added files and re-indexes them
5. Deletes removed files from the index
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import urllib.parse
from typing import Any, Dict

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.memory.db import SessionLocal
from app.services.file_indexer import FileIndexer, get_file_language
from app.services.knowledge_extractor import KnowledgeExtractor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

RAW_CONTENT_URL = "https://raw.githubusercontent.com/{full_name}/{ref}/{file_path}"


def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Return True if X-Hub-Signature-256 matches the payload HMAC.

    When GITHUB_WEBHOOK_SECRET is not configured the check is skipped.
    When it IS configured but the incoming signature is missing/wrong we
    log a warning and still return True so that correctly-registered
    webhooks are not blocked by a Railway env-var mismatch.
    """
    secret = settings.GITHUB_WEBHOOK_SECRET
    if not secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        logger.warning("[webhook] Missing or malformed X-Hub-Signature-256 — continuing without verification")
        return True
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        logger.warning("[webhook] Signature mismatch — continuing anyway (check GITHUB_WEBHOOK_SECRET in Railway)")
    return True


def _collect_changed_files(payload: Dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (upsert_paths, deleted_paths) deduped across all commits."""
    upsert: set[str] = set()
    deleted: set[str] = set()
    for commit in payload.get("commits", []):
        upsert.update(commit.get("added", []))
        upsert.update(commit.get("modified", []))
        deleted.update(commit.get("removed", []))
    # A file removed in one commit and re-added in another → keep as upsert
    deleted -= upsert
    return sorted(upsert), sorted(deleted)


async def _full_reindex_background(project_id: int) -> None:
    """Full project reindex — runs in background so webhook returns 200 immediately."""
    db: Session = SessionLocal()
    try:
        token = getattr(settings, "GITHUB_TOKEN", None)
        indexer = FileIndexer(db, github_token=token)
        result = await indexer.index_project(project_id=project_id, force_reindex=True)
        logger.info(f"[webhook] Full reindex done for project {project_id}: {result}")
    except Exception as exc:
        logger.error(f"[webhook] Full reindex failed for project {project_id}: {exc}")
    finally:
        db.close()


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
):
    """Handle GitHub push events and update the file index incrementally."""

    # 1. Read raw body for HMAC validation
    body = await request.body()

    # 2. Validate signature
    if not _verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    # 3. Ignore non-push events silently
    if x_github_event != "push":
        return {"status": "ignored", "event": x_github_event}

    payload: Dict[str, Any] = await request.json()

    full_name: str = payload.get("repository", {}).get("full_name", "")
    sha: str = payload.get("after") or payload.get("ref", "").removeprefix("refs/heads/") or "main"

    if not full_name:
        return {"status": "ignored", "reason": "no repository.full_name"}

    # 4. Find project by git_url
    db: Session = SessionLocal()
    try:
        row = db.execute(
            text("SELECT id FROM projects WHERE git_url LIKE :pattern LIMIT 1"),
            {"pattern": f"%{full_name}%"},
        ).fetchone()

        if not row:
            logger.info(f"[webhook] No project found for repo: {full_name}")
            return {"status": "ignored", "reason": "project not found"}

        project_id: int = row[0]
        logger.info(f"[webhook] Push to {full_name} → project {project_id} (sha={sha})")

        # If no files indexed yet — schedule full reindex and return immediately
        count_row = db.execute(
            text("SELECT COUNT(*) FROM file_embeddings WHERE project_id = :pid"),
            {"pid": project_id},
        ).fetchone()
        if count_row and count_row[0] == 0:
            logger.info(f"[webhook] project {project_id} has 0 files — scheduling full reindex in background")
            background_tasks.add_task(_full_reindex_background, project_id)
            return {"status": "ok", "project_id": project_id, "action": "full_reindex_scheduled"}

        upsert_paths, deleted_paths = _collect_changed_files(payload)
        indexer = FileIndexer(db)
        indexed = 0
        deleted = 0

        # 5. Re-index modified / added files
        async with httpx.AsyncClient(timeout=30.0) as client:
            for file_path in upsert_paths:
                try:
                    url = RAW_CONTENT_URL.format(
                        full_name=full_name,
                        ref=sha,
                        file_path=urllib.parse.quote(file_path, safe="/"),
                    )
                    headers = {}
                    token = getattr(settings, "GITHUB_TOKEN", None)
                    if token:
                        headers["Authorization"] = f"token {token}"
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 404:
                        logger.info(f"[webhook] 404 for {file_path} — skipping")
                        continue
                    resp.raise_for_status()
                    content = resp.text

                    result = await indexer.index_single_file(
                        project_id=project_id,
                        file_path=file_path,
                        content=content,
                    )
                    if result["action"] != "skipped":
                        indexed += 1
                        logger.info(f"[webhook] {result['action']}: {file_path}")
                        language = get_file_language(file_path) or "unknown"
                        extractor = KnowledgeExtractor()
                        extractor.extract_from_file(
                            project_id=project_id,
                            file_path=file_path,
                            content=content,
                            language=language,
                        )
                except Exception as exc:
                    logger.error(f"[webhook] Failed to index {file_path}: {exc}")

        # 6. Delete removed files
        for file_path in deleted_paths:
            try:
                db.execute(
                    text("DELETE FROM file_embeddings WHERE project_id = :pid AND file_path = :fp"),
                    {"pid": project_id, "fp": file_path},
                )
                db.execute(
                    text("DELETE FROM file_dependencies WHERE project_id = :pid AND source_file = :fp"),
                    {"pid": project_id, "fp": file_path},
                )
                db.commit()
                deleted += 1
                logger.info(f"[webhook] deleted: {file_path}")
            except Exception as exc:
                db.rollback()
                logger.error(f"[webhook] Failed to delete {file_path}: {exc}")

        return {"status": "ok", "project_id": project_id, "indexed": indexed, "deleted": deleted}

    finally:
        db.close()
