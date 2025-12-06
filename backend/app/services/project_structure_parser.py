"""
Project Structure Parser

Универсальный парсер для project_structure из БД.
Поддерживает 3 формата:
1. JSON (Git sync) - from git_service.py
2. Markdown (Debate Mode) - from debate_manager.py
3. Plain list (manual input)

Usage:
    from app.services.project_structure_parser import parse_project_structure
    
    file_specs = parse_project_structure(project.project_structure)
    for spec in file_specs:
        print(f"{spec.file_path} - {spec.language}")
"""

import json
import re
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class FileSpec:
    """
    File specification extracted from project_structure
    
    Attributes:
        file_path: Relative path to file (e.g., "src/types.d.ts")
        file_number: Sequential number from structure (1-based)
        description: Optional description of the file
        language: Detected programming language
    """
    file_path: str
    file_number: Optional[int] = None
    description: Optional[str] = None
    language: str = "unknown"
    
    def __post_init__(self):
        # Auto-detect language from file extension
        if self.language == "unknown":
            self.language = self._detect_language()
    
    def _detect_language(self) -> str:
        """Detect programming language from file extension"""
        ext_map = {
            '.py': 'python',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.md': 'markdown',
            '.json': 'json',
            '.html': 'html',
            '.css': 'css',
            '.scss': 'scss',
            '.txt': 'text',
            '.yml': 'yaml',
            '.yaml': 'yaml',
            '.sh': 'bash',
            '.sql': 'sql',
            '.go': 'go',
            '.rs': 'rust',
            '.java': 'java',
            '.cpp': 'cpp',
            '.c': 'c',
            '.h': 'c',
            '.hpp': 'cpp'
        }
        
        for ext, lang in ext_map.items():
            if self.file_path.endswith(ext):
                return lang
        
        return 'unknown'
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'file_path': self.file_path,
            'file_number': self.file_number,
            'description': self.description,
            'language': self.language
        }


def parse_project_structure(text: str) -> List[FileSpec]:
    """
    Universal parser for project_structure
    
    Supports:
    - JSON format (Git sync): {"source": "git", "files": [...]}
    - Markdown format (Debate Mode): [1] file.ts - Description
    - Plain list format: One file per line
    
    Args:
        text: project_structure string from database
        
    Returns:
        List of FileSpec objects
        
    Example:
        >>> structure = '{"source": "git", "files": [{"path": "src/index.ts"}]}'
        >>> files = parse_project_structure(structure)
        >>> print(files[0].file_path)
        src/index.ts
    """
    
    if not text or not text.strip():
        return []
    
    # Try JSON format first (most common from Git)
    try:
        data = json.loads(text)
        if isinstance(data, dict) and 'files' in data:
            return parse_json_format(data)
    except json.JSONDecodeError:
        pass
    
    # Try Markdown format (Debate Mode)
    if re.search(r'\[\d+\]', text):
        return parse_markdown_format(text)
    
    # Fallback to plain list
    return parse_plain_list(text)


def parse_json_format(data: dict) -> List[FileSpec]:
    """
    Parse Git sync JSON format
    
    Format:
    {
        "source": "git",
        "git_url": "github.com/user/repo",
        "files": [
            {"path": "src/index.ts", "type": "blob", "size": 1234},
            {"path": "src/", "type": "tree", "size": 0}
        ]
    }
    """
    files = data.get('files', [])
    result = []
    
    for i, file_info in enumerate(files, start=1):
        path = file_info.get('path', '')
        
        # Skip directories (type: "tree")
        if file_info.get('type') == 'tree':
            continue
        
        # Skip empty paths
        if not path or not path.strip():
            continue
        
        # Skip files with size 0 (often metadata)
        if file_info.get('size', 1) == 0:
            continue
        
        result.append(FileSpec(
            file_path=path,
            file_number=i,
            description=None,
            language="unknown"
        ))
    
    return result


def parse_markdown_format(text: str) -> List[FileSpec]:
    """
    Parse Markdown format from Debate Mode
    
    Format:
    [1] src/types.d.ts - Type definitions
    [2] src/logger.ts - Logger implementation
    [3] src/index.ts - Main entry point
    """
    pattern = r'\[(\d+)\]\s*([^\s\-\n]+)(?:\s*-\s*(.+?))?(?=\n|\[|$)'
    matches = re.finditer(pattern, text, re.MULTILINE)
    
    result = []
    for match in matches:
        file_number = int(match.group(1))
        file_path = match.group(2).strip()
        description = match.group(3).strip() if match.group(3) else None
        
        result.append(FileSpec(
            file_path=file_path,
            file_number=file_number,
            description=description,
            language="unknown"
        ))
    
    return result


