from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from google.oauth2 import id_token
from google.auth.transport import requests as g_requests
from pydantic import BaseModel
from sqlalchemy import select

from src.auth.jwt_utils import create_access_token, get_current_user
from src.cities.registry import CITY_REGISTRY
from src.config.settings import settings
from src.database.db import get_db
from sqlalchemy_models.user import UserModel

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class GoogleLoginRequest(BaseModel):
    """Payload sent by the frontend after completing Google Sign-In."""
    id_token: str


class GoogleUserInfo(BaseModel):
    """Fields extracted from Google's verified ID-token payload."""
    google_id     : str
    email         : str
    email_verified: bool
    full_name     : str | None = None
    given_name    : str | None = None
    family_name   : str | None = None
    picture       : str | None = None


class AuthResponse(BaseModel):
    access_token    : str
    token_type      : str = "bearer"
    user_id         : int
    email           : str
    full_name       : str | None
    picture         : str | None
    default_city_id : str = "lucknow"


class ProfileUpdateRequest(BaseModel):
    default_city_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_google_token(raw_token: str) -> GoogleUserInfo:
    """Verify the Google ID-token and return normalised user info."""
    try:
        payload = id_token.verify_oauth2_token(
            raw_token,
            g_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Google token: {exc}")

    return GoogleUserInfo(
        google_id      = payload["sub"],
        email          = payload["email"],
        email_verified = payload.get("email_verified", False),
        full_name      = payload.get("name"),
        given_name     = payload.get("given_name"),
        family_name    = payload.get("family_name"),
        picture        = payload.get("picture"),
    )


async def _get_or_create_user(info: GoogleUserInfo) -> UserModel:
    """
    Look up the user by google_id; create a new row if not found.
    Updates mutable profile fields and last_login on every login.
    """
    async with get_db() as db:
        # 1. Try to fetch existing user
        result = await db.execute(
            select(UserModel).where(UserModel.google_id == info.google_id)
        )
        user: UserModel | None = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if user is None:
            # 2. First-ever login – create the row
            user = UserModel(
                google_id      = info.google_id,
                email          = info.email,
                email_verified = info.email_verified,
                full_name      = info.full_name,
                given_name     = info.given_name,
                family_name    = info.family_name,
                picture        = info.picture,
                auth_provider  = "google",
                last_login     = now,
            )
            db.add(user)
        else:
            # 3. Returning user – refresh mutable fields
            user.email          = info.email
            user.email_verified = info.email_verified
            user.full_name      = info.full_name
            user.given_name     = info.given_name
            user.family_name    = info.family_name
            user.picture        = info.picture
            user.last_login     = now

        await db.flush()   # populate auto-generated id before commit
        await db.refresh(user)
        return user


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/google", response_model=AuthResponse)
async def google_login(body: GoogleLoginRequest, response: Response):
    """
    Exchange a Google ID-token for an application JWT.

    Flow
    ----
    1. Verify the Google ID-token with Google's public keys.
    2. Get-or-create the user row in PostgreSQL.
    3. Issue a signed JWT and set it as an HttpOnly cookie.
    """
    # 1. Verify Google token
    google_info = _parse_google_token(body.id_token)

    # 2. Upsert user in DB
    user = await _get_or_create_user(google_info)

    # 3. Mint JWT
    access_token = create_access_token(
        {"sub": str(user.id), "email": user.email}
    )

    # 4. Set secure cookie
    # secure=True  → only sent over HTTPS (required on Cloud Run)
    # samesite='none' → required when frontend and backend are on different
    #   domains; browsers silently drop samesite='none' without secure=True.
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=7 * 24 * 60 * 60,  # 7 days, matches token expiry
    )

    return AuthResponse(
        access_token    = access_token,
        user_id         = user.id,
        email           = user.email,
        full_name       = user.full_name,
        picture         = user.picture,
        default_city_id = user.default_city_id or "lucknow",
    )


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@router.post("/logout")
async def logout(response: Response):
    """Clear the access_token cookie — effectively logs the user out."""
    response.delete_cookie(
        key="access_token",
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
        secure=settings.COOKIE_SECURE,
    )
    return {"message": "Logged out successfully"}


# ---------------------------------------------------------------------------
# Current user (protected)
# ---------------------------------------------------------------------------

@router.get("/me", response_model=AuthResponse)
async def me(current_user: dict = Depends(get_current_user)):
    """
    Return the profile of the currently logged-in user.

    Reads identity from the HttpOnly cookie (no body needed).
    """
    async with get_db() as db:
        result = await db.execute(
            select(UserModel).where(UserModel.id == int(current_user["sub"]))
        )
        user: UserModel | None = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    return AuthResponse(
        access_token    = "",   # not re-issued on /me
        user_id         = user.id,
        email           = user.email,
        full_name       = user.full_name,
        picture         = user.picture,
        default_city_id = user.default_city_id or "lucknow",
    )


# ---------------------------------------------------------------------------
# Profile update (city preference)
# ---------------------------------------------------------------------------

@router.patch("/profile")
async def update_profile(
    body: ProfileUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Update the authenticated user's profile settings.

    Currently supports updating ``default_city_id``.
    """
    if body.default_city_id not in CITY_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown city: {body.default_city_id!r}. Valid values: {list(CITY_REGISTRY)}",
        )

    async with get_db() as db:
        result = await db.execute(
            select(UserModel).where(UserModel.id == int(current_user["sub"]))
        )
        user: UserModel | None = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        user.default_city_id = body.default_city_id
        await db.flush()
        await db.refresh(user)

    return {"default_city_id": user.default_city_id}