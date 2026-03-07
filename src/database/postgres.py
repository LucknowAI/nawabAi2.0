"""
PostgreSQL Database Connection Module
======================================

WHY THIS MODULE IS NEEDED:
--------------------------
1. **Centralized Connection Management**: Single point for all database connections
   - Prevents connection leaks
   - Manages connection pool efficiently
   
2. **Async Support**: FastAPI is async, so we need async database operations
   - Non-blocking database queries
   - Better performance under high load
   
3. **Connection Pooling**: Reuses database connections
   - Reduces connection overhead
   - Limits max connections to prevent database overload
   
4. **Dependency Injection**: Provides clean way to inject database sessions
   - Easy testing with mock databases
   - Clean separation of concerns

WHAT IT SOLVES:
---------------
- No more connection management scattered across files
- Automatic cleanup of connections
- Consistent error handling for database operations
- Easy to switch database configurations
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging

from src.config.settings import settings

logger = logging.getLogger(__name__)

# ===========================================
# SQLAlchemy Base Class
# ===========================================
# All models will inherit from this Base class
# This enables SQLAlchemy to track all models and their relationships
Base = declarative_base()


# ===========================================
# Async Engine Configuration
# ===========================================
# The engine is the core interface to the database
# It maintains the connection pool and handles all low-level operations

engine = create_async_engine(
    settings.DATABASE_URL,
    
    # Pool Settings - WHY THESE MATTER:
    # ---------------------------------
    # pool_size: Number of connections to keep open
    # - Too few = requests queue up waiting for connections
    # - Too many = database gets overwhelmed
    pool_size=settings.DB_POOL_SIZE,
    
    # max_overflow: Extra connections allowed during high load
    # These are temporary and closed when not needed
    max_overflow=settings.DB_MAX_OVERFLOW,
    
    # pool_timeout: How long to wait for a connection
    # Prevents requests hanging forever
    pool_timeout=settings.DB_POOL_TIMEOUT,
    
    # pool_recycle: Recreate connections after this many seconds
    # Prevents stale connections from causing issues
    pool_recycle=3600,  # 1 hour
    
    # echo: Log all SQL statements (useful for debugging)
    echo=settings.DEBUG,
    
    # future: Use SQLAlchemy 2.0 style
    future=True,
)


# ===========================================
# Async Session Factory
# ===========================================
# Sessions are the "workspace" for database operations
# Each request should get its own session

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    
    # expire_on_commit=False: Objects remain usable after commit
    # This is important for returning data after creating/updating records
    expire_on_commit=False,
    
    # autoflush=False: Don't automatically sync changes to DB
    # This gives us more control over when changes are persisted
    autoflush=False,
    
    # autocommit=False: Require explicit commits
    # Ensures we don't accidentally save incomplete data
    autocommit=False,
)


class DatabaseManager:
    """
    Database Manager Class
    ----------------------
    Handles database lifecycle and provides utility methods.
    
    WHY A CLASS INSTEAD OF FUNCTIONS?
    - Maintains state (connection status)
    - Can be extended for multiple databases
    - Easier to mock for testing
    """
    
    def __init__(self):
        self._connected = False
    
    async def connect(self) -> None:
        """
        Initialize database connection and create tables.
        
        Called during application startup.
        """
        try:
            # Test the connection
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            
            self._connected = True
            logger.info("✅ Successfully connected to PostgreSQL database")
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to PostgreSQL: {str(e)}")
            raise
    
    async def disconnect(self) -> None:
        """
        Close all database connections gracefully.
        
        Called during application shutdown.
        """
        try:
            await engine.dispose()
            self._connected = False
            logger.info("🔌 Disconnected from PostgreSQL database")
        except Exception as e:
            logger.error(f"Error disconnecting from database: {str(e)}")
    
    async def create_tables(self) -> None:
        """
        Create all tables defined in the models.
        
        Uses Base.metadata to discover all models that inherit from Base.
        
        NOTE: In production, use Alembic migrations instead!
        This is for development convenience only.
        """
        try:
            async with engine.begin() as conn:
                # Import all models to ensure they're registered with Base
                # This import must happen here to avoid circular imports
                from src.models import sqlalchemy_models  # noqa
                
                await conn.run_sync(Base.metadata.create_all)
            logger.info("📦 Database tables created/verified")
        except Exception as e:
            logger.error(f"Error creating tables: {str(e)}")
            raise
    
    async def health_check(self) -> dict:
        """
        Check database health and connection status.
        
        Returns:
            dict: Health status with connection info
        """
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(text("SELECT 1"))
                result.fetchone()
                
            return {
                "status": "healthy",
                "connected": True,
                "database": settings.POSTGRES_DB,
                "host": settings.POSTGRES_HOST
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e)
            }
    
    @property
    def is_connected(self) -> bool:
        return self._connected


# Global database manager instance
db_manager = DatabaseManager()


# ===========================================
# Dependency Injection for FastAPI
# ===========================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI Dependency for Database Sessions
    -----------------------------------------
    
    HOW TO USE:
    ```python
    @router.get("/users")
    async def get_users(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(User))
        return result.scalars().all()
    ```
    
    WHY THIS PATTERN?
    - Each request gets its own session (isolation)
    - Session is automatically closed after request
    - Errors trigger automatic rollback
    - No manual cleanup needed
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # If we reach here without exception, commit any pending changes
            await session.commit()
        except Exception:
            # If any error occurs, rollback all changes
            await session.rollback()
            raise
        finally:
            # Always close the session
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context Manager for Database Sessions (non-FastAPI use)
    --------------------------------------------------------
    
    Use this when you need a database session outside of a request,
    like in background tasks or CLI scripts.
    
    HOW TO USE:
    ```python
    async with get_db_context() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()
    ```
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

