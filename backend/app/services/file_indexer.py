# File: backend/app/services/file_indexer.py
"""
File Indexer Service - Index project files into pgvector for semantic search

This service:
1. Fetches files from Git repository (via GitHub API)
2. Generates embeddings using OpenAI text-embedding-3-small
3. Stores in file_embeddings table
4. Provides semantic search across codebase
5. NEW: Saves file dependencies to file_dependencies table

Use cases:
- "Find files related to authentication" → returns auth files
- "Where is error handling implemented?" → returns error handler files
- Debug assistance with full codebase context
- Smart Context: find dependencies for a file
"""

import hashlib
import json
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone

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

# External packages to skip when resolving imports
PYTHON_EXTERNAL_PACKAGES = {
    # Stdlib
    "os", "sys", "re", "json", "datetime", "typing", "logging", "hashlib",
    "pathlib", "collections", "functools", "itertools", "asyncio", "time",
    "uuid", "base64", "copy", "math", "random", "io", "contextlib", "enum",
    "dataclasses", "abc", "traceback", "inspect", "importlib", "warnings",
    # Common packages
    "fastapi", "sqlalchemy", "pydantic", "httpx", "requests", "numpy",
    "pandas", "pytest", "openai", "anthropic", "tiktoken", "redis",
    "celery", "boto3", "passlib", "jwt", "dotenv", "uvicorn", "starlette",
    "pgvector", "alembic", "aiohttp", "aiofiles", "cryptography", "bcrypt",
}


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
# NEW: IMPORT RESOLUTION FUNCTIONS (Phase 2)
# ====================================================================

def resolve_python_import(
    import_module: str,
    source_file: str,
    project_id: int,
    db: Session
) -> Optional[str]:
    """
    Resolve Python import to actual file path in database.
    
    Examples:
    - "app.services.vector_service" → "backend/app/services/vector_service.py"
    - "app.memory.models" → "backend/app/memory/models.py"
    - "os" → None (stdlib)
    - "fastapi" → None (external package)
    """
    # Get first part of import
    first_part = import_module.split(".")[0]
    if first_part in PYTHON_EXTERNAL_PACKAGES:
        return None
    
    # Convert module path to possible file paths
    module_path = import_module.replace(".", "/")
    possible_paths = [
        f"{module_path}.py",
        f"backend/{module_path}.py",
        f"src/{module_path}.py",
        f"{module_path}/__init__.py",
        f"backend/{module_path}/__init__.py",
    ]
    
    # Search in database
    for path_pattern in possible_paths:
        result = db.execute(text("""
            SELECT file_path FROM file_embeddings
            WHERE project_id = :project_id 
              AND (file_path = :path OR file_path LIKE :like_path)
            LIMIT 1
        """), {
            "project_id": project_id,
            "path": path_pattern,
            "like_path": f"%/{path_pattern}"
        }).fetchone()
        
        if result:
            return result[0]
    
    return None


