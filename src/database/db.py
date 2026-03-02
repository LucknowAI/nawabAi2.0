"""
Async SQLAlchemy engine and session factory.

Usage (inside a route or service)
----------------------------------
    async with get_db() as db:
        result = await db.execute(select(UserModel).where(...))
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config.settings import settings


def _build_asyncpg_url(raw_url: str):
    """
    asyncpg does not accept the 'sslmode' query parameter that psycopg2 uses.
    Strip it from the URL and return (cleaned_url, connect_args) so the caller
    can pass ssl settings via connect_args instead.
    """
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    ssl_value = None
    if "sslmode" in params:
        sslmode = params.pop("sslmode")[0]
        # Map psycopg2 sslmode values to asyncpg ssl argument
        if sslmode in ("require", "verify-ca", "verify-full"):
            ssl_value = True
        elif sslmode == "disable":
            ssl_value = False
        # prefer / allow → let asyncpg decide (no explicit ssl arg)

    new_query = urlencode(params, doseq=True)
    cleaned = urlunparse(parsed._replace(query=new_query))

    connect_args = {}
    if ssl_value is not None:
        connect_args["ssl"] = ssl_value

    return cleaned, connect_args


_db_url, _connect_args = _build_asyncpg_url(settings.POSTGRES_DB_URL)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
engine = create_async_engine(
    _db_url,
    echo=False,          # set True for SQL query logging in development
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args=_connect_args,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Dependency / context-manager helper
# ---------------------------------------------------------------------------
@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession and commit/rollback automatically."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
