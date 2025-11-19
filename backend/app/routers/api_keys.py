"""User API keys management"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.memory.db import get_db
from app.memory.models import User, UserAPIKey
from app.deps import get_current_active_user
from app.utils.security import encrypt_api_key, decrypt_api_key, mask_api_key

router = APIRouter(prefix="/settings", tags=["api-keys"])

# === Schemas ===

class APIKeysUpdate(BaseModel):
    openai_key: Optional[str] = None
    anthropic_key: Optional[str] = None
    youtube_key: Optional[str] = None
    google_search_key: Optional[str] = None

class APIKeysResponse(BaseModel):
    openai_key: Optional[str]
    anthropic_key: Optional[str]
    youtube_key: Optional[str]
    google_search_key: Optional[str]
    has_openai: bool
    has_anthropic: bool
    has_youtube: bool
    has_google_search: bool

# === Endpoints ===

@router.post("/api-keys", response_model=APIKeysResponse)
async def save_api_keys(
    keys: APIKeysUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Save user's API keys (encrypted).
    Only saves provided keys, doesn't delete existing ones unless explicitly set to empty string.
    """
    # Get or create UserAPIKey record
    user_keys = db.query(UserAPIKey).filter(UserAPIKey.user_id == current_user.id).first()
    
    if not user_keys:
        user_keys = UserAPIKey(user_id=current_user.id)
        db.add(user_keys)
    
    # Update keys (encrypt non-empty values)
    if keys.openai_key is not None:
        user_keys.openai_key_encrypted = encrypt_api_key(keys.openai_key) if keys.openai_key else None
    
    if keys.anthropic_key is not None:
        user_keys.anthropic_key_encrypted = encrypt_api_key(keys.anthropic_key) if keys.anthropic_key else None
    
    if keys.youtube_key is not None:
        user_keys.youtube_key_encrypted = encrypt_api_key(keys.youtube_key) if keys.youtube_key else None
    
    if keys.google_search_key is not None:
        user_keys.google_search_key_encrypted = encrypt_api_key(keys.google_search_key) if keys.google_search_key else None
    
    db.commit()
    db.refresh(user_keys)
    
    # Return masked keys
    return get_api_keys_response(user_keys)

@router.get("/api-keys", response_model=APIKeysResponse)
async def get_api_keys(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get user's API keys (masked for security)"""
    user_keys = db.query(UserAPIKey).filter(UserAPIKey.user_id == current_user.id).first()
    
    if not user_keys:
        return APIKeysResponse(
            openai_key=None,
            anthropic_key=None,
            youtube_key=None,
            google_search_key=None,
            has_openai=False,
            has_anthropic=False,
            has_youtube=False,
            has_google_search=False
        )
    
    return get_api_keys_response(user_keys)

@router.delete("/api-keys")
async def delete_api_keys(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete all user's API keys"""
    user_keys = db.query(UserAPIKey).filter(UserAPIKey.user_id == current_user.id).first()
    
    if user_keys:
        db.delete(user_keys)
        db.commit()
    
    return {"message": "API keys deleted successfully"}

# === Helper Functions ===

def get_api_keys_response(user_keys: UserAPIKey) -> APIKeysResponse:
    """Build API keys response with masked values"""
    openai_decrypted = decrypt_api_key(user_keys.openai_key_encrypted or "")
    anthropic_decrypted = decrypt_api_key(user_keys.anthropic_key_encrypted or "")
    youtube_decrypted = decrypt_api_key(user_keys.youtube_key_encrypted or "")
    google_decrypted = decrypt_api_key(user_keys.google_search_key_encrypted or "")
    
    return APIKeysResponse(
        openai_key=mask_api_key(openai_decrypted) if openai_decrypted else None,
        anthropic_key=mask_api_key(anthropic_decrypted) if anthropic_decrypted else None,
        youtube_key=mask_api_key(youtube_decrypted) if youtube_decrypted else None,
        google_search_key=mask_api_key(google_decrypted) if google_decrypted else None,
        has_openai=bool(openai_decrypted),
        has_anthropic=bool(anthropic_decrypted),
        has_youtube=bool(youtube_decrypted),
        has_google_search=bool(google_decrypted)
    )

# === Helper to get decrypted keys for providers ===

def get_user_api_key(user: User, provider: str, db: Session) -> Optional[str]:
    """
    Get user's decrypted API key for a provider.
    Falls back to env vars for superusers.
    
    Args:
        user: Current user
        provider: "openai", "anthropic", "youtube", "google_search"
        db: Database session
    
    Returns:
        Decrypted API key or None
    """
    from app.config.settings import settings
    
    # Try user's own keys first
    user_keys = db.query(UserAPIKey).filter(UserAPIKey.user_id == user.id).first()
    
    if user_keys:
        if provider == "openai" and user_keys.openai_key_encrypted:
            return decrypt_api_key(user_keys.openai_key_encrypted)
        elif provider == "anthropic" and user_keys.anthropic_key_encrypted:
            return decrypt_api_key(user_keys.anthropic_key_encrypted)
        elif provider == "youtube" and user_keys.youtube_key_encrypted:
            return decrypt_api_key(user_keys.youtube_key_encrypted)
        elif provider == "google_search" and user_keys.google_search_key_encrypted:
            return decrypt_api_key(user_keys.google_search_key_encrypted)
    
    # Fallback to .env for superusers only
    if user.is_superuser:
        if provider == "openai":
            return settings.OPENAI_API_KEY
        elif provider == "anthropic":
            return settings.ANTHROPIC_API_KEY
        elif provider == "youtube":
            return settings.YOUTUBE_API_KEY
    
    return None
