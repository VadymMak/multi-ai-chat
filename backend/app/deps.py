"""Dependencies for FastAPI endpoints"""
from typing import Generator
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from app.memory.db import SessionLocal
from app.memory.models import User
from app.utils.security import verify_token

# Setup logging
logger = logging.getLogger(__name__)

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency – открыть сессию и закрыть после запроса."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# OAuth2 scheme for JWT token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Get current authenticated user from JWT token.
    Validates token and checks user status.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # DEBUG: Log token
    logger.info(f"🔍 Token received: {token[:30]}...")
    
    # Verify token
    payload = verify_token(token)
    logger.info(f"🔍 Payload: {payload}")
    
    if payload is None:
        logger.error("❌ Payload is None - token verification failed")
        raise credentials_exception
    
    # Get user_id from payload (might be int or str)
    user_id = payload.get("sub")
    logger.info(f"🔍 user_id from payload: {user_id} (type: {type(user_id).__name__})")
    
    if user_id is None:
        logger.error("❌ user_id is None in payload")
        raise credentials_exception
    
    # Convert to int if needed
    try:
        user_id = int(user_id)
        logger.info(f"✅ user_id converted to int: {user_id}")
    except (ValueError, TypeError) as e:
        logger.error(f"❌ Failed to convert user_id to int: {e}")
        raise credentials_exception
    
    # Get user from database
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        logger.error(f"❌ User not found with id: {user_id}")
        raise credentials_exception
    
    logger.info(f"✅ User authenticated: {user.username} (id={user.id})")
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """
    Get current active user and check status.
    Blocks suspended/inactive users.
    Superusers bypass all checks.
    """
    # Superuser always has access
    if current_user.is_superuser:
        return current_user
    
    # Check if user is active
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive. Please contact support."
        )
    
    # Check trial expiration
    if current_user.status == "trial":
        if current_user.trial_ends_at and current_user.trial_ends_at < datetime.utcnow():
            current_user.status = "suspended"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trial period expired. Please subscribe to continue."
            )
    
    # Check subscription expiration
    if current_user.status == "active":
        if current_user.subscription_ends_at and current_user.subscription_ends_at < datetime.utcnow():
            current_user.status = "suspended"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Subscription expired. Please renew to continue."
            )
    
    # Check if suspended
    if current_user.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended. Please subscribe or contact support."
        )
    
    return current_user

async def get_superuser(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Require superuser privileges"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required"
        )
    return current_user