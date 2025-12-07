# File: backend/app/services/file_indexer.py
"""
File Indexer Service - Index project files into pgvector for semantic search

This service:
1. Fetches files from Git repository (via GitHub API)
2. Generates embeddings using OpenAI text-embedding-3-small
3. Stores in file_embeddings table
4. Provides semantic search across codebase

Use cases:
- "Find files related to authentication" → returns auth files
- "Where is error handling implemented?" → returns error handler files
- Debug assistance with full codebase context
"""

import hashlib
import json
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services import vector_service
from app.memory.models import Project

logger = logging.getLogger(__name__)

# ====================================================================
# CONFIGURATION
# ====================================================================

# Supported file extensions for indexing
SUPPORTED_EXTENSIONS = {
    # TypeScript / JavaScript
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    
    # Python
    ".py": "python",
    
    # Web
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".vue": "vue",
    ".svelte": "svelte",
    
    # Data / Config
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    
    # Other languages
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".sql": "sql",
    ".sh": "bash",
    
    # Documentation
    ".md": "markdown",
    ".mdx": "markdown",
}

# Files/folders to skip
SKIP_PATTERNS = [
    "node_modules/",
    "__pycache__/",
    ".git/",
    ".venv/",
    "venv/",
    "dist/",
    "build/",
    ".next/",
    "coverage/",
    ".pytest_cache/",
    ".mypy_cache/",
    "*.min.js",
    "*.min.css",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "*.map",
    "*.d.ts.map",
]

# Max file size to index (in bytes)
MAX_FILE_SIZE = 100_000  # 100KB

# Max files per project
MAX_FILES_PER_PROJECT = 500


# ====================================================================
# HELPER FUNCTIONS
# ====================================================================

def parse_github_url(git_url: str) -> Tuple[str, str, str]:
    """
    Parse GitHub URL to extract owner, repo, and branch.
    
    Supports:
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - git@github.com:owner/repo.git
    
    Returns: (owner, repo, branch)
    """
    # Remove .git suffix
    git_url = git_url.rstrip("/").replace(".git", "")
    
    # HTTPS format
    if "github.com/" in git_url:
        parts = git_url.split("github.com/")[-1].split("/")
        if len(parts) >= 2:
            owner = parts[0]
            repo = parts[1]
            branch = parts[3] if len(parts) > 3 and parts[2] == "tree" else "main"
            return owner, repo, branch
    
    # SSH format
    if "git@github.com:" in git_url:
        parts = git_url.split("git@github.com:")[-1].split("/")
        if len(parts) >= 2:
            return parts[0], parts[1], "main"
    
    raise ValueError(f"Could not parse GitHub URL: {git_url}")


def should_skip_file(file_path: str) -> bool:
    """Check if file should be skipped based on patterns"""
    for pattern in SKIP_PATTERNS:
        if pattern.endswith("/"):
            # Directory pattern
            if pattern[:-1] in file_path:
                return True
        elif pattern.startswith("*"):
            # Wildcard pattern
            if file_path.endswith(pattern[1:]):
                return True
        else:
            # Exact match
            if file_path.endswith(pattern):
                return True
    return False


def get_file_language(file_path: str) -> Optional[str]:
    """Get language from file extension"""
    for ext, lang in SUPPORTED_EXTENSIONS.items():
        if file_path.endswith(ext):
            return lang
    return None


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def extract_metadata(content: str, language: str) -> Dict[str, Any]:
    """
    Extract metadata from file content.
    
    Returns dict with:
    - imports: list of imported modules
    - exports: list of exported items
    - classes: list of class names
    - functions: list of function names
    """
    metadata = {
        "imports": [],
        "exports": [],
        "classes": [],
        "functions": [],
    }
    
    try:
        if language in ["typescript", "javascript"]:
            # Extract imports
            import_matches = re.findall(
                r"import\s+(?:{[^}]+}|\*\s+as\s+\w+|\w+)\s+from\s+['\"]([^'\"]+)['\"]",
                content
            )
            metadata["imports"] = list(set(import_matches))
            
            # Extract exports
            export_matches = re.findall(
                r"export\s+(?:default\s+)?(?:class|function|const|let|var|interface|type|enum)\s+(\w+)",
                content
            )
            metadata["exports"] = list(set(export_matches))
            
            # Extract classes
            class_matches = re.findall(r"class\s+(\w+)", content)
            metadata["classes"] = list(set(class_matches))
            
            # Extract functions
            func_matches = re.findall(
                r"(?:async\s+)?function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\(",
                content
            )
            metadata["functions"] = list(set(
                m[0] or m[1] for m in func_matches if m[0] or m[1]
            ))
            
        elif language == "python":
            # Extract imports
            import_matches = re.findall(
                r"(?:from\s+(\S+)\s+import|import\s+(\S+))",
                content
            )
            metadata["imports"] = list(set(
                m[0] or m[1] for m in import_matches if m[0] or m[1]
            ))
            
            # Extract classes
            class_matches = re.findall(r"class\s+(\w+)", content)
            metadata["classes"] = list(set(class_matches))
            
            # Extract functions
            func_matches = re.findall(r"def\s+(\w+)", content)
            metadata["functions"] = list(set(func_matches))
            
    except Exception as e:
        logger.warning(f"Failed to extract metadata: {e}")
    
    return metadata


