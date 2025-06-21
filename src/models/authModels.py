from pydantic import BaseModel, EmailStr
from typing import Optional
from beanie import Document
from datetime import datetime


class Token(BaseModel):
    access_token   : str
    refresh_token  : str
    token_type     : str
    expires_in     : str
    

class TokenData(BaseModel):
    username       : str | None = None
    email          : Optional[str] = None
    token_type     : Optional[str] = None

class RefreshTokenRequest(BaseModel):
    refresh_token  : str 

class UserRegistration(BaseModel):
    username       : str
    email          : str
    password       : str
    full_name      : Optional[str] = None

class UserLogin(BaseModel):
    username       : str
    password       : str

class LogoutRequest(BaseModel):
    refresh_token  : str

# Password Reset Models
class ForgotPasswordRequest(BaseModel):
    email          : EmailStr

class VerifyOTPRequest(BaseModel):
    email          : EmailStr 
    otp            : str

class ResetPasswordRequest(BaseModel):
    email          : EmailStr
    otp            : str
    new_password    : str


# Response Models
class AuthResponse(BaseModel):
    message        : str
    success        : bool

class RegistrationResponse(AuthResponse):
    user_id        : Optional[str] = None
    tokens         : Optional[Token] = None

class LoginResponse(AuthResponse):
    user           : Optional[dict] = None
    tokens         : Optional[Token] = None

class OTPResponse(AuthResponse):
    expires_at     : Optional[datetime] = None



# Database Models for storing tokens and OTPs
class RefreshTokenInDB(Document):
    token_id       : str
    user_id        : str
    token          : str
    expires_at     : datetime
    created_at     : datetime
    is_active      : bool

class OTPinDB(Document):
    email          : EmailStr
    otp            : str
    purpose        : str      # "email_verification", "password_reset"
    expires_at     : datetime
    created_at     : datetime
    attempts       : int = 0
    max_attempts   : int = 5

