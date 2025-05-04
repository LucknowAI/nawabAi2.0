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


settings = Settings()