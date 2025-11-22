"""Authentication endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, timedelta
from typing import Optional

from app.memory.db import get_db
from app.memory.models import User
from app.deps import get_current_user, get_current_active_user
from app.utils.security import validate_password, create_access_token
from app.config.settings import settings

router = APIRouter(prefix="/auth", tags=["authentication"])

# === Schemas ===

class UserRegister(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8)

class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    status: str
    is_superuser: bool
    trial_ends_at: Optional[datetime]
    subscription_ends_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)

class TrialStatusResponse(BaseModel):
    status: str
    trial_ends_at: Optional[datetime]
    days_remaining: Optional[int]
    subscription_ends_at: Optional[datetime]

# === Endpoints ===

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Register new user with 14-day trial.
    Password requirements: min 8 chars, at least 1 letter and 1 number.
    """
    # Validate password
    is_valid, error_msg = validate_password(user_data.password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    # Check if email already exists
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Check if username already exists
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    
    # Create user with trial period
    trial_ends = datetime.utcnow() + timedelta(days=settings.TRIAL_DAYS)
    
    user = User(
        email=user_data.email,
        username=user_data.username,
        password_hash=User.hash_password(user_data.password),
        status="trial",
        trial_ends_at=trial_ends,
        is_superuser=False,
        is_active=True
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Create access token
    access_token = create_access_token(data={"sub": user.id})
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.from_orm(user)
    )

@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Login with username/email and password.
    Returns JWT access token.
    """
    # Find user by username or email
    user = db.query(User).filter(
        (User.username == form_data.username) | (User.email == form_data.username)
    ).first()
    
    if not user or not user.verify_password(form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive"
        )
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    
    # Create access token
    access_token = create_access_token(data={"sub": user.id})
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.from_orm(user)
    )

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return UserResponse.from_orm(current_user)

@router.get("/trial-status", response_model=TrialStatusResponse)
async def get_trial_status(current_user: User = Depends(get_current_active_user)):
    """Get trial/subscription status"""
    days_remaining = None
    
    if current_user.status == "trial" and current_user.trial_ends_at:
        delta = current_user.trial_ends_at - datetime.utcnow()
        days_remaining = max(0, delta.days)
    
    return TrialStatusResponse(
        status=current_user.status,
        trial_ends_at=current_user.trial_ends_at,
        days_remaining=days_remaining,
        subscription_ends_at=current_user.subscription_ends_at
    )

@router.post("/change-password")
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Change user password"""
    # Verify current password
    if not current_user.verify_password(password_data.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    
    # Validate new password
    is_valid, error_msg = validate_password(password_data.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    # Update password
    current_user.password_hash = User.hash_password(password_data.new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}

@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """
    Logout endpoint (token invalidation handled client-side).
    Server just confirms receipt.
    """
    return {"message": "Logged out successfully"}