def parse_plain_list(text: str) -> List[FileSpec]:
    """
    Parse plain list format
    
    Format:
    src/types.d.ts
    src/logger.ts
    src/index.ts
    """
    lines = text.strip().split('\n')
    result = []
    
    for i, line in enumerate(lines, start=1):
        line = line.strip()
        
        # Skip empty lines and comments
        if not line or line.startswith('#'):
            continue
        
        result.append(FileSpec(
            file_path=line,
            file_number=i,
            description=None,
            language="unknown"
        ))
    
    return result


def analyze_basic_dependencies(file_specs: List[FileSpec]) -> dict:
    """
    Analyze basic file dependencies using heuristics
    
    Rules:
    - types.d.ts / types.ts → imported by all files
    - index.ts / main.ts → imports all files in same folder
    - Files import types files from same/parent folders
    
    Args:
        file_specs: List of FileSpec objects
        
    Returns:
        Dictionary mapping file_path to list of dependency paths
        
    Example:
        >>> specs = [FileSpec("types.d.ts"), FileSpec("logger.ts")]
        >>> deps = analyze_basic_dependencies(specs)
        >>> print(deps["logger.ts"])
        ["types.d.ts"]
    """
    dependencies = {}
    
    # Find types files
    types_files = [
        f.file_path for f in file_specs 
        if 'types' in f.file_path.lower() and f.language in ['typescript', 'javascript']
    ]
    
    # Find index/main files
    entry_files = [
        f.file_path for f in file_specs
        if f.file_path.endswith(('index.ts', 'index.js', 'main.ts', 'main.js'))
    ]
    
    for spec in file_specs:
        deps = []
        
        # All files depend on types files (except types themselves)
        if spec.file_path not in types_files:
            for types_file in types_files:
                # Only add if in same or parent folder
                if _is_related_path(spec.file_path, types_file):
                    deps.append(types_file)
        
        # Index files depend on all files in same folder
        if spec.file_path in entry_files:
            folder = _get_folder(spec.file_path)
            for other_spec in file_specs:
                if other_spec.file_path == spec.file_path:
                    continue
                if _get_folder(other_spec.file_path) == folder:
                    deps.append(other_spec.file_path)
        
        if deps:
            dependencies[spec.file_path] = list(set(deps))  # Remove duplicates
    
    return dependencies


def _is_related_path(file_path: str, dependency_path: str) -> bool:
    """Check if file is in same or child folder as dependency"""
    file_parts = file_path.split('/')
    dep_parts = dependency_path.split('/')
    
    # Same folder or dependency is in parent folder
    return (
        file_parts[:-1] == dep_parts[:-1] or  # Same folder
        dep_parts[:-1] == file_parts[:-len(dep_parts)]  # Dependency in parent
    )


def _get_folder(file_path: str) -> str:
    """Get folder path from file path"""
    parts = file_path.split('/')
    return '/'.join(parts[:-1]) if len(parts) > 1 else ''


# Example usage for testing
if __name__ == "__main__":
    # Test Git format
    git_structure = '''
    {
        "source": "git",
        "files": [
            {"path": "src/types.d.ts", "type": "blob", "size": 500},
            {"path": "src/logger.ts", "type": "blob", "size": 1000},
            {"path": "src/index.ts", "type": "blob", "size": 800}
        ]
    }
    '''
    
    files = parse_project_structure(git_structure)
    print("Git format test:")
    for f in files:
        print(f"  {f.file_path} - {f.language}")
    
    # Test Markdown format
    markdown_structure = '''
    [1] src/types.d.ts - Type definitions
    [2] src/logger.ts - Logger implementation
    [3] src/index.ts - Main entry point
    '''
    
    files = parse_project_structure(markdown_structure)
    print("\nMarkdown format test:")
    for f in files:
        print(f"  [{f.file_number}] {f.file_path} - {f.description}")
    
    # Test dependencies
    deps = analyze_basic_dependencies(files)
    print("\nDependencies:")
    for file_path, file_deps in deps.items():
        print(f"  {file_path} depends on: {', '.join(file_deps)}")