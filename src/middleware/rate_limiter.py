"""
Rate limiter middleware.

Uses Redis counters (INCR + EXPIRE) when available so limits are enforced
correctly across multiple Cloud Run instances.  Falls back to per-instance
in-memory tracking when Redis is unreachable.
"""

import asyncio
import time
from collections import defaultdict
from typing import Dict, List, Set

from fastapi import Request, HTTPException, status

from src.config.settings import Settings


# ---------------------------------------------------------------------------
# Lazy Redis import — avoids hard dependency when Redis is not configured
# ---------------------------------------------------------------------------

def _get_redis_manager():
    """Return the global RedisManager, or None if import fails."""
    try:
        from src.database.redis import redis_manager
        return redis_manager
    except Exception:
        return None


class RateLimiter:
    def __init__(self):
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self.max_requests = getattr(Settings, "RATE_LIMIT", 60)
        self.window = 60  # 1-minute window
        self.semaphore = asyncio.Semaphore(getattr(Settings, "MAX_WORKERS", 100))
        self.ip_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.cleanup_lock = asyncio.Lock()
        self.last_cleanup = time.time()
        self.cleanup_interval = 60
        self.banned_ips: Set[str] = set()
        self.ban_threshold = getattr(Settings, "BAN_THRESHOLD", 5)
        self.ban_duration = 3600
        self.cache_prefix = getattr(Settings, "CACHE_PREFIX", "nawab:")

    # ------------------------------------------------------------------
    # Redis-backed counter (distributed, works across multiple instances)
    # ------------------------------------------------------------------

    async def _redis_increment(self, key: str, window: int) -> int:
        """Atomically increment a Redis counter; returns current count or 0 on failure."""
        redis = _get_redis_manager()
        if redis is None or not redis.is_connected:
            return 0
        try:
            full_key = f"{self.cache_prefix}rate:{key}"
            pipe = redis.redis_client.pipeline()
            pipe.incr(full_key)
            pipe.expire(full_key, window)
            results = await pipe.execute()
            return results[0]
        except Exception:
            return 0

    async def _redis_get_count(self, key: str) -> int:
        redis = _get_redis_manager()
        if redis is None or not redis.is_connected:
            return 0
        try:
            val = await redis.redis_client.get(f"{self.cache_prefix}rate:{key}")
            return int(val) if val else 0
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Cleanup (in-memory fallback only)
    # ------------------------------------------------------------------

    async def _cleanup_old_requests(self):
        async with self.cleanup_lock:
            now = time.time()
            if now - self.last_cleanup < self.cleanup_interval:
                return
            for ip in list(self.requests.keys()):
                self.requests[ip] = [t for t in self.requests[ip] if now - t < self.window]
                if not self.requests[ip]:
                    del self.requests[ip]
            self.last_cleanup = now

    # ------------------------------------------------------------------
    # Main check
    # ------------------------------------------------------------------

    async def check_rate_limit(self, request: Request, max_requests: int = None, window: int = None):
        """Check rate limit — Redis-backed when available, in-memory fallback otherwise."""
        client_ip = request.client.host
        now = time.time()
        max_req = max_requests or self.max_requests
        time_window = window or self.window

        # Fast path: check ban set (in-memory; bans are instance-local for now)
        if client_ip in self.banned_ips:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="IP is temporarily banned due to rate limit violations",
            )

        # Try Redis first (distributed)
        redis = _get_redis_manager()
        if redis and redis.is_connected:
            count = await self._redis_increment(client_ip, time_window)
            if count > max_req:
                # Track violations in Redis too
                viol_count = await self._redis_increment(f"viol:{client_ip}", self.ban_duration)
                if viol_count >= self.ban_threshold:
                    self.banned_ips.add(client_ip)
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="IP has been banned due to multiple rate limit violations",
                    )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Please try again in {time_window} seconds.",
                    headers={"Retry-After": str(time_window)},
                )
            return

        # Fallback: in-memory sliding window
        async with self.ip_locks[client_ip]:
            await self._cleanup_old_requests()
            self.requests[client_ip] = [
                t for t in self.requests[client_ip] if now - t < time_window
            ]
            self.requests[client_ip].append(now)

            if len(self.requests[client_ip]) > max_req:
                violation_key = f"violations:{client_ip}"
                violations = len(self.requests.get(violation_key, []))
                self.requests[violation_key] = [now]

                if violations >= self.ban_threshold:
                    self.banned_ips.add(client_ip)
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="IP has been banned due to multiple rate limit violations",
                    )

                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Please try again in {time_window} seconds.",
                    headers={"Retry-After": str(time_window)},
                )

    async def acquire_worker(self):
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=5.0)
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server is currently overloaded. Please try again later.",
            )

    def release_worker(self):
        try:
            self.semaphore.release()
        except ValueError:
            pass
