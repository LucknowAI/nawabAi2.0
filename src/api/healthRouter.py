from fastapi import APIRouter, status
import psutil
import time

health_router = APIRouter(
    prefix="/health",
    tags=["Health"],
)

@health_router.get("/", status_code=status.HTTP_200_OK)
async def health_check():
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "2.0.0",
    }

@health_router.get("/metrics", status_code=status.HTTP_200_OK)
async def metrics():
    return {
        "cpu_usage": psutil.cpu_percent(),
        "memory_usage": psutil.virtual_memory().percent,
        "disk_usage": psutil.disk_usage('/').percent,
    }