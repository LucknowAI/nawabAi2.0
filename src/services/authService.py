from typing import Optional
from datetime import datetime, timedelta, timezone
import jwt
import logging
from passlib.context import CryptContext
from src.config.settings import Settings
from src.models.userModels import User
from src.models.authModels import TokenData
import secrets

logger = logging.getLogger("AuthService")


class AuthService:

    def __init__(self):
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        self.settings = Settings()

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:

        try: 
            return self.pwd_context.verify(plain_password, hashed_password)
        except Exception as e:
            logger.error(f"Error verifying password: {e}")

        return False

    def get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """
        Get a user by username
        """
        try:
            return await User.find_one(User.username == username)
        except Exception as e:
            logger.error(f"Error getting user by {username}: {e}")
            return None

    async def authenticate_user(self, username: str, password: str ) -> Optional[dict]:
        """
        Authenticate a user by username and password
        """
        user = await self.get_user_by_username(username)
        if not user or not self.verify_password(password, user.hashed_password):
            return None
        user.last_login = datetime.now(timezone.utc)
        await user.save()

        return user.model_dump(exclude = {"hashed_password"})

    def create_tokens(self, user_data: dict) -> tuple[str, str]:

        now = datetime.now(timezone.utc)

        access_payload = {
            "user_id": str(user_data["id"]),
            "email": user_data["email"],
            "username": user_data["username"],
            "exp": now + timedelta(minutes=self.settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            "iat": now,
            "token_type": "access",
            "jti": secrets.token_urlsafe(32)  # JWT ID for token blacklisting
        }
        
        refresh_payload = {
            "user_id": str(user_data["id"]),
            "exp": now + timedelta(days=self.settings.REFRESH_TOKEN_EXPIRE_DAYS),
            "iat": now,
            "token_type": "refresh",
            "jti": secrets.token_urlsafe(32)
        } 

        access_token = jwt.encode(access_payload, self.settings.JWT_SECRET, algorithm=self.settings.JWT_ALGORITHM)
        refresh_token = jwt.encode(refresh_payload, self.settings.JWT_SECRET, algorithm=self.settings.JWT_ALGORITHM)
        
        return access_token, refresh_token




