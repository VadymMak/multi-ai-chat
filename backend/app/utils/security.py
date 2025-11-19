"""Security utilities for password validation and encryption"""
from cryptography.fernet import Fernet
from passlib.hash import bcrypt
from datetime import datetime, timedelta
from jose import JWTError, jwt, ExpiredSignatureError
from typing import Optional
import logging
import os
import re

from app.config.settings import settings

# Setup logging
logger = logging.getLogger(__name__)

# Initialize Fernet cipher for API key encryption
def get_cipher():
    """Get Fernet cipher instance"""
    key = settings.ENCRYPTION_KEY
    if not key:
        # Generate key if not set (DEV ONLY - should be in env for production)
        key = Fernet.generate_key().decode()
        logger.warning(f"⚠️ WARNING: No ENCRYPTION_KEY set. Generated: {key}")
        logger.warning("   Add this to your .env file!")
    
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        raise ValueError(f"Invalid ENCRYPTION_KEY: {e}")

cipher = get_cipher()

# === Password Validation ===

def validate_password(password: str) -> tuple[bool, Optional[str]]:
    """
    Validate password requirements:
    - Minimum 8 characters
    - At least 1 letter
    - At least 1 number
    
    Returns: (is_valid, error_message)
    """
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters"
    
    has_letter = any(c.isalpha() for c in password)
    has_number = any(c.isdigit() for c in password)
    
    if not has_letter:
        return False, "Password must contain at least one letter"
    if not has_number:
        return False, "Password must contain at least one number"
    
    return True, None

# === API Key Encryption ===

def encrypt_api_key(key: str) -> str:
    """Encrypt API key with Fernet"""
    if not key:
        return ""
    try:
        return cipher.encrypt(key.encode()).decode()
    except Exception as e:
        logger.error(f"❌ Failed to encrypt API key: {e}")
        return ""

def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt API key with Fernet"""
    if not encrypted_key:
        return ""
    try:
        return cipher.decrypt(encrypted_key.encode()).decode()
    except Exception as e:
        logger.error(f"❌ Failed to decrypt API key: {e}")
        return ""

def mask_api_key(key: str) -> str:
    """Mask API key for display (show first 7 and last 4 chars)"""
    if not key or len(key) < 12:
        return "sk-..." if key and key.startswith("sk-") else "***"
    return f"{key[:7]}...{key[-4:]}"

# === JWT Token Management ===

def create_access_token(data: dict) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    
    # CRITICAL FIX: JWT 'sub' claim must be a string
    if 'sub' in to_encode:
        to_encode['sub'] = str(to_encode['sub'])
    
    expire = datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    to_encode.update({"exp": expire})
    
    try:
        encoded_jwt = jwt.encode(
            to_encode, 
            settings.JWT_SECRET_KEY, 
            algorithm=settings.JWT_ALGORITHM
        )
        logger.info(f"✅ Token created for sub={to_encode.get('sub')}, expires in {settings.JWT_EXPIRATION_HOURS}h")
        return encoded_jwt
    except Exception as e:
        logger.error(f"❌ Failed to create token: {e}")
        raise

def verify_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload"""
    try:
        # Log token info (first 30 chars only for security)
        logger.info(f"🔍 Verifying token: {token[:30]}...")
        logger.debug(f"🔍 Using JWT_SECRET_KEY: {settings.JWT_SECRET_KEY[:20]}...")
        logger.debug(f"🔍 Using JWT_ALGORITHM: {settings.JWT_ALGORITHM}")
        
        # Decode JWT token
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        logger.info(f"✅ Token verified successfully")
        logger.debug(f"   Payload: {payload}")
        return payload
        
    except ExpiredSignatureError:
        logger.warning("⚠️ Token expired")
        return None
    except jwt.JWTError as e:
        logger.error(f"❌ JWT verification failed: {type(e).__name__}: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected error verifying token: {type(e).__name__}: {str(e)}")
        return None