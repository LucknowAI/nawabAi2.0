"""
Redis Cache Manager
====================

WHY REDIS IS NEEDED:
--------------------
1. **Session Caching**: Active chat sessions are stored in Redis for fast access
   - Database queries are ~1-10ms, Redis is ~0.1ms
   - Each message in a conversation would require multiple DB queries without caching
   
2. **Context Management**: Store recent conversation context
   - LLM needs recent messages for context
   - Fetching from DB every time is expensive
   
3. **Rate Limiting**: Store request counts per IP
   - Must be fast to not add latency to every request
   - Needs atomic increment operations
   
4. **User Presence**: Track active users in real-time
   - WebSocket connections, typing indicators, etc.

WHAT IT SOLVES:
---------------
- Reduces database load by 80-90% for chat operations
- Enables real-time features without database polling
- Provides automatic session expiration (TTL)
- Graceful handling of Redis unavailability
"""

import redis.asyncio as redis
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from src.config.settings import settings

logger = logging.getLogger(__name__)


class RedisManager:
    """
    Redis Connection Manager
    ------------------------
    
    Handles all Redis operations for the application.
    Designed to gracefully handle Redis unavailability.
    
    KEY DESIGN DECISIONS:
    1. Single connection with pooling (handled by redis-py)
    2. JSON serialization for complex data
    3. Consistent key naming: {type}:{id} (e.g., session:uuid, context:user_id)
    4. All operations have error handling and logging
    """
    
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self._connected = False
        
    async def connect(self) -> None:
        """
        Establish Redis connection.
        
        WHY from_url:
        - Supports both local and cloud Redis (Redis Cloud, AWS ElastiCache)
        - Connection string can be easily configured via environment
        """
        try:
            self.redis_client = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,  # Return strings instead of bytes
                socket_keepalive=True,  # Keep connection alive
                health_check_interval=30,  # Check connection health every 30s
                retry_on_timeout=True,  # Auto-retry on timeout
            )
            
            # Test the connection
            await self.redis_client.ping()
            self._connected = True
            logger.info("✅ Successfully connected to Redis")
            
        except redis.ConnectionError as e:
            logger.warning(f"⚠️ Redis connection failed: {str(e)}. Chat sessions will use database only.")
            self._connected = False
        except Exception as e:
            logger.error(f"❌ Unexpected Redis error: {str(e)}")
            self._connected = False
    
    async def disconnect(self) -> None:
        """Close Redis connection gracefully."""
        if self.redis_client:
            await self.redis_client.close()
            self._connected = False
            logger.info("🔌 Disconnected from Redis")
    
    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        return self._connected
    
    async def ping(self) -> bool:
        """
        Check if Redis is responsive.
        
        Use this for health checks instead of relying on is_connected,
        as the connection may have dropped.
        """
        if not self.redis_client:
            return False
        try:
            await self.redis_client.ping()
            return True
        except Exception:
            self._connected = False
            return False
    
    # =========================================
    # SESSION MANAGEMENT
    # =========================================
    
    async def cache_session(self, session_id: str, user_id: str, data: Dict[str, Any] = None) -> bool:
        """
        Create or update a chat session in Redis.
        
        WHY CACHE SESSIONS:
        - Active sessions are accessed frequently (every message)
        - Storing in Redis reduces DB load
        - TTL ensures old sessions are auto-cleaned
        
        Args:
            session_id: Unique session identifier (UUID)
            user_id: User who owns this session
            data: Optional additional session data
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._connected:
            return False
            
        try:
            session_key = f"{settings.CACHE_PREFIX}session:{session_id}"
            now = datetime.now(timezone.utc).isoformat()
            
            session_data = {
                "session_id": session_id,
                "user_id": user_id,
                "messages": [],  # Recent messages for context
                "created_at": now,
                "last_activity": now,
                "title": None,
                "message_count": 0,
                "context_summary": None,
                **(data or {})
            }
            
            # Store session with TTL
            await self.redis_client.set(
                session_key, 
                json.dumps(session_data), 
                ex=settings.SESSION_TIMEOUT
            )
            
            # Add to user's session index (for listing user's sessions)
            user_sessions_key = f"{settings.CACHE_PREFIX}user_sessions:{user_id}"
            await self.redis_client.sadd(user_sessions_key, session_id)
            await self.redis_client.expire(user_sessions_key, settings.SESSION_TIMEOUT)
            
            logger.debug(f"Cached session {session_id} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error caching session {session_id}: {str(e)}")
            return False
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a chat session from Redis cache.
        
        Returns:
            dict: Session data if found, None otherwise
        """
        if not self._connected:
            return None
            
        try:
            session_key = f"{settings.CACHE_PREFIX}session:{session_id}"
            session_data = await self.redis_client.get(session_key)
            
            if session_data:
                return json.loads(session_data)
            return None
            
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in session {session_id}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving session {session_id}: {str(e)}")
            return None
    
    async def update_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update specific fields in a cached session.
        
        WHY PARTIAL UPDATES:
        - More efficient than replacing entire session
        - Reduces risk of race conditions
        - Preserves fields not being updated
        """
        if not self._connected:
            return False
            
        try:
            session_data = await self.get_session(session_id)
            if not session_data:
                logger.warning(f"Session {session_id} not found in cache for update")
                return False
            
            # Update fields
            session_data.update(updates)
            session_data["last_activity"] = datetime.now(timezone.utc).isoformat()
            
            session_key = f"{settings.CACHE_PREFIX}session:{session_id}"
            await self.redis_client.set(
                session_key, 
                json.dumps(session_data), 
                ex=settings.SESSION_TIMEOUT
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating session {session_id}: {str(e)}")
            return False
    
    async def add_message_to_cache(
        self, 
        session_id: str, 
        role: str, 
        content: str,
        metadata: Dict[str, Any] = None
    ) -> bool:
        """
        Add a message to the cached session.
        
        WHY CACHE MESSAGES:
        - Fast context retrieval for LLM calls
        - Avoid DB query for every message
        
        NOTE: This only caches recent messages (controlled by MAX_CONTEXT_MESSAGES).
        Full message history is always stored in PostgreSQL.
        """
        if not self._connected:
            return False
            
        try:
            session_data = await self.get_session(session_id)
            if not session_data:
                return False
            
            # Create message object
            message = {
                "role": role,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {}
            }
            
            # Add to messages list
            session_data["messages"].append(message)
            
            # Keep only recent messages (sliding window)
            max_messages = settings.MAX_CONTEXT_MESSAGES
            if len(session_data["messages"]) > max_messages:
                session_data["messages"] = session_data["messages"][-max_messages:]
            
            # Update counters
            session_data["message_count"] = session_data.get("message_count", 0) + 1
            
            # Auto-generate title from first user message
            if not session_data.get("title") and role == "user":
                session_data["title"] = self._generate_title(content)
            
            return await self.update_session(session_id, session_data)
            
        except Exception as e:
            logger.error(f"Error adding message to session {session_id}: {str(e)}")
            return False
    
    async def get_session_messages(
        self, 
        session_id: str, 
        limit: int = None
    ) -> List[Dict[str, Any]]:
        """
        Get cached messages for a session.
        
        These are the recent messages stored in Redis for fast context access.
        For full history, query PostgreSQL.
        
        Args:
            session_id: Session to get messages from
            limit: Optional limit on number of messages
            
        Returns:
            List of message dictionaries
        """
        if not self._connected:
            return []
            
        try:
            session_data = await self.get_session(session_id)
            if not session_data:
                return []
            
            messages = session_data.get("messages", [])
            
            if limit:
                return messages[-limit:]
            return messages
            
        except Exception as e:
            logger.error(f"Error getting messages for session {session_id}: {str(e)}")
            return []
    
    async def get_user_active_sessions(self, user_id: str) -> List[str]:
        """
        Get all active session IDs for a user.
        
        Returns:
            List of session IDs
        """
        if not self._connected:
            return []
            
        try:
            user_sessions_key = f"{settings.CACHE_PREFIX}user_sessions:{user_id}"
            sessions = await self.redis_client.smembers(user_sessions_key)
            return list(sessions) if sessions else []
            
        except Exception as e:
            logger.error(f"Error retrieving user sessions for {user_id}: {str(e)}")
            return []
    
    async def invalidate_session(self, session_id: str, user_id: str = None) -> bool:
        """
        Remove a session from cache.
        
        Called when:
        - Session is completed
        - User logs out
        - Session data needs to be refreshed from DB
        """
        if not self._connected:
            return False
            
        try:
            session_key = f"{settings.CACHE_PREFIX}session:{session_id}"
            await self.redis_client.delete(session_key)
            
            # Remove from user's session list if user_id provided
            if user_id:
                user_sessions_key = f"{settings.CACHE_PREFIX}user_sessions:{user_id}"
                await self.redis_client.srem(user_sessions_key, session_id)
            
            logger.debug(f"Invalidated session cache: {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error invalidating session {session_id}: {str(e)}")
            return False
    
    async def update_context_summary(self, session_id: str, summary: str) -> bool:
        """
        Update the context summary for a session.
        
        WHY CONTEXT SUMMARIES:
        - Long conversations exceed LLM context limits
        - Summaries compress old messages
        - Cached for fast retrieval
        """
        if not self._connected:
            return False
            
        return await self.update_session(session_id, {
            "context_summary": summary,
            "summary_updated_at": datetime.now(timezone.utc).isoformat()
        })
    
    # =========================================
    # RATE LIMITING
    # =========================================
    
    async def increment_rate_limit(
        self, 
        key: str, 
        window_seconds: int = 60
    ) -> int:
        """
        Increment rate limit counter for a key.
        
        Used for API rate limiting. Returns current count.
        
        Args:
            key: Unique identifier (e.g., IP address, user ID)
            window_seconds: Time window for rate limiting
            
        Returns:
            Current request count in the window
        """
        if not self._connected:
            return 0  # If Redis is down, don't block requests
            
        try:
            rate_key = f"{settings.CACHE_PREFIX}rate:{key}"
            
            # Increment and set expiry atomically
            pipe = self.redis_client.pipeline()
            pipe.incr(rate_key)
            pipe.expire(rate_key, window_seconds)
            results = await pipe.execute()
            
            return results[0]  # Current count
            
        except Exception as e:
            logger.error(f"Error in rate limiting: {str(e)}")
            return 0
    
    async def get_rate_limit_count(self, key: str) -> int:
        """Get current rate limit count for a key."""
        if not self._connected:
            return 0
            
        try:
            rate_key = f"{settings.CACHE_PREFIX}rate:{key}"
            count = await self.redis_client.get(rate_key)
            return int(count) if count else 0
            
        except Exception as e:
            logger.error(f"Error getting rate limit count: {str(e)}")
            return 0
    
    # =========================================
    # UTILITY METHODS
    # =========================================
    
    def _generate_title(self, first_message: str, max_length: int = 50) -> str:
        """
        Generate a session title from the first message.
        
        Simple truncation for now. Could be enhanced with LLM summarization.
        """
        title = first_message.strip()
        if len(title) > max_length:
            title = title[:max_length].rsplit(' ', 1)[0] + "..."
        return title
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Get Redis health and statistics.
        
        Used by health check endpoint.
        """
        if not self._connected:
            return {
                "status": "disconnected",
                "connected": False
            }
            
        try:
            info = await self.redis_client.info()
            
            # Count cached items
            session_pattern = f"{settings.CACHE_PREFIX}session:*"
            session_keys = await self.redis_client.keys(session_pattern)
            
            return {
                "status": "healthy",
                "connected": True,
                "redis_version": info.get("redis_version", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory": info.get("used_memory_human", "0"),
                "active_sessions_cached": len(session_keys),
            }
            
        except Exception as e:
            return {
                "status": "error",
                "connected": False,
                "error": str(e)
            }
    
    async def flush_all(self) -> bool:
        """
        Clear all cached data.
        
        ⚠️ USE WITH CAUTION - Only for testing/development!
        This will clear ALL data in the Redis database.
        """
        if not self._connected:
            return False
            
        if settings.ENVIRONMENT != 'development':
            logger.error("Refusing to flush Redis in non-development environment")
            return False
            
        try:
            await self.redis_client.flushdb()
            logger.warning("⚠️ Redis cache flushed")
            return True
        except Exception as e:
            logger.error(f"Error flushing Redis: {str(e)}")
            return False


# =========================================
# GLOBAL INSTANCE AND DEPENDENCY
# =========================================

# Global Redis manager instance
redis_manager = RedisManager()


async def get_redis() -> RedisManager:
    """
    FastAPI Dependency for Redis Manager
    ------------------------------------
    
    HOW TO USE:
    ```python
    @router.get("/sessions")
    async def get_sessions(redis: RedisManager = Depends(get_redis)):
        return await redis.get_user_active_sessions(user_id)
    ```
    
    NOTE: Returns the manager even if Redis is disconnected.
    All methods gracefully handle disconnection.
    """
    return redis_manager 