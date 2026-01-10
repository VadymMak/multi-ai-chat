# File: backend/app/services/query_classifier.py
"""
Query Classifier - Determines the type of search query

This classifier analyzes user queries to determine the best search strategy:
- FILENAME: User is looking for a specific file
- SYMBOL: User is looking for a class/function/variable
- PATTERN: User is searching for code patterns
- SEMANTIC: Natural language conceptual search

Examples:
    "file_indexer.py" → FILENAME
    "FileIndexer" → SYMBOL (class)
    "search_files" → SYMBOL (function)
    "async def index" → PATTERN
    "how to index files" → SEMANTIC
"""

from enum import Enum
import re
from typing import Optional, List, Dict


# ====================================================================
# QUERY TYPES
# ====================================================================

class QueryType(Enum):
    """Types of search queries"""
    FILENAME = "filename"      # Searching for a file by name
    SYMBOL = "symbol"          # Searching for class/function/variable
    PATTERN = "pattern"        # Searching for code patterns
    SEMANTIC = "semantic"      # Natural language search
    HYBRID = "hybrid"          # Try multiple strategies


# ====================================================================
# DETECTION PATTERNS
# ====================================================================

# File extensions that indicate filename search
FILE_EXTENSIONS = [
    ".ts", ".tsx", ".js", ".jsx", ".py", ".html", ".css", ".json",
    ".md", ".sql", ".sh", ".go", ".rs", ".java", ".php", ".rb"
]

# Code keywords that indicate pattern search
CODE_KEYWORDS = [
    "async", "def", "function", "class", "interface", "type",
    "import", "export", "const", "let", "var", "return",
    "if", "else", "for", "while", "try", "catch"
]

# Words that indicate natural language search
NATURAL_LANGUAGE_WORDS = [
    "how", "what", "where", "when", "why", "who",
    "find", "show", "get", "list", "explain", "describe",
    "is", "are", "does", "do", "can", "should"
]


# ====================================================================
# HELPER FUNCTIONS
# ====================================================================

def has_file_extension(query: str) -> bool:
    """
    Check if query contains a file extension.
    
    Examples:
        "file_indexer.py" → True
        "config.json" → True
        "FileIndexer" → False
    """
    query_lower = query.lower()
    return any(ext in query_lower for ext in FILE_EXTENSIONS)


def is_camel_case(query: str) -> bool:
    """
    Check if query is in CamelCase or PascalCase.
    
    CamelCase typically indicates a class name.
    
    Examples:
        "FileIndexer" → True
        "QueryType" → True
        "file_indexer" → False
        "search_files" → False
    """
    # Must start with uppercase
    if not query or not query[0].isupper():
        return False
    
    # Must have at least one lowercase letter
    if not any(c.islower() for c in query):
        return False
    
    # Must have at least one uppercase letter after the first
    if not any(c.isupper() for c in query[1:]):
        return False
    
    # Should not have underscores (that's snake_case)
    if "_" in query:
        return False
    
    return True


def is_snake_case(query: str) -> bool:
    """
    Check if query is in snake_case.
    
    snake_case typically indicates a function or variable name.
    
    Examples:
        "search_files" → True
        "file_indexer" → True
        "FileIndexer" → False
    """
    # Must be all lowercase with underscores
    if not query:
        return False
    
    # Should contain at least one underscore
    if "_" not in query:
        return False
    
    # All letters should be lowercase
    letters = [c for c in query if c.isalpha()]
    if not letters:
        return False
    
    return all(c.islower() for c in letters)


def has_code_keywords(query: str) -> bool:
    """
    Check if query contains code keywords.
    
    Examples:
        "async def index" → True
        "class FileIndexer" → True
        "search files" → False
    """
    query_lower = query.lower()
    words = query_lower.split()
    return any(keyword in words for keyword in CODE_KEYWORDS)


def has_natural_language_indicators(query: str) -> bool:
    """
    Check if query looks like natural language.
    
    Examples:
        "how to index files" → True
        "what is authentication" → True
        "FileIndexer" → False
    """
    query_lower = query.lower()
    words = query_lower.split()
    
    # Check for question words
    if any(word in words for word in NATURAL_LANGUAGE_WORDS):
        return True
    
    # Check if query has 4+ words (likely a sentence)
    if len(words) >= 4:
        return True
    
    return False


def looks_like_function_pattern(query: str) -> bool:
    """
    Check if query looks like a function pattern.
    
    Examples:
        "search_files()" → True
        "def search" → True
        "async search_files" → True
    """
    query_lower = query.lower()
    
    # Has parentheses
    if "(" in query or ")" in query:
        return True
    
    # Starts with function keywords
    if query_lower.startswith(("def ", "async ", "function ")):
        return True
    
    return False