# ====================================================================
# GITHUB API CLIENT
# ====================================================================

class GitHubClient:
    """Client for GitHub API to fetch repository files"""
    
    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Multi-AI-Chat-Indexer"
        }
        if token:
            self.headers["Authorization"] = f"token {token}"
    
    async def get_repo_tree(
        self, 
        owner: str, 
        repo: str, 
        branch: str = "main"
    ) -> List[Dict[str, Any]]:
        """
        Get all files in repository using Git Trees API.
        
        Returns list of file objects with path, size, sha.
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, timeout=30.0)
            
            if response.status_code == 404:
                # Try 'master' branch if 'main' not found
                if branch == "main":
                    return await self.get_repo_tree(owner, repo, "master")
                raise ValueError(f"Repository not found: {owner}/{repo}")
            
            response.raise_for_status()
            data = response.json()
            
            # Filter to only files (not directories)
            files = [
                item for item in data.get("tree", [])
                if item.get("type") == "blob"
            ]
            
            logger.info(f"Found {len(files)} files in {owner}/{repo}")
            return files
    
    async def get_file_content(
        self, 
        owner: str, 
        repo: str, 
        file_path: str,
        branch: str = "main"
    ) -> str:
        """Get content of a single file"""
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{file_path}?ref={branch}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            
            # Content is base64 encoded
            import base64
            content = base64.b64decode(data["content"]).decode("utf-8")
            return content
    
    async def get_raw_file(
        self,
        owner: str,
        repo: str,
        file_path: str,
        branch: str = "main"
    ) -> str:
        """Get raw file content (faster than API for large files)"""
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
            return response.text


# ====================================================================
# FILE INDEXER SERVICE
# ====================================================================

class FileIndexer:
    """
    Index project files into pgvector for semantic search.
    
    Usage:
        indexer = FileIndexer(db)
        await indexer.index_project(project_id)
        
        # Search files
        results = await indexer.search_files(project_id, "authentication")
    """
    
    def __init__(self, db: Session, github_token: Optional[str] = None):
        self.db = db
        self.github = GitHubClient(github_token)
    
    async def index_project(
        self,
        project_id: int,
        force_reindex: bool = False
    ) -> Dict[str, Any]:
        """
        Index all files from project's Git repository.
        
        Args:
            project_id: Project ID
            force_reindex: If True, reindex even if file hasn't changed
            
        Returns:
            Statistics about indexing process
        """
        logger.info(f"🔍 Starting indexing for project {project_id}")
        
        # Get project
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Project {project_id} not found")
        
        if not project.git_url:
            raise ValueError(f"Project {project_id} has no Git URL")
        
        # Parse GitHub URL
        try:
            owner, repo, branch = parse_github_url(project.git_url)
            logger.info(f"📦 Indexing {owner}/{repo} (branch: {branch})")
        except ValueError as e:
            raise ValueError(f"Invalid Git URL: {e}")
        
        # Get repository tree
        try:
            repo_files = await self.github.get_repo_tree(owner, repo, branch)
        except Exception as e:
            logger.error(f"Failed to get repo tree: {e}")
            raise
        
        # Filter files to index
        files_to_index = []
        for file_info in repo_files:
            file_path = file_info.get("path", "")
            file_size = file_info.get("size", 0)
            
            # Skip non-code files
            if not get_file_language(file_path):
                continue
            
            # Skip files matching skip patterns
            if should_skip_file(file_path):
                continue
            
            # Skip large files
            if file_size > MAX_FILE_SIZE:
                logger.debug(f"Skipping large file: {file_path} ({file_size} bytes)")
                continue
            
            files_to_index.append(file_info)
        
        # Limit number of files
        if len(files_to_index) > MAX_FILES_PER_PROJECT:
            logger.warning(
                f"Project has {len(files_to_index)} files, limiting to {MAX_FILES_PER_PROJECT}"
            )
            files_to_index = files_to_index[:MAX_FILES_PER_PROJECT]
        
        logger.info(f"📄 {len(files_to_index)} files to index")
        
        # Index each file
        stats = {
            "total_files": len(files_to_index),
            "indexed": 0,
            "skipped": 0,
            "errors": 0,
            "errors_list": []
        }
        
        for i, file_info in enumerate(files_to_index, 1):
            file_path = file_info["path"]
            
            try:
                indexed = await self._index_file(
                    project_id=project_id,
                    owner=owner,
                    repo=repo,
                    branch=branch,
                    file_path=file_path,
                    file_sha=file_info.get("sha"),
                    force_reindex=force_reindex
                )
                
                if indexed:
                    stats["indexed"] += 1
                    logger.info(f"  ✅ [{i}/{len(files_to_index)}] {file_path}")
                else:
                    stats["skipped"] += 1
                    logger.debug(f"  ⏭️ [{i}/{len(files_to_index)}] {file_path} (unchanged)")
                    
            except Exception as e:
                stats["errors"] += 1
                stats["errors_list"].append(f"{file_path}: {str(e)[:100]}")
                logger.error(f"  ❌ [{i}/{len(files_to_index)}] {file_path}: {e}")
        
        # Update project last indexed time
        self.db.execute(text("""
            UPDATE projects 
            SET git_updated_at = :now 
            WHERE id = :project_id
        """), {"now": datetime.utcnow(), "project_id": project_id})
        self.db.commit()
        
        logger.info(f"""
