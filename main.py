from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import time 
import logging
import uvicorn

from src.api.chatRouter import chat_router
from src.api.healthRouter import health_router
from src.middleware.rate_limiter import RateLimiter
from src.config.settings import Settings

logging.basicConfig(
    level=getattr(logging, Settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("nawab-ai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize resources
    logger.info("Starting Nawab AI 2.0")
    # Add any startup code here (database connections, etc.)
    yield
    # Shutdown: Clean up resources
    logger.info("Shutting down Nawab AI 2.0")
    
    
rate_limiter = RateLimiter()
    

app = FastAPI(
    title="Nawab Chat API",
    description="AI assistant specialized in Lucknow-related information",
    version="2.0.0",
    lifespan=lifespan
)



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    
    # Apply rate limiting
    try:
        await rate_limiter.check_rate_limit(request)
    except Exception as e:
        return Response(
            content=str(e),
            status_code=429
        )
    
    # Track concurrent requests
    await rate_limiter.acquire_worker()
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        logger.info(f"Request processed in {process_time:.4f} seconds: {request.url.path}")
        return response
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        raise
    finally:
        rate_limiter.release_worker()

# Include routers
app.include_router(chat_router)
app.include_router(health_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)