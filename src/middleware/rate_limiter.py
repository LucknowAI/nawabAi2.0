from fastapi import Request, HTTPException, status
import time
import asyncio
from src.config.settings import Settings

class RateLimiter:
    def __init__(self):
        self.requests = {}
        self.max_requests = Settings.RATE_LIMIT
        self.window = 60  # 1 minute window
        self.semaphore = asyncio.Semaphore(Settings.MAX_WORKERS)
        
    async def check_rate_limit(self, request: Request):
        client_ip = request.client.host
        current_time = time.time()
        
        # Clean old requests
        self.requests = {ip: times for ip, times in self.requests.items() 
                         if current_time - times[-1] < self.window}
        
        # Check current IP
        if client_ip not in self.requests:
            self.requests[client_ip] = [current_time]
        else:
            # Filter times within the window
            self.requests[client_ip] = [t for t in self.requests[client_ip] 
                                       if current_time - t < self.window]
            self.requests[client_ip].append(current_time)
            
            if len(self.requests[client_ip]) > self.max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please try again later."
                )

    async def acquire_worker(self):
        await self.semaphore.acquire()
        
    def release_worker(self):
        self.semaphore.release()