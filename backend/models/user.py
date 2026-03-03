"""
User models for AI Desktop Copilot.
Handles authentication, authorization, and user management.
"""

from datetime import datetime, timezone
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field, EmailStr


# ==================== Enums ====================

class UserRole(str, Enum):
    """User role types."""
    ADMIN = "admin"
    USER = "user"


class UserStatus(str, Enum):
    """User account status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


# ==================== Core User Model ====================

class User(BaseModel):
    """Main user model."""
    id: Optional[str] = Field(None, description="User ID")
    name: str = Field(..., min_length=1, max_length=100, description="Full name")
    email: EmailStr = Field(..., description="User email address")

    role: UserRole = Field(default=UserRole.USER)
    status: UserStatus = Field(default=UserStatus.ACTIVE)

    is_verified: bool = Field(default=False)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_login_at: Optional[datetime] = None

    def touch(self):
        """Update updated_at timestamp."""
        self.updated_at = datetime.now(timezone.utc)


# ==================== Authentication Models ====================

class UserCreate(BaseModel):
    """User registration request."""
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class UserLogin(BaseModel):
    """User login request."""
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class UserResponse(BaseModel):
    """Safe user response (no password)."""
    id: str
    name: str
    email: EmailStr
    role: UserRole
    status: UserStatus
    is_verified: bool
    created_at: datetime
    last_login_at: Optional[datetime]


# ==================== Token Models ====================

class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    """Decoded JWT payload."""
    user_id: str
    email: EmailStr
    role: UserRole
    exp: int