def resolve_typescript_import(
    import_path: str,
    source_file: str,
    project_id: int,
    db: Session
) -> Optional[str]:
    """
    Resolve TypeScript/JavaScript import to actual file path.
    
    Examples:
    - "./utils" → "src/utils.ts"
    - "../services/apiService" → "src/services/apiService.ts"
    - "@/components/Button" → "src/components/Button.tsx"
    - "react" → None (external)
    """
    # Skip node_modules / external packages
    if not import_path.startswith(".") and not import_path.startswith("@/"):
        return None
    
    # Handle @/ alias (typically maps to src/)
    if import_path.startswith("@/"):
        import_path = "./" + import_path[2:]
        source_file = "src/index.ts"
    
    # Get directory of source file
    source_dir = "/".join(source_file.replace("\\", "/").split("/")[:-1])
    
    # Resolve relative path
    parts = import_path.split("/")
    resolved_parts = source_dir.split("/") if source_dir else []
    
    for part in parts:
        if part == ".":
            continue
        elif part == "..":
            if resolved_parts:
                resolved_parts.pop()
        else:
            resolved_parts.append(part)
    
    base_path = "/".join(resolved_parts)
    
    # Try different extensions
    extensions = [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js"]
    
    for ext in extensions:
        test_path = base_path + ext
        
        result = db.execute(text("""
            SELECT file_path FROM file_embeddings
            WHERE project_id = :project_id 
              AND (file_path = :path OR file_path LIKE :like_path)
            LIMIT 1
        """), {
            "project_id": project_id,
            "path": test_path,
            "like_path": f"%/{test_path}"
        }).fetchone()
        
        if result:
            return result[0]
    
    return None


def resolve_import_path(
    import_module: str,
    source_file: str,
    language: str,
    project_id: int,
    db: Session
) -> Optional[str]:
    """
    Universal import resolver - dispatches to language-specific resolver.
    """
    if language == "python":
        return resolve_python_import(import_module, source_file, project_id, db)
    elif language in ["typescript", "javascript"]:
        return resolve_typescript_import(import_module, source_file, project_id, db)
    else:
        return None


def save_file_dependencies(
    project_id: int,
    source_file: str,
    imports: List[str],
    language: str,
    db: Session
) -> int:
    """
    Save resolved dependencies to file_dependencies table.
    
    Args:
        project_id: Project ID
        source_file: Path of the file that has imports
        imports: List of import strings from extract_metadata()
        language: Language of the source file
        db: Database session
        
    Returns:
        Number of dependencies saved
    """
    if not imports:
        return 0
    
    saved_count = 0
    
    # First, delete old dependencies for this file
    db.execute(text("""
        DELETE FROM file_dependencies 
        WHERE project_id = :project_id AND source_file = :source_file
    """), {"project_id": project_id, "source_file": source_file})
    
    for import_module in imports:
        # Try to resolve to actual file
        target_file = resolve_import_path(
            import_module=import_module,
            source_file=source_file,
            language=language,
            project_id=project_id,
            db=db
        )
        
        # Skip if couldn't resolve (external package)
        if not target_file:
            # Only save unresolved relative imports
            if import_module.startswith(".") or import_module.startswith("@/"):
                target_file = import_module
                dep_type = "import_unresolved"
            else:
                continue  # Skip external packages
        else:
            dep_type = "import"
        
        # Skip self-references
        if target_file == source_file:
            continue
        
        # Insert dependency
        try:
            db.execute(text("""
                INSERT INTO file_dependencies 
                (project_id, source_file, target_file, dependency_type, imports_what, created_at)
                VALUES (:project_id, :source_file, :target_file, :dep_type, :imports_what, :now)
                ON CONFLICT (project_id, source_file, target_file) 
                DO UPDATE SET 
                    dependency_type = EXCLUDED.dependency_type,
                    imports_what = EXCLUDED.imports_what,
                    created_at = EXCLUDED.created_at
            """), {
                "project_id": project_id,
                "source_file": source_file,
                "target_file": target_file,
                "dep_type": dep_type,
                "imports_what": json.dumps([import_module]),
                "now": datetime.now(timezone.utc)
            })
            saved_count += 1
        except Exception as e:
            logger.warning(f"Failed to save dependency {source_file} → {target_file}: {e}")
    
    return saved_count


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
            "dependencies_saved": 0,  # NEW
            "errors_list": []
        }
        
        for i, file_info in enumerate(files_to_index, 1):
            file_path = file_info["path"]
            
            try:
                indexed, deps_count = await self._index_file(
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
                    stats["dependencies_saved"] += deps_count  # NEW
                    logger.info(f"  ✅ [{i}/{len(files_to_index)}] {file_path} ({deps_count} deps)")
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
   Dependencies saved: {stats['dependencies_saved']}  ← NEW!
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
    ) -> Tuple[bool, int]:
        """
        Index a single file.
        
        Returns: (indexed: bool, dependencies_count: int)
        """
        # Check if file already indexed and unchanged
        if not force_reindex and file_sha:
            existing = self.db.execute(text("""
                SELECT content_hash FROM file_embeddings
                WHERE project_id = :project_id AND file_path = :file_path
            """), {"project_id": project_id, "file_path": file_path}).fetchone()
            
            if existing and existing[0] == file_sha:
                return False, 0  # File unchanged
        
        # Get file content
        content = await self.github.get_raw_file(owner, repo, file_path, branch)
        
        # Get language
        language = get_file_language(file_path)
        
        # Compute hash
        content_hash = file_sha or compute_content_hash(content)
        
        # Extract metadata
        metadata = extract_metadata(content, language) if language else {}
        
        # Generate embedding
        embedding_text = f"""
File: {file_path}
Language: {language}
Classes: {', '.join(metadata.get('classes', []))}
Functions: {', '.join(metadata.get('functions', []))}
Imports: {', '.join(metadata.get('imports', []))}

{content[:8000]}
""".strip()
        
        embedding = vector_service.create_embedding(embedding_text)
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        
        # Get file name from path
        file_name = file_path.split("/")[-1]
        
        # Count lines
        line_count = content.count("\n") + 1
        
        # Upsert into database
        self.db.execute(text(f"""
            INSERT INTO file_embeddings 
            (project_id, file_path, file_name, language, content, content_hash,
             file_size, line_count, embedding, metadata, indexed_at, updated_at)
            VALUES 
            (:project_id, :file_path, :file_name, :language, :content, :content_hash,
             :file_size, :line_count, '{embedding_str}'::vector, :metadata, :now, :now)
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
            "metadata": json.dumps(metadata),
            "now": datetime.now(timezone.utc)
        })
        
        # ============================================================
        # NEW: SAVE FILE DEPENDENCIES (Phase 2)
        # ============================================================
        deps_count = 0
        if language and metadata.get("imports"):
            deps_count = save_file_dependencies(
                project_id=project_id,
                source_file=file_path,
                imports=metadata["imports"],
                language=language,
                db=self.db
            )
        # ============================================================
        
        self.db.commit()
        
        return True, deps_count
    
    async def search_by_filename(self, project_id: int, query: str, limit: int = 5, db: Session = None) -> List[Dict]:
        """Search by filename using SQL LIKE"""
        db = db or self.db
        if not db:
            return []
        try:
            search_pattern = f"%{query}%"
            sql = text("""
                SELECT id, file_path, file_name, language, line_count, metadata,
                       1.0 as similarity, 'filename' as match_type
                FROM file_embeddings
                WHERE project_id = :project_id AND embedding IS NOT NULL
                  AND (file_path ILIKE :pattern OR file_name ILIKE :pattern)
                ORDER BY CASE WHEN file_name ILIKE :pattern THEN 1 ELSE 2 END, file_name
                LIMIT :limit
            """)
            result = db.execute(sql, {"project_id": project_id, "pattern": search_pattern, "limit": limit})
            files = []
            for row in result:
                metadata = row.metadata if row.metadata else {}
                files.append({"id": row.id, "file_path": row.file_path, "file_name": row.file_name,
                             "language": row.language, "line_count": row.line_count, "similarity": row.similarity,
                             "match_type": row.match_type, "metadata": metadata})
            print(f"[FILENAME] '{query}' → {len(files)} files")
            return files
        except Exception as e:
            print(f"[ERROR] Filename search: {e}")
            return []
        
    async def search_by_symbol(self, project_id: int, query: str, limit: int = 5, db: Session = None) -> List[Dict]:
        """Search for class/function names in metadata"""
        db = db or self.db
        if not db:
            return []
        try:
            search_pattern = f"%{query}%"
            sql = text("""
                SELECT id, file_path, file_name, language, line_count, metadata,
                       1.0 as similarity, 'symbol' as match_type
                FROM file_embeddings
                WHERE project_id = :project_id AND embedding IS NOT NULL
                  AND (metadata->>'classes' ILIKE :pattern
                       OR metadata->>'functions' ILIKE :pattern
                       OR metadata->>'exports' ILIKE :pattern)
                ORDER BY file_name
                LIMIT :limit
            """)
            result = db.execute(sql, {"project_id": project_id, "pattern": search_pattern, "limit": limit})
            files = []
            for row in result:
                metadata = row.metadata if row.metadata else {}
                files.append({"id": row.id, "file_path": row.file_path, "file_name": row.file_name,
                             "language": row.language, "line_count": row.line_count, "similarity": row.similarity,
                             "match_type": row.match_type, "metadata": metadata})
            print(f"[SYMBOL] '{query}' → {len(files)} files")
            return files
        except Exception as e:
            print(f"[ERROR] Symbol search: {e}")
            return []
        
    async def search_by_pattern(self, project_id: int, query: str, limit: int = 5, db: Session = None) -> List[Dict]:
        """Search for code patterns"""
        db = db or self.db
        if not db:
            return []
        try:
            search_pattern = f"%{query}%"
            sql = text("""
                SELECT id, file_path, file_name, language, line_count, metadata,
                       0.9 as similarity, 'pattern' as match_type
                FROM file_embeddings
                WHERE project_id = :project_id AND embedding IS NOT NULL
                  AND file_path ILIKE :pattern
                ORDER BY file_name
                LIMIT :limit
            """)
            result = db.execute(sql, {"project_id": project_id, "pattern": search_pattern, "limit": limit})
            files = []
            for row in result:
                metadata = row.metadata if row.metadata else {}
                files.append({"id": row.id, "file_path": row.file_path, "file_name": row.file_name,
                             "language": row.language, "line_count": row.line_count, "similarity": row.similarity,
                             "match_type": row.match_type, "metadata": metadata})
            print(f"[PATTERN] '{query}' → {len(files)} files")
            return files
        except Exception as e:
            print(f"[ERROR] Pattern search: {e}")
            return []
    
    async def search_semantic(self, project_id: int, query: str, limit: int = 5, db: Session = None) -> List[Dict]:
        """Semantic search using pgvector"""
        db = db or self.db
        if not db:
            print("[ERROR] No database session available")
            return []
        
        try:
            query_embedding = vector_service.create_embedding(query)
            
            sql = text("""
                SELECT id, file_path, file_name, language, line_count, metadata,
                       1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity,
                       'semantic' as match_type
                FROM file_embeddings
                WHERE project_id = :project_id AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                LIMIT :limit
            """)
            result = db.execute(sql, {"project_id": project_id, "query_embedding": query_embedding, "limit": limit})
            files = []
            for row in result:
                metadata = row.metadata if row.metadata else {}
                files.append({"id": row.id, "file_path": row.file_path, "file_name": row.file_name,
                             "language": row.language, "line_count": row.line_count, 
                             "similarity": float(row.similarity), "match_type": row.match_type, "metadata": metadata})
            print(f"[SEMANTIC] '{query}' → {len(files)} files")
            return files
        except Exception as e:
            print(f"[ERROR] Semantic search: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    async def search_files(self, project_id: int, query: str, limit: int = 5, 
                          language: Optional[str] = None, db: Session = None) -> List[Dict]:
        """Intelligent search with query classification"""
        from .query_classifier_with_logging import classify_and_log, QueryType
        
        db = db or self.db
        if not db:
            return await self.search_semantic(project_id, query, limit, db)
        
        try:
            query_type = classify_and_log(query=query, project_id=project_id, db=db, 
                                          user_id=None, enable_logging=True)
            print(f"[CLASSIFIER] '{query}' → {query_type.value}")
            
            results = []
            if query_type == QueryType.FILENAME:
                results = await self.search_by_filename(project_id, query, limit, db)
            elif query_type == QueryType.SYMBOL:
                results = await self.search_by_symbol(project_id, query, limit, db)
            elif query_type == QueryType.PATTERN:
                results = await self.search_by_pattern(project_id, query, limit, db)
            else:
                results = await self.search_semantic(project_id, query, limit, db)
            
            if len(results) < 3 and query_type != QueryType.SEMANTIC:
                print(f"[FALLBACK] Only {len(results)} results, trying semantic...")
                semantic_results = await self.search_semantic(project_id, query, limit, db)
                existing_paths = {r['file_path'] for r in results}
                for sr in semantic_results:
                    if sr['file_path'] not in existing_paths:
                        results.append(sr)
                        if len(results) >= limit:
                            break
            
            print(f"[SEARCH] Total: {len(results)} results")
            return results
        except Exception as e:
            print(f"[ERROR] Search failed: {e}")
            import traceback
            traceback.print_exc()
            return await self.search_semantic(project_id, query, limit, db)
    
    # ====================================================================
    # NEW: DEPENDENCY QUERY METHODS (Phase 2)
    # ====================================================================
    
    async def get_file_dependencies(
        self,
        project_id: int,
        file_path: str
    ) -> List[Dict[str, Any]]:
        """
        Get all files that this file imports (outgoing dependencies).
        
        Args:
            project_id: Project ID
            file_path: Path of the file to get dependencies for
            
        Returns:
            List of dependency info dicts
        """
        result = self.db.execute(text("""
            SELECT fd.target_file, fd.dependency_type, fd.imports_what,
                   fe.language, fe.line_count
            FROM file_dependencies fd
            LEFT JOIN file_embeddings fe 
                ON fe.project_id = fd.project_id AND fe.file_path = fd.target_file
            WHERE fd.project_id = :project_id AND fd.source_file = :file_path
            ORDER BY fd.target_file
        """), {"project_id": project_id, "file_path": file_path}).fetchall()
        
        return [
            {
                "file_path": row[0],
                "dependency_type": row[1],
                "imports_what": json.loads(row[2]) if row[2] else [],
                "language": row[3],
                "line_count": row[4],
            }
            for row in result
        ]
    
    async def get_file_dependents(
        self,
        project_id: int,
        file_path: str
    ) -> List[Dict[str, Any]]:
        """
        Get all files that import this file (incoming dependencies).
        
        Args:
            project_id: Project ID
            file_path: Path of the file to find dependents for
            
        Returns:
            List of dependent file info dicts
        """
        result = self.db.execute(text("""
            SELECT fd.source_file, fd.dependency_type, fd.imports_what,
                   fe.language, fe.line_count
            FROM file_dependencies fd
            LEFT JOIN file_embeddings fe 
                ON fe.project_id = fd.project_id AND fe.file_path = fd.source_file
            WHERE fd.project_id = :project_id AND fd.target_file = :file_path
            ORDER BY fd.source_file
        """), {"project_id": project_id, "file_path": file_path}).fetchall()
        
        return [
            {
                "file_path": row[0],
                "dependency_type": row[1],
                "imports_what": json.loads(row[2]) if row[2] else [],
                "language": row[3],
                "line_count": row[4],
            }
            for row in result
        ]
    
    async def get_dependency_stats(self, project_id: int) -> Dict[str, Any]:
        """Get dependency statistics for project"""
        stats = self.db.execute(text("""
            SELECT 
                COUNT(*) as total_dependencies,
                COUNT(DISTINCT source_file) as files_with_imports,
                COUNT(DISTINCT target_file) as files_imported
            FROM file_dependencies
            WHERE project_id = :project_id AND dependency_type = 'import'
        """), {"project_id": project_id}).fetchone()
        
        return {
            "total_dependencies": stats[0] or 0,
            "files_with_imports": stats[1] or 0,
            "files_imported": stats[2] or 0,
        }
    
    # ====================================================================
    # EXISTING METHODS (unchanged)
    # ====================================================================
    
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
        
        # NEW: Include dependency stats
        dep_stats = await self.get_dependency_stats(project_id)
        
        return {
            "total_files": stats[0] or 0,
            "languages": stats[1] or 0,
            "total_lines": stats[2] or 0,
            "total_size_kb": round((stats[3] or 0) / 1024, 2),
            "last_indexed": stats[4].isoformat() if stats[4] else None,
            "by_language": {r[0]: r[1] for r in by_language},
            "dependencies": dep_stats,  # NEW
        }
    
    async def delete_project_index(self, project_id: int) -> int:
        """Delete all indexed files for project"""
        # Delete dependencies first
        self.db.execute(text("""
            DELETE FROM file_dependencies WHERE project_id = :project_id
        """), {"project_id": project_id})
        
        # Then delete files
        result = self.db.execute(text("""
            DELETE FROM file_embeddings WHERE project_id = :project_id
        """), {"project_id": project_id})
        self.db.commit()
        
        return result.rowcount