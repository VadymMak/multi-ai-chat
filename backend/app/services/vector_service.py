"""
Vector Service for Semantic Search using pgvector and OpenAI embeddings.

This service provides:
- Embedding generation using OpenAI text-embedding-3-small
- Vector storage in PostgreSQL with pgvector
- Semantic search using cosine similarity
- RAG context retrieval for conversation history

Cost: $0.02 per 1M tokens (text-embedding-3-small)
Expected: < $0.01 per user per month
"""

from openai import OpenAI
from typing import List, Dict, Any, Optional
import os
import httpx
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.orm import Session

# Embedding model configuration
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536  # text-embedding-3-small dimension

# Lazy OpenAI client initialization (matches openai_provider.py pattern)
_client = None

def _load_api_key_from_env() -> str:
    """
    Load OpenAI API key with proper .env file resolution.
    This function ensures we get the REAL key from .env file,
    not a masked version from os.environ.
    
    Returns:
        API key string
        
    Raises:
        RuntimeError: If no valid key found
    """
    # ============================================================
    # METHOD 1: Try os.environ first (if already loaded correctly)
    # ============================================================
    key_direct = os.environ.get("OPENAI_API_KEY")
    
    # Only accept if key is long enough (not masked)
    if key_direct and len(key_direct) > 50:
        print(f"[Embedding] Using key from os.environ (length: {len(key_direct)})")
        return key_direct
    
    # ============================================================
    # METHOD 2: Force reload from .env file
    # ============================================================
    try:
        from dotenv import load_dotenv, dotenv_values
        
        # Find .env file
        # Path: services/vector_service.py -> app/ -> backend/ -> .env
        current_file = Path(__file__)           # vector_service.py
        app_dir = current_file.parent.parent    # app/
        backend_dir = app_dir.parent            # backend/
        env_path = backend_dir / ".env"         # backend/.env
        
        print(f"[Embedding] Looking for .env at: {env_path}")
        
        if env_path.exists():
            # Load fresh from file
            env_vars = dotenv_values(env_path)
            file_key = env_vars.get("OPENAI_API_KEY")
            
            if file_key and len(file_key) > 50:
                print(f"[Embedding] Loaded key from .env file (length: {len(file_key)})")
                
                # Also reload into environment for next time
                load_dotenv(env_path, override=True)
                
                return file_key
            elif file_key:
                print(f"[Embedding] WARNING: Key in .env too short ({len(file_key)} chars)")
        else:
            print(f"[Embedding] WARNING: .env file not found at {env_path}")
            
            # Try alternative path (project root)
            project_root = backend_dir.parent
            alt_env_path = project_root / ".env"
            
            print(f"[Embedding] Trying alternative: {alt_env_path}")
            
            if alt_env_path.exists():
                env_vars = dotenv_values(alt_env_path)
                file_key = env_vars.get("OPENAI_API_KEY")
                
                if file_key and len(file_key) > 50:
                    print(f"[Embedding] Loaded key from alternative path (length: {len(file_key)})")
                    load_dotenv(alt_env_path, override=True)
                    return file_key
    
    except Exception as e:
        print(f"[Embedding] Error loading .env: {e}")
    
    # ============================================================
    # METHOD 3: Try alternative environment variable names
    # ============================================================
    alternative_keys = [
        "CHATITNOW_API_KEY",
        "OPEN_API_KEY",
        "OPENAI_KEY"
    ]
    
    for alt_name in alternative_keys:
        alt_key = os.environ.get(alt_name)
        if alt_key and len(alt_key) > 50:
            print(f"[Embedding] Using key from {alt_name} (length: {len(alt_key)})")
            return alt_key
    
    # ============================================================
    # NO VALID KEY FOUND
    # ============================================================
    raise RuntimeError(
        "OPENAI_API_KEY not found or invalid. "
        "Please ensure it's set in backend/.env and has length 160+ characters."
    )


def _get_openai_client():
    """Get OpenAI client with proper HTTP configuration and key loading"""
    # Load API key with proper .env resolution
    api_key = _load_api_key_from_env()
    
    # Validate key format
    if not api_key.startswith("sk-"):
        raise RuntimeError(f"Invalid OpenAI key format: must start with 'sk-'")
    
    if len(api_key) < 50:
        raise RuntimeError(
            f"OpenAI key too short: {len(api_key)} chars (expected 160+). "
            "Key may be truncated or masked."
        )
    
    print(f"[Embedding] Creating OpenAI client with valid key (length: {len(api_key)})")
    
    # Create HTTP client without proxy (same as openai_provider.py)
    http_client = httpx.Client(
        timeout=httpx.Timeout(60.0, connect=10.0),
        trust_env=False  # Don't read proxy from environment
    )
    
    return OpenAI(api_key=api_key, http_client=http_client)

def _get_client():
    """Lazy initialization of OpenAI client"""
    global _client
    if _client is None:
        _client = _get_openai_client()
    return _client


def create_embedding(text: str) -> List[float]:
    """
    Generate embedding vector using OpenAI text-embedding-3-small.
    
    Args:
        text: Input text to embed
        
    Returns:
        List of floats representing the embedding vector
        
    Cost: $0.02 per 1M tokens
    """
    try:
        client = _get_client()
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"[Embedding Generation Error] {e}")
        raise


def store_message_with_embedding(
    db: Session,
    message_id: int,
    content: str,
    table_name: str = "memory_entries"
) -> None:
    """
    Generate and store embedding for a message.
    
    Only generates embeddings for user/assistant messages to optimize cost.
    Silently fails if pgvector is not available (SQLite mode).
    
    Args:
        db: Database session
        message_id: ID of the message to embed
        content: Message content to embed
        table_name: Name of the table storing messages (default: memory_entries)
    """
    try:
        # Generate embedding
        embedding = create_embedding(content)
        
        # Update message with embedding vector
        db.execute(
            text(f"UPDATE {table_name} SET embedding = :embedding WHERE id = :id"),
            {"embedding": embedding, "id": message_id}
        )
        db.commit()
        print(f"[Embedding] Stored for message {message_id}")
        
    except Exception as e:
        print(f"[Embedding Storage Error] Message {message_id}: {e}")
        db.rollback()
        # Don't raise - allow graceful degradation


def search_similar_messages(
    db: Session,
    query: str,
    session_id: str,
    limit: int = 5,
    table_name: str = "memory_entries",
    session_column: str = "chat_session_id"
) -> List[Dict[str, Any]]:
    """
    Perform semantic search using pgvector cosine similarity.
    
    Uses the <=> operator for cosine distance (lower = more similar).
    
    Args:
        db: Database session
        query: Search query text
        session_id: Chat session ID to search within
        limit: Maximum number of results to return
        table_name: Name of the table storing messages
        session_column: Column name for session ID
        
    Returns:
        List of dictionaries containing:
        - id: Message ID
        - content: Message content
        - sender: Message sender
        - created_at: Timestamp
        - similarity: Similarity score (0-1, higher = more similar)
    """
    try:
        # Generate query embedding
        query_embedding = create_embedding(query)
        
        # Perform vector similarity search
        # <=> is pgvector's cosine distance operator
        # ✅ NEW CODE:
        # ✅ NEW CODE:
        results = db.execute(
            text(f"""
                SELECT id, raw_text, summary, is_summary, timestamp,
                    embedding <=> CAST(:query_embedding AS vector) AS distance
                FROM {table_name}
                WHERE {session_column} = :session_id
                AND embedding IS NOT NULL
                ORDER BY distance
                LIMIT :limit
            """),
            {
                "query_embedding": query_embedding,
                "session_id": session_id,
                "limit": limit
            }
        ).fetchall()
        
        # Convert results to list of dicts
        messages = [
            {
                "id": r.id,
                "content": r.summary if r.summary else r.raw_text,
                "timestamp": r.timestamp,
                "is_summary": r.is_summary,
                "similarity": 1 - r.distance
            }
            for r in results
        ]
        
        print(f"[Semantic Search] Found {len(messages)} similar messages")
        return messages
        
    except Exception as e:
        print(f"[Semantic Search Error] {e}")
        return []  # Graceful degradation


def get_relevant_context(
    db: Session,
    query: str,
    session_id: str,
    limit: int = 3,
    max_chars_per_message: int = 200
) -> str:
    """
    Get relevant context from conversation history for RAG.
    
    This is the main function to use for reducing token usage.
    Instead of loading full conversation history, retrieves only
    the most semantically relevant messages.
    
    Args:
        db: Database session
        query: Current user query
        session_id: Chat session ID
        limit: Number of relevant messages to retrieve
        max_chars_per_message: Max characters to include per message
        
    Returns:
        Formatted context string ready for inclusion in prompt
    """
    similar_messages = search_similar_messages(db, query, session_id, limit)
    
    if not similar_messages:
        return ""
    
    # Format messages for context
    # Use is_summary flag since 'sender' field doesn't exist in search results
    context_lines = [
        f"[{'Summary' if msg['is_summary'] else 'Message'}]: {msg['content'][:max_chars_per_message]}"
        for msg in similar_messages
    ]
    
    context = "\n".join(context_lines)
    print(f"[RAG Context] Retrieved {len(similar_messages)} relevant messages")
    return context


def get_relevant_context_with_metadata(
    db: Session,
    query: str,
    session_id: str,
    limit: int = 3,
    similarity_threshold: float = 0.7
) -> Dict[str, Any]:
    """
    Get relevant context with metadata for advanced use cases.
    
    Args:
        db: Database session
        query: Current user query
        session_id: Chat session ID
        limit: Number of relevant messages to retrieve
        similarity_threshold: Minimum similarity score to include (0-1)
        
    Returns:
        Dictionary with:
        - context: Formatted context string
        - messages: List of message dicts with full metadata
        - count: Number of messages retrieved
        - avg_similarity: Average similarity score
    """
    similar_messages = search_similar_messages(db, query, session_id, limit)
    
    # Filter by similarity threshold
    filtered = [m for m in similar_messages if m['similarity'] >= similarity_threshold]
    
    if not filtered:
        return {
            "context": "",
            "messages": [],
            "count": 0,
            "avg_similarity": 0.0
        }
    
    # Calculate metrics
    avg_similarity = sum(m['similarity'] for m in filtered) / len(filtered)
    
    # Format context
    context_lines = [
        f"[{msg['sender']}]: {msg['content'][:200]}"
        for msg in filtered
    ]
    
    return {
        "context": "\n".join(context_lines),
        "messages": filtered,
        "count": len(filtered),
        "avg_similarity": round(avg_similarity, 3)
    }


def check_pgvector_available(db: Session) -> bool:
    """
    Check if pgvector extension is available and enabled.
    
    Args:
        db: Database session
        
    Returns:
        True if pgvector is available, False otherwise
    """
    try:
        result = db.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ).scalar()
        return bool(result)
    except Exception:
        # Likely SQLite or pgvector not installed
        return False
