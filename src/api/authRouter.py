from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
import secrets

import jwt
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Body
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from beanie.operators import Or

from src.services.authService import AuthService
from src.utils.validators import AuthValidator
from src.middleware.rate_limiter import rate_limit, rate_limiter
from src.models.authModels import Token, TokenData, UserRegistration, RefreshTokenInDB, UserLogin
from src.models.userModels import User, UserStatus, AuthProvider, PasswordChange
from src.config.settings import Settings
import uuid
import logging

logger = logging.getLogger("auth_router")

auth_service = AuthService()
validator = AuthValidator()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

auth_router = APIRouter(
    prefix = "/auth",
    tags = ["Auth"],
    responses = {404: {"description": "Not found"}},
)


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    """Get current user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decode the token
        payload = jwt.decode(token, Settings.JWT_SECRET, algorithms=[Settings.JWT_ALGORITHM])
        
        # Validate token type
        if payload.get("token_type") != "access":
            raise credentials_exception
            
        # Check token expiration
        exp = payload.get("exp")
        if not exp or datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        
        # Get user data from token
        user_id = payload.get("user_id")
        username = payload.get("username")
        
        if not user_id or not username:
            raise credentials_exception
            
        # Verify user still exists and is active
        user = await User.find_one(User.id == user_id)
        if not user or user.status != UserStatus.ACTIVE:
            raise credentials_exception
            
        return user.model_dump(exclude={"hashed_password"})
        
    except InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        raise credentials_exception
    except Exception as e:
        logger.error(f"Token validation error: {e}")
        raise credentials_exception


async def get_current_active_user(
    current_user: Annotated[dict, Depends(get_current_user)]
) -> dict:
    if current_user.get("status") != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


@auth_router.post("/login", response_model=dict)
@rate_limit(max_requests=5, window_seconds=300)
async def login_user(
    request: Request,
    user_login: UserLogin
) -> dict:
    """
    User login endpoint with rate limiting
    
    **Rate Limited**: 5 attempts per 5 minutes per IP
    
    - **username**: Username or email
    - **password**: User password
    
    Returns access and refresh tokens on successful authentication.
    """
    try: 
        username = validator.sanitize_string(user_login.username)

        logger.info(f"Login attempt for user: {username} from IP: {request.client.host}")

        user = await auth_service.authenticate_user(username, user_login.password)
        if not user:
            logger.warning(f"Invalid credentials for user: {username} from IP: {request.client.host}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        access_token, refresh_token = auth_service.create_tokens(user)

        refresh_token_record = RefreshTokenInDB(
            token_id = secrets.token_urlsafe(32),
            user_id = str(user["id"]),
            token = refresh_token, 
            expires_at = datetime.now(timezone.utc) + timedelta(days = Settings.REFRESH_TOKEN_EXPIRE_DAYS),
            created_at = datetime.now(timezone.utc),
            is_active = True
        )
        await refresh_token_record.save()

        logger.info(f"Login successful for user: {username} from IP: {request.client.host}")

        return {
            "message"         : "Login successful",
            "access_token"    : access_token,
            "refresh_token"   : refresh_token,
            "token_type"      : "Bearer",
            "expires_in"      : Settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user"            : {
                "id"            : str(user["id"]),
                "username"      : user["username"],
                "email"         : user["email"],
                "full_name"     : user.get("full_name")
            }
        }
    except HTTPException: 
        raise
    except Exception as e:
        logger.error(f"Login error for user: {username} from IP: {request.client.host}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@auth_router.post("/register", response_model=dict)
@rate_limit(max_requests=3, window_seconds = 600) 
async def register_user(request: Request, user_registration: UserRegistration) -> dict:
    """
    User registration endpoint with rate limiting
    
    **Rate Limited**: 3 registrations per 10 minutes per IP
    
    - **username**: Unique username
    - **email**: Valid email address  
    - **password**: Strong password meeting security requirements
    - **full_name**: User's full name
    
    Returns access and refresh tokens on successful registration.
    """
    try:
        username = validator.sanitize_string(user_registration.username)
        email = validator.sanitize_string(user_registration.email)
        full_name = validator.sanitize_string(user_registration.full_name)

        if not validator.validate_email(email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email format"
            )
        
        is_valid, error_message = validator.validate_password_length(user_registration.password)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message
            )
        
        logger.info(f"Registration attempt for user: {username}, email: {email} from IP: {request.client.host}")
        
        existing_user = await User.find_one(
            Or(
                User.email == email,
                User.username == username
            )
        )
        
        if existing_user:
            logger.warning(f"Registration failed - user already exists: {username}/{email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this username or email already exists"
            )
        
        hashed_password = auth_service.get_password_hash(user_registration.password)
        
        new_user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            status=UserStatus.ACTIVE,
            email_verified=False,
            auth_provider=AuthProvider.LOCAL,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            last_login=None
        )
        
        await new_user.save()
        
        user_data = new_user.model_dump(exclude={"hashed_password"})
        access_token, refresh_token = auth_service.create_tokens(user_data)
        
        refresh_token_record = RefreshTokenInDB(
            token_id=secrets.token_urlsafe(32),
            user_id=str(new_user.id),
            token=refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(days=Settings.REFRESH_TOKEN_EXPIRE_DAYS),
            created_at=datetime.now(timezone.utc),
            is_active=True
        )
        await refresh_token_record.save()
        
        logger.info(f"Successful registration for user: {username}")
        
        return {
            "message": "User registered successfully",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": Settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": {
                "id": str(new_user.id),
                "username": new_user.username,
                "email": new_user.email,
                "full_name": new_user.full_name
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@auth_router.post("/refresh", response_model=dict)
@rate_limit(max_requests=10, window_seconds=300)
async def refresh_access_token(
    request: Request,
    refresh_token: str = Body(..., embed=True)
) -> dict:
    """
    Refresh access token endpoint with rate limiting
    """
    try: 
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )
        
        try: 
            payload = jwt.decode(refresh_token, Settings.JWT_SECRET, algorithms=[Settings.JWT_ALGORITHM])
        except InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        
        if payload.get("token_type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        
        token_record = await RefreshTokenInDB.find_one(
            RefreshTokenInDB.token == refresh_token,
            RefreshTokenInDB.is_active == True
        )
        
        if not token_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh Token not found or inactive"
            )
        
        current_time = datetime.now(timezone.utc)
        expires_at = token_record.expires_at
        
        # If expires_at is timezone-naive, make it timezone-aware
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        
        if current_time > expires_at:
            token_record.is_active = False
            await token_record.save()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token expired"
            )

        user = await User.find_one(User.id == token_record.user_id)
        if not user or user.status != UserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive"
            )

        user_data = user.model_dump(exclude={"hashed_password"})
        new_access_token, _ = auth_service.create_tokens(user_data)

        return {
            "message": "Token refreshed successfully",
            "access_token": new_access_token,
            "token_type": "Bearer",
            "expires_in": Settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Refresh token error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )
        


@auth_router.post("/logout")
async def logout_user(
    request: Request,
    current_user: Annotated[dict, Depends(get_current_user)],
    refresh_token:str = Body(..., embed=True)
) -> dict:
    """
    Logout user endpoint
    """
    try: 
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )
        
        token_record = await RefreshTokenInDB.find_one(
            RefreshTokenInDB.user_id == str(current_user['id']),
            RefreshTokenInDB.token == refresh_token,
            RefreshTokenInDB.is_active == True
        )

        if token_record:
            token_record.is_active = False
            await token_record.save()

        logger.info(f"User {current_user['username']} logged out successfully")

        return {"message" : "Logged out successfully"}


    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )    

@auth_router.get("/me", response_model=dict)
async def get_user_profile(
    current_user: Annotated[dict, Depends(get_current_user)]
) -> dict:
    """
    Get current user endpoint
    """

    return {
        "user": {
            "id": str(current_user["id"]),
            "username": current_user["username"],
            "email": current_user["email"],
            "full_name": current_user.get("full_name"),
            "status": current_user["status"],
            "email_verified": current_user.get("email_verified", False),
            "auth_provider": current_user.get("auth_provider"),
            "created_at": current_user.get("created_at"),
            "last_login": current_user.get("last_login")
        }
    }


@auth_router.post("/change-password")
async def change_password(
    request: Request,
    current_user: Annotated[dict, Depends(get_current_active_user)],
    password_data: PasswordChange
) -> dict:
    """
    Change password endpoint
    
    Request body:
    {
        "current_password": "your_current_password",
        "new_password": "your_new_password"
    }
    """
    try: 
        user = await User.find_one(User.id == current_user['id'])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        if not auth_service.verify_password(password_data.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid current password"
            )

        is_valid, error_message = validator.validate_password_length(password_data.new_password)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message
            )

        user.hashed_password = auth_service.get_password_hash(password_data.new_password)
        user.updated_at = datetime.now(timezone.utc)
        await user.save()

        await RefreshTokenInDB.find(
            RefreshTokenInDB.user_id == str(user.id),   
        ).update({"$set": {"is_active": False}})

        logger.info(f"Password changed for user: {user.username}")

        return {"message": "Password changed successfully"}
        
    except HTTPException:
        raise 
    except Exception as e:
        logger.error(f"Password change error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@auth_router.get("/health")
async def auth_health_check():
    """Authentication service health check"""
    return {
        "status": "healthy",
        "service": "authentication",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }        

        
        














