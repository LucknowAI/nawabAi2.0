import time

from fastapi import APIRouter, status
import psutil

health_router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


@health_router.get("/", status_code=status.HTTP_200_OK)
async def health_check():
    from src.cities.registry import CITY_REGISTRY

    redis_status = "unconfigured"
    try:
        from src.database.redis import redis_manager
        redis_status = "healthy" if await redis_manager.ping() else "unavailable"
    except Exception:
        redis_status = "unavailable"

    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "2.0.0",
        "redis": redis_status,
        "city_registry_size": len(CITY_REGISTRY),
    }


@health_router.get("/metrics", status_code=status.HTTP_200_OK)
async def metrics():
    return {
        "cpu_usage": psutil.cpu_percent(),
        "memory_usage": psutil.virtual_memory().percent,
        "disk_usage": psutil.disk_usage("/").percent,
    }
