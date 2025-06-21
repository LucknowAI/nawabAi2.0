from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from beanie import Document
from datetime import datetime
from enum import Enum
import uuid

class UserStatus(str, Enum):
    ACTIVE               = 'active'
    INACTIVE             = 'inactive'
    SUSPENDED            = 'suspended'
    PENDING_VERIFICATION = 'pending_verification'

class AuthProvider(str, Enum):
    LOCAL                = 'local'
    GOOGLE               = 'google'



#Base User Model (for API responses)
class User(Document):
    id                   : str = Field(default_factory=lambda: str(uuid.uuid4()))
    username             : str
    email                : str | None               = None
    full_name            : str | None               = None
    status               : UserStatus               = UserStatus.PENDING_VERIFICATION
    email_verified       : bool                     = False
    auth_provider        : AuthProvider             = AuthProvider.LOCAL
    created_at           : Optional[datetime]       = None
    updated_at           : Optional[datetime]       = None
    last_login           : Optional[datetime]       = None
    hashed_password      : Optional[str]            = None
    failed_login_attempts: int = 0
    account_locked_until : Optional[datetime]       = None

# User model with sensitive data (for database storage)


class UserCreate(BaseModel):
    username             : str
    email                : str
    password             : str
    full_name            : Optional[str]            = None

class UserUpdate(BaseModel):
    username             : Optional[str]            = None
    email                : Optional[EmailStr]       = None
    full_name            : Optional[str]            = None
    status               : Optional[UserStatus]     = None


# User profile response (public information)
class UserProfile(BaseModel):
    id                   : str
    username             : str
    email                : EmailStr
    full_name            : Optional[str]            = None
    email_verified       : bool
    auth_provider        : AuthProvider
    created_at           : datetime
    last_login           : Optional[datetime]       = None


# Password change model
class PasswordChange(BaseModel):
    current_password     : str
    new_password         : str


# Google OAuth user data
class GoogleUserInfo(BaseModel):
    google_id            : str
    email                : EmailStr
    name                 : str
    picture              : Optional[str]            = None
    email_verified       : bool                     = True




