from dotenv import load_dotenv
import os

load_dotenv()

class Settings:
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')    
    JWT_SECRET = os.getenv('JWT_SECRET')  # Replace with your actual secret
    JWT_ALGORITHM = os.getenv('JWT_ALGORITHM')
    MONGO_DATABASE_URL = os.getenv('MONGO_DB_CONNECTION_STRING')  
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    SERPER_API_KEY = os.getenv('SERPER_API_KEY')
    GEMINI_MODEL_NAME = os.getenv('GEMINI_MODEL_NAME', 'google-gla:gemini-3-flash-preview')
    OPENAI_MODEL_NAME = os.getenv('OPENAI_MODEL_NAME', 'openai:gpt-5.2')


    # Rate Limiting
    RATE_LIMIT = int(os.getenv('RATE_LIMIT', 60))  # requests per minute
    MAX_WORKERS = int(os.getenv('MAX_WORKERS', 100))  # concurrent workers
    BAN_THRESHOLD = int(os.getenv('BAN_THRESHOLD', 5))  # violations before ban
    BAN_DURATION = int(os.getenv('BAN_DURATION', 3600))  # ban duration in seconds

    # JWT Settings
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', 30))
    REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv('REFRESH_TOKEN_EXPIRE_DAYS', 30))

    #APP Configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    ENVIRONMENT = os.getenv('ENVIRONMENT', 'production')  # development, staging, production
    
    # Performance Settings
    MAX_WORKERS = int(os.getenv('MAX_WORKERS', 10))
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', 30))
    RATE_LIMIT = int(os.getenv('RATE_LIMIT', 100))
    BAN_THRESHOLD = int(os.getenv('BAN_THRESHOLD', 5))  # Number of rate limit violations before ban
    
    # Cache Settings
    CACHE_TTL = int(os.getenv('CACHE_TTL', 3600))  # Default cache TTL in seconds
    CACHE_ENABLED = os.getenv('CACHE_ENABLED', 'true').lower() == 'true'
    CACHE_PREFIX = os.getenv('CACHE_PREFIX', 'nawab:')
    
    # API Settings
    API_TIMEOUT = int(os.getenv('API_TIMEOUT', 10))  # Timeout for external API calls
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', 5))  # Batch size for LLM requests
    
    # Model Settings
    MODEL_TEMPERATURE = float(os.getenv('MODEL_TEMPERATURE', '0.5'))
    MODEL_TOP_P = float(os.getenv('MODEL_TOP_P', '0.95'))
    MODEL_MAX_TOKENS = int(os.getenv('MODEL_MAX_TOKENS', 1000))
    
    # Location Settings
    VERTEX_PROJECT_LOCATION = os.getenv('VERTEX_PROJECT_LOCATION', 'asia-south1')
    VERTEX_PROJECT_ID = os.getenv('VERTEX_PROJECT_ID', 'upai-projects')

    # Google OAuth Settings
    GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')

    # PostgreSQL (async)
    POSTGRES_DB_URL = os.getenv('POSTGRES_DB_URL')  # postgresql+asyncpg://user:pass@host/db

    # CORS — comma-separated list of allowed frontend origins
    # e.g. "http://localhost:3000,https://yourapp.com"
    FRONTEND_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv('FRONTEND_ORIGINS', 'http://localhost:3000').split(',')
        if o.strip()
    ]

    # Cookie security — True in production (HTTPS), False in local dev
    # Override via COOKIE_SECURE=true/false in .env
    @property
    def COOKIE_SECURE(self) -> bool:
        override = os.getenv('COOKIE_SECURE')
        if override is not None:
            return override.lower() == 'true'
        return self.ENVIRONMENT != 'development'

    # SameSite=none required when frontend and backend are on different domains.
    # Must be paired with secure=True or browsers will reject the cookie.
    COOKIE_SAMESITE: str = os.getenv('COOKIE_SAMESITE', 'none')


settings = Settings()