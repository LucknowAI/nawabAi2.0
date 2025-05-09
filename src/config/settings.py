from dotenv import load_dotenv
import os

load_dotenv()

class Settings:
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    # JWT_SECRET = os.getenv('JWT_SECRET')  # Replace with your actual secret
    # JWT_ALGORITHM = os.getenv('JWT_ALGORITHM')
    # DATABASE_URL = os.getenv('DATABASE_URL')  
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    SERPER_API_KEY = os.getenv('SERPER_API_KEY')

    #APP Configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    ENVIRONMENT = os.getenv('ENVIRONMENT', 'development')
    
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


settings = Settings()