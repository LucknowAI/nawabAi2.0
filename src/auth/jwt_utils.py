from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError, jwt

from src.config.settings import settings


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=7)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT; raises 401 on any failure."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("sub") is None:
            raise ValueError("missing sub")
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    request: Request,
    access_token: str | None = Cookie(default=None),
) -> dict:
    """
    FastAPI dependency — resolves the JWT from either source, in order:

    1. ``access_token`` HttpOnly cookie  (browser / same-origin)
    2. ``Authorization: Bearer <token>`` header  (server-to-server, AG-UI via Next.js)

    Returns the full decoded payload dict (contains ``sub``, ``email``, etc.).
    Raises 401 if neither source yields a valid token.
    """
    token = access_token

    if token is None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):].strip()

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — no access_token cookie or Authorization header",
        )
    return _decode_token(token)


async def get_current_user_id(user: dict = Depends(get_current_user)) -> int:
    """
    FastAPI dependency — resolves the authenticated user's integer ID.

    Chains on top of ``get_current_user`` so the cookie validation is
    performed first, then ``sub`` is extracted and cast to ``int``.
    Raises 401 if the token is missing or invalid.

    Usage in a route:
        @router.post("/chat")
        async def chat(user_id: int = Depends(get_current_user_id)):
            ...
    """
    try:
        return int(user["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a valid user identifier",
        )


async def get_optional_user_id(
    request: Request,
    access_token: str | None = Cookie(default=None),
) -> int | None:
    """
    FastAPI dependency — resolves the user ID from either source, in order:

    1. ``access_token`` HttpOnly cookie  (set by the /auth/google login flow)
    2. ``Authorization: Bearer <token>`` header  (used by AG-UI / non-browser clients)

    Returns ``None`` if neither is present or the token is invalid.
    Never raises 401, so endpoints remain accessible to unauthenticated callers.
    """
    # 1. prefer the cookie
    token = access_token

    # 2. fall back to Authorization header
    if token is None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):].strip()

    if token is None:
        return None

    try:
        payload = _decode_token(token)
        return int(payload["sub"])
    except (HTTPException, KeyError, ValueError, TypeError):
        return None