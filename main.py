import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

from src.api.chatRouter import chat_router
from src.api.cityRouter import city_router
from src.api.healthRouter import health_router
from src.api.auth.auth_routes import router as auth_router
from src.middleware.rate_limiter import RateLimiter
from src.config.settings import Settings
from src.utils.util_logger.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Nawab AI 2.0")

    # Connect to Redis (graceful — won't abort startup if Redis is unavailable)
    try:
        from src.database.redis import redis_manager
        await redis_manager.connect()
    except Exception as exc:
        logger.warning("Redis unavailable at startup — rate limiting falls back to in-memory", extra={"error": str(exc)})

    yield

    logger.info("Shutting down Nawab AI 2.0")
    try:
        from src.database.redis import redis_manager
        await redis_manager.disconnect()
    except Exception:
        pass


rate_limiter = RateLimiter()


class _RateLimitAndTimingMiddleware:
    """Pure ASGI middleware for rate-limiting and request timing.

    Using a Pure ASGI middleware instead of BaseHTTPMiddleware (which is what
    @app.middleware("http") creates) avoids response-body buffering.
    BaseHTTPMiddleware buffers the entire response before forwarding it, which
    breaks streaming endpoints like the SSE chat route (FastAPI Tip #8).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        start_time = time.time()

        # ── Rate limit check ──────────────────────────────────────────────────
        try:
            await rate_limiter.check_rate_limit(request)
        except HTTPException as exc:
            resp = Response(content=exc.detail, status_code=exc.status_code)
            await resp(scope, receive, send)
            return
        except Exception as exc:
            resp = Response(content=str(exc), status_code=429)
            await resp(scope, receive, send)
            return

        # ── Worker semaphore ──────────────────────────────────────────────────
        try:
            await rate_limiter.acquire_worker()
        except HTTPException as exc:
            resp = Response(content=exc.detail, status_code=exc.status_code)
            await resp(scope, receive, send)
            return

        # ── Wrap send to inject X-Process-Time header ─────────────────────────
        async def _send_with_timing(message: dict) -> None:
            if message["type"] == "http.response.start":
                process_time = time.time() - start_time
                headers = MutableHeaders(scope=message)
                headers.append("X-Process-Time", str(process_time))
                logger.info(
                    "Request completed",
                    extra={
                        "path": scope.get("path", ""),
                        "duration_ms": round(process_time * 1000, 1),
                    },
                )
            await send(message)

        try:
            await self.app(scope, receive, _send_with_timing)
        except Exception as exc:
            logger.error("Unhandled request error", extra={"error": str(exc)})
            raise
        finally:
            rate_limiter.release_worker()


app = FastAPI(
    title="Nawab Chat API",
    description="AI assistant for Indian cities — Lucknow, Delhi, and more",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if Settings.ENVIRONMENT == "development" else None,
    redoc_url="/redoc" if Settings.ENVIRONMENT == "development" else None,
    openapi_url="/openapi.json" if Settings.ENVIRONMENT == "development" else None,
)

# Middleware is applied last-added = outermost.
# Order: _RateLimitAndTimingMiddleware (outermost) → CORSMiddleware → app
app.add_middleware(CORSMiddleware,
    allow_origins=Settings.FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(_RateLimitAndTimingMiddleware)


# Routers
app.include_router(chat_router, prefix="/api/v1")
app.include_router(city_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