def is_path_like(query: str) -> bool:
    """
    Check if query looks like a file path.
    
    Examples:
        "backend/app/services/file_indexer.py" → True
        "src/components/Header.tsx" → True
        "FileIndexer" → False
    """
    # Contains slashes
    if "/" in query or "\\" in query:
        return True
    
    # Contains directory indicators
    if query.startswith(("./", "../", "/")):
        return True
    
    return False


# ====================================================================
# MAIN CLASSIFIER
# ====================================================================

def classify_query(query: str) -> QueryType:
    """
    Classify search query to determine best search strategy.
    
    Classification priority:
    1. FILENAME - if looks like a file or path
    2. PATTERN - if contains code keywords
    3. SYMBOL - if looks like class/function name
    4. SEMANTIC - natural language
    
    Args:
        query: Search query string
        
    Returns:
        QueryType indicating best search strategy
        
    Examples:
        >>> classify_query("file_indexer.py")
        QueryType.FILENAME
        
        >>> classify_query("FileIndexer")
        QueryType.SYMBOL
        
        >>> classify_query("search_files")
        QueryType.SYMBOL
        
        >>> classify_query("async def index")
        QueryType.PATTERN
        
        >>> classify_query("how to index files")
        QueryType.SEMANTIC
    """
    
    # Clean query
    query = query.strip()
    
    if not query:
        return QueryType.SEMANTIC
    
    # ========== PRIORITY 1: FILENAME ==========
    # Check if query looks like a filename or path
    if has_file_extension(query) or is_path_like(query):
        return QueryType.FILENAME
    
    # ========== PRIORITY 2: PATTERN ==========
    # Check if query contains code patterns
    if has_code_keywords(query) or looks_like_function_pattern(query):
        return QueryType.PATTERN
    
    # ========== PRIORITY 3: SYMBOL ==========
    # Check if query looks like a class name (CamelCase)
    if is_camel_case(query):
        return QueryType.SYMBOL
    
    # Check if query looks like a function name (snake_case)
    if is_snake_case(query):
        return QueryType.SYMBOL
    
    # Single word without special chars might be a symbol
    if len(query.split()) == 1 and query.isalnum():
        # If it's all uppercase, likely a constant
        if query.isupper() and len(query) > 1:
            return QueryType.SYMBOL
        # Single lowercase word might be variable/function
        if query.islower():
            return QueryType.SYMBOL
    
    # ========== PRIORITY 4: SEMANTIC ==========
    # Everything else is semantic search
    return QueryType.SEMANTIC


# ====================================================================
# BATCH CLASSIFICATION (for testing)
# ====================================================================

def classify_queries_batch(queries: List[str]) -> Dict[str, QueryType]:
    """
    Classify multiple queries at once.
    Useful for testing and debugging.
    
    Args:
        queries: List of query strings
        
    Returns:
        Dict mapping query to its QueryType
    """
    return {query: classify_query(query) for query in queries}


# ====================================================================
# TESTING EXAMPLES
# ====================================================================

if __name__ == "__main__":
    """
    Run this file directly to see classification examples.
    
    Usage:
        python -m app.services.query_classifier
    """
    
    test_queries = [
        # FILENAME queries
        "file_indexer.py",
        "config.json",
        "src/extension.ts",
        "backend/app/services/file_indexer.py",
        
        # SYMBOL queries (classes)
        "FileIndexer",
        "QueryType",
        "GitHubClient",
        
        # SYMBOL queries (functions)
        "search_files",
        "index_project",
        "classify_query",
        
        # PATTERN queries
        "async def index",
        "class FileIndexer",
        "import React",
        "search_files()",
        
        # SEMANTIC queries
        "how to index files",
        "what is authentication",
        "find error handling code",
        "where is the database connection",
        
        # Edge cases
        "test",  # single word
        "API",   # all caps
        "get_user_by_id",  # snake_case
    ]
    
    print("=" * 60)
    print("QUERY CLASSIFICATION TEST")
    print("=" * 60)
    
    results = classify_queries_batch(test_queries)
    
    # Group by type
    by_type = {}
    for query, qtype in results.items():
        if qtype not in by_type:
            by_type[qtype] = []
        by_type[qtype].append(query)
    
    # Print results
    for qtype in QueryType:
        if qtype in by_type:
            print(f"\n{qtype.value.upper()}:")
            for query in by_type[qtype]:
                print(f"  ✓ {query}")
    
    print("\n" + "=" * 60)