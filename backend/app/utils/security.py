"""Security utilities for password validation and encryption"""
from cryptography.fernet import Fernet
from passlib.hash import bcrypt
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from typing import Optional
import logging
import os
import re
import time

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
    
    # FIX: Use UNIX timestamp for expiration (more reliable)
    now_timestamp = int(time.time())
    expire_seconds = settings.JWT_EXPIRATION_HOURS * 3600
    expire_timestamp = now_timestamp + expire_seconds
    
    to_encode.update({"exp": expire_timestamp})
    
    try:
        encoded_jwt = jwt.encode(
            to_encode, 
            settings.JWT_SECRET_KEY, 
            algorithm=settings.JWT_ALGORITHM
        )
        
        # Debug logging
        expire_datetime = datetime.fromtimestamp(expire_timestamp)
        logger.info(f"✅ Token created for sub={to_encode.get('sub')}, expires in {settings.JWT_EXPIRATION_HOURS}h")
        logger.debug(f"   Current time: {datetime.fromtimestamp(now_timestamp).isoformat()}")
        logger.debug(f"   Expires at:   {expire_datetime.isoformat()}")
        logger.debug(f"   Expire timestamp: {expire_timestamp}")
        
        return encoded_jwt
    except Exception as e:
        logger.error(f"❌ Failed to create token: {e}")
        raise

def verify_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload"""
    try:
        # Log token info (first 30 chars only for security)
        logger.info(f"🔍 Verifying token: {token[:30]}...")
        
        # ✅ CRITICAL: Current time in UTC
        now_timestamp = int(time.time())
        now_datetime = datetime.utcnow()
        logger.info(f"⏰ Server current time (UTC): {now_datetime.isoformat()}")
        logger.info(f"⏰ Server current timestamp: {now_timestamp}")
        
        # Decode JWT token
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        logger.info(f"🔍 Payload decoded: {payload}")
        
        # Check expiration manually
        exp_timestamp = payload.get("exp")
        if exp_timestamp:
            exp_datetime = datetime.utcfromtimestamp(exp_timestamp)
            time_left_seconds = exp_timestamp - now_timestamp
            time_left_hours = time_left_seconds / 3600
            
            logger.info(f"⏰ Token expires at (UTC): {exp_datetime.isoformat()}")
            logger.info(f"⏰ Token exp timestamp: {exp_timestamp}")
            logger.info(f"⏰ Time left: {time_left_seconds}s ({time_left_hours:.2f}h)")
            
            if exp_timestamp < now_timestamp:
                logger.warning(f"⚠️ Token expired! exp={exp_timestamp} < now={now_timestamp}")
                logger.warning(f"⚠️ Token was valid until: {exp_datetime.isoformat()}")
                return None
            else:
                logger.info(f"✅ Token is valid for {time_left_hours:.2f} more hours")
        
        logger.info(f"✅ Token verified successfully")
        return payload
        
    except jwt.ExpiredSignatureError:
        logger.warning("⚠️ Token expired (JWT library check)")
        return None
    except jwt.JWTError as e:
        logger.error(f"❌ JWT verification failed: {type(e).__name__}: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected error verifying token: {type(e).__name__}: {str(e)}")
        return None