🎉 Indexing complete for project {project_id}:
   Total: {stats['total_files']} files
   Indexed: {stats['indexed']}
   Skipped: {stats['skipped']} (unchanged)
   Errors: {stats['errors']}
""")
        
        return stats
    
    async def _index_file(
        self,
        project_id: int,
        owner: str,
        repo: str,
        branch: str,
        file_path: str,
        file_sha: Optional[str],
        force_reindex: bool = False
    ) -> bool:
        """
        Index a single file.
        
        Returns True if file was indexed, False if skipped.
        """
        # Check if file already indexed and unchanged
        if not force_reindex and file_sha:
            existing = self.db.execute(text("""
                SELECT content_hash FROM file_embeddings
                WHERE project_id = :project_id AND file_path = :file_path
            """), {"project_id": project_id, "file_path": file_path}).fetchone()
            
            if existing and existing[0] == file_sha:
                return False  # File unchanged
        
        # Get file content
        content = await self.github.get_raw_file(owner, repo, file_path, branch)
        
        # Get language
        language = get_file_language(file_path)
        
        # Compute hash
        content_hash = file_sha or compute_content_hash(content)
        
        # Extract metadata
        metadata = extract_metadata(content, language) if language else {}
        
        # Generate embedding
        # For code files, include file path and metadata in embedding text
        embedding_text = f"""
File: {file_path}
Language: {language}
Classes: {', '.join(metadata.get('classes', []))}
Functions: {', '.join(metadata.get('functions', []))}
Imports: {', '.join(metadata.get('imports', []))}

