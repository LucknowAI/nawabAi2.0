from fastapi import Request, HTTPException, status
import time
import asyncio
from src.config.settings import Settings
from collections import defaultdict
from typing import Dict, List, Set
import logging

class RateLimiter:
    def __init__(self):
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self.max_requests = Settings.RATE_LIMIT
        self.window = 60  # 1 minute window
        self.semaphore = asyncio.Semaphore(Settings.MAX_WORKERS)
        self.ip_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.cleanup_lock = asyncio.Lock()
        self.last_cleanup = time.time()
        self.cleanup_interval = 60  # Cleanup every minute
        self.banned_ips: Set[str] = set()
        self.ban_threshold = Settings.BAN_THRESHOLD  # Number of rate limit violations before ban
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
            
    async def check_rate_limit(self, request: Request):
        client_ip = request.client.host
        current_time = time.time()
        
        # Check if IP is banned
        if client_ip in self.banned_ips:
            ban_time = self.requests.get(f"ban:{client_ip}", [0])[0]
            if current_time - ban_time < self.ban_duration:
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
                                      if current_time - t < self.window]
            self.requests[client_ip].append(current_time)
            
            # Check rate limit
            if len(self.requests[client_ip]) > self.max_requests:
                # Increment violation count
                violation_key = f"violations:{client_ip}"
                violations = len(self.requests.get(violation_key, []))
                self.requests[violation_key] = [current_time]
                
                if violations >= self.ban_threshold:
                    # Ban the IP
                    self.banned_ips.add(client_ip)
                    self.requests[f"ban:{client_ip}"] = [current_time]
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="IP has been banned due to multiple rate limit violations"
                    )
                    
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Please try again in {self.window} seconds."
                )

    async def acquire_worker(self):
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=5.0)
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server is currently overloaded. Please try again later."
            )
        
    def release_worker(self):
        try:
            self.semaphore.release()
        except ValueError:
            logging.warning("Attempted to release a worker that wasn't acquired")