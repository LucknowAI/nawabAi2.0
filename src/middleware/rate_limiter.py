from fastapi import Request, HTTPException, status
import time
import asyncio
from src.config.settings import Settings
from collections import defaultdict
from typing import Dict, List, Set, Callable, Any
import logging
from functools import wraps
import inspect

logger = logging.getLogger("rate_limiter")

class RateLimiter:
    def __init__(self):
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self.max_requests = getattr(Settings, 'RATE_LIMIT', 60)
        self.window = 60  # 1 minute window
        self.semaphore = asyncio.Semaphore(getattr(Settings, 'MAX_WORKERS', 100))
        self.ip_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.cleanup_lock = asyncio.Lock()
        self.last_cleanup = time.time()
        self.cleanup_interval = 60  # Cleanup every minute
        self.banned_ips: Set[str] = set()
        self.ban_threshold = getattr(Settings, 'BAN_THRESHOLD', 5)
        self.ban_duration = 3600  # Ban duration in seconds
        
    async def _cleanup_old_requests(self):
        """Clean up old request records"""
        async with self.cleanup_lock:
            current_time = time.time()
            if current_time - self.last_cleanup < self.cleanup_interval:
                return
                
            # Clean old requests
            for ip in list(self.requests.keys()):
                self.requests[ip] = [t for t in self.requests[ip] 
                                   if current_time - t < self.window]
                if not self.requests[ip]:
                    del self.requests[ip]
                    
            # Clean expired bans
            for ip in list(self.banned_ips):
                ban_time = self.requests.get(f"ban:{ip}", [0])[0]
                if current_time - ban_time > self.ban_duration:
                    self.banned_ips.remove(ip)
                    
            self.last_cleanup = current_time
            
    async def check_rate_limit(self, request: Request, max_requests: int = None, window: int = None):
        """Check rate limit for a request"""
        client_ip = request.client.host
        current_time = time.time()
        
        # Use custom limits if provided
        max_req = max_requests or self.max_requests
        time_window = window or self.window
        
        # Check if IP is banned
        if client_ip in self.banned_ips:
            ban_time = self.requests.get(f"ban:{client_ip}", [0])[0]
            if current_time - ban_time < self.ban_duration:
                logger.warning(f"Banned IP {client_ip} attempted access")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="IP is temporarily banned due to rate limit violations"
                )
            else:
                self.banned_ips.remove(client_ip)
        
        # Acquire IP-specific lock for thread safety
        async with self.ip_locks[client_ip]:
            # Clean old requests periodically
            await self._cleanup_old_requests()
            
            # Update requests for current IP
            self.requests[client_ip] = [t for t in self.requests[client_ip] 
                                      if current_time - t < time_window]
            self.requests[client_ip].append(current_time)
            
            # Check rate limit
            if len(self.requests[client_ip]) > max_req:
                # Increment violation count
                violation_key = f"violations:{client_ip}"
                violations = len(self.requests.get(violation_key, []))
                self.requests[violation_key] = [current_time]
                
                logger.warning(f"Rate limit exceeded for IP {client_ip}: {len(self.requests[client_ip])} requests in {time_window}s")
                
                if violations >= self.ban_threshold:
                    # Ban the IP
                    self.banned_ips.add(client_ip)
                    self.requests[f"ban:{client_ip}"] = [current_time]
                    logger.error(f"IP {client_ip} has been banned for {self.ban_duration}s")
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="IP has been banned due to multiple rate limit violations"
                    )
                    
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Please try again in {time_window} seconds.",
                    headers={"Retry-After": str(time_window)}
                )

    async def acquire_worker(self):
        """Acquire a worker from the semaphore pool"""
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error("Server overloaded - no available workers")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server is currently overloaded. Please try again later."
            )
        
    def release_worker(self):
        """Release a worker back to the semaphore pool"""
        try:
            self.semaphore.release()
        except ValueError:
            logger.warning("Attempted to release a worker that wasn't acquired")


# Decorator for endpoint-specific rate limiting
def rate_limit(max_requests: int = 5, window_seconds: int = 300):
    """
    Rate limiting decorator for FastAPI endpoints
    
    Args:
        max_requests: Maximum number of requests allowed
        window_seconds: Time window in seconds
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Extract request from function arguments
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            # Check if request is in kwargs
            if not request and 'request' in kwargs:
                request = kwargs['request']
            
            if not request:
                # If no request found, try to get it from function signature
                sig = inspect.signature(func)
                for name, param in sig.parameters.items():
                    if param.annotation == Request:
                        request = kwargs.get(name) or (args[list(sig.parameters.keys()).index(name)] if len(args) > list(sig.parameters.keys()).index(name) else None)
                        break
            
            if request:
                # Create a temporary rate limiter instance for this endpoint
                endpoint_limiter = RateLimiter()
                await endpoint_limiter.check_rate_limit(request, max_requests, window_seconds)
            
            # Call the original function
            if inspect.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


# Global rate limiter instance
rate_limiter = RateLimiter()