{content[:8000]}
""".strip()
        
        embedding = vector_service.create_embedding(embedding_text)
        
        # Get file name from path
        file_name = file_path.split("/")[-1]
        
        # Count lines
        line_count = content.count("\n") + 1
        
        # Upsert into database
        self.db.execute(text("""
            INSERT INTO file_embeddings 
            (project_id, file_path, file_name, language, content, content_hash,
             file_size, line_count, embedding, metadata, indexed_at, updated_at)
            VALUES 
            (:project_id, :file_path, :file_name, :language, :content, :content_hash,
             :file_size, :line_count, :embedding, :metadata, :now, :now)
            ON CONFLICT (project_id, file_path) 
            DO UPDATE SET
                content = EXCLUDED.content,
                content_hash = EXCLUDED.content_hash,
                file_size = EXCLUDED.file_size,
                line_count = EXCLUDED.line_count,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata,
                indexed_at = EXCLUDED.indexed_at,
                updated_at = EXCLUDED.updated_at
        """), {
            "project_id": project_id,
            "file_path": file_path,
            "file_name": file_name,
            "language": language,
            "content": content,
            "content_hash": content_hash,
            "file_size": len(content.encode("utf-8")),
            "line_count": line_count,
            "embedding": embedding,
            "metadata": json.dumps(metadata),
            "now": datetime.utcnow()
        })
        self.db.commit()
        
        return True
    
    async def search_files(
        self,
        project_id: int,
        query: str,
        limit: int = 5,
        language: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search files by semantic similarity.
        """
        # Generate query embedding
        query_embedding = vector_service.create_embedding(query)
        
        # Convert embedding to PostgreSQL vector string format
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        
        # Build query - use string formatting for vector to avoid :: conflict
        if language:
            sql = f"""
                SELECT 
                    id, file_path, file_name, language, line_count,
                    1 - (embedding <=> '{embedding_str}'::vector) AS similarity,
                    metadata
                FROM file_embeddings
                WHERE project_id = :project_id
                AND embedding IS NOT NULL
                AND language = :language
                ORDER BY embedding <=> '{embedding_str}'::vector
                LIMIT :limit
            """
            params = {"project_id": project_id, "language": language, "limit": limit}
        else:
            sql = f"""
                SELECT 
                    id, file_path, file_name, language, line_count,
                    1 - (embedding <=> '{embedding_str}'::vector) AS similarity,
                    metadata
                FROM file_embeddings
                WHERE project_id = :project_id
                AND embedding IS NOT NULL
                ORDER BY embedding <=> '{embedding_str}'::vector
                LIMIT :limit
            """
            params = {"project_id": project_id, "limit": limit}
        
        results = self.db.execute(text(sql), params).fetchall()
        
        return [
            {
                "id": r[0],
                "file_path": r[1],
                "file_name": r[2],
                "language": r[3],
                "line_count": r[4],
                "similarity": round(r[5], 4),
                "metadata": r[6] if r[6] else {}
            }
            for r in results
        ]
    
    async def get_file_content(
        self,
        project_id: int,
        file_path: str
    ) -> Optional[str]:
        """Get indexed file content"""
        result = self.db.execute(text("""
            SELECT content FROM file_embeddings
            WHERE project_id = :project_id AND file_path = :file_path
        """), {"project_id": project_id, "file_path": file_path}).fetchone()
        
        return result[0] if result else None
    
    async def get_project_stats(self, project_id: int) -> Dict[str, Any]:
        """Get indexing statistics for project"""
        stats = self.db.execute(text("""
            SELECT 
                COUNT(*) as total_files,
                COUNT(DISTINCT language) as languages,
                SUM(line_count) as total_lines,
                SUM(file_size) as total_size,
                MAX(indexed_at) as last_indexed
            FROM file_embeddings
            WHERE project_id = :project_id
        """), {"project_id": project_id}).fetchone()
        
        by_language = self.db.execute(text("""
            SELECT language, COUNT(*) as count
            FROM file_embeddings
            WHERE project_id = :project_id
            GROUP BY language
            ORDER BY count DESC
        """), {"project_id": project_id}).fetchall()
        
        return {
            "total_files": stats[0] or 0,
            "languages": stats[1] or 0,
            "total_lines": stats[2] or 0,
            "total_size_kb": round((stats[3] or 0) / 1024, 2),
            "last_indexed": stats[4].isoformat() if stats[4] else None,
            "by_language": {r[0]: r[1] for r in by_language}
        }
    
    async def delete_project_index(self, project_id: int) -> int:
        """Delete all indexed files for project"""
        result = self.db.execute(text("""
            DELETE FROM file_embeddings WHERE project_id = :project_id
        """), {"project_id": project_id})
        self.db.commit()
        
        return result.rowcount