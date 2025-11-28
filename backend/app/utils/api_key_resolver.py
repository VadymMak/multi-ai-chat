"""
API Key Resolver - Central utility for getting user's API keys

This module provides a unified way to get API keys across the application.
It checks user's stored keys first, then falls back to .env for superusers.

Usage:
    from app.utils.api_key_resolver import get_api_key, require_api_key

    # Get key (returns None if not found)
    key = get_api_key(user, "openai", db)
    
    # Require key (raises HTTPException if not found)
    key = require_api_key(user, "openai", db)
"""

from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.memory.models import User, UserAPIKey
from app.utils.security import decrypt_api_key
from app.config.settings import settings

# Provider names mapping
PROVIDER_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic (Claude)",
    "youtube": "YouTube",
    "google_search": "Google Search",
}


def get_api_key(
    user: User,
    provider: str,
    db: Session,
    allow_env_fallback: bool = True
) -> Optional[str]:
    """
    Get user's API key for a provider.
    
    Priority:
    1. User's own stored key (encrypted in DB)
    2. Environment variable (only if user is superuser and allow_env_fallback=True)
    
    Args:
        user: Current authenticated user
        provider: "openai", "anthropic", "youtube", "google_search"
        db: Database session
        allow_env_fallback: If True, superusers can use .env keys as fallback
    
    Returns:
        Decrypted API key string, or None if not found
    """
    # 1. Try user's own stored key first
    user_keys = db.query(UserAPIKey).filter(UserAPIKey.user_id == user.id).first()
    
    if user_keys:
        encrypted_key = None
        
        if provider == "openai":
            encrypted_key = user_keys.openai_key_encrypted
        elif provider == "anthropic":
            encrypted_key = user_keys.anthropic_key_encrypted
        elif provider == "youtube":
            encrypted_key = user_keys.youtube_key_encrypted
        elif provider == "google_search":
            encrypted_key = user_keys.google_search_key_encrypted
        
        if encrypted_key:
            decrypted = decrypt_api_key(encrypted_key)
            if decrypted:
                return decrypted
    
    # 2. Fallback to .env for superusers only
    if allow_env_fallback and user.is_superuser:
        env_key = None
        
        if provider == "openai":
            env_key = settings.OPENAI_API_KEY
        elif provider == "anthropic":
            env_key = settings.ANTHROPIC_API_KEY
        elif provider == "youtube":
            env_key = settings.YOUTUBE_API_KEY
        elif provider == "google_search":
            env_key = getattr(settings, 'GOOGLE_API_KEY', None)
        
        if env_key:
            return env_key
    
    return None


def require_api_key(
    user: User,
    provider: str,
    db: Session,
    allow_env_fallback: bool = True
) -> str:
    """
    Get user's API key or raise HTTPException if not found.
    
    Args:
        user: Current authenticated user
        provider: "openai", "anthropic", "youtube", "google_search"
        db: Database session
        allow_env_fallback: If True, superusers can use .env keys as fallback
    
    Returns:
        Decrypted API key string
    
    Raises:
        HTTPException 403: If user doesn't have the required API key
    """
    key = get_api_key(user, provider, db, allow_env_fallback)
    
    if not key:
        provider_name = PROVIDER_NAMES.get(provider, provider)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Please add your {provider_name} API key in Settings to use this feature."
        )
    
    return key


def has_api_key(user: User, provider: str, db: Session) -> bool:
    """
    Check if user has an API key for a provider.
    
    Args:
        user: Current authenticated user
        provider: "openai", "anthropic", "youtube", "google_search"
        db: Database session
    
    Returns:
        True if user has the key (either stored or via .env for superuser)
    """
    return get_api_key(user, provider, db) is not None


def get_available_providers(user: User, db: Session) -> dict:
    """
    Get dict of available providers for user.
    
    Returns:
        {
            "openai": True/False,
            "anthropic": True/False,
            "youtube": True/False,
            "google_search": True/False
        }
    """
    return {
        "openai": has_api_key(user, "openai", db),
        "anthropic": has_api_key(user, "anthropic", db),
        "youtube": has_api_key(user, "youtube", db),
        "google_search": has_api_key(user, "google_search", db),
    }


# ============== Provider-specific helpers ==============

def get_openai_key(user: User, db: Session, required: bool = True) -> Optional[str]:
    """Get OpenAI API key for user"""
    if required:
        return require_api_key(user, "openai", db)
    return get_api_key(user, "openai", db)


def get_anthropic_key(user: User, db: Session, required: bool = True) -> Optional[str]:
    """Get Anthropic API key for user"""
    if required:
        return require_api_key(user, "anthropic", db)
    return get_api_key(user, "anthropic", db)


def get_youtube_key(user: User, db: Session, required: bool = True) -> Optional[str]:
    """Get YouTube API key for user"""
    if required:
        return require_api_key(user, "youtube", db)
    return get_api_key(user, "youtube", db)


def get_google_search_key(user: User, db: Session, required: bool = False) -> Optional[str]:
    """Get Google Search API key for user (optional by default)"""
    if required:
        return require_api_key(user, "google_search", db)
    return get_api_key(user, "google_search", db)