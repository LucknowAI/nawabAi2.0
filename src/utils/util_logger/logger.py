import logging
from src.config.settings import Settings

logging.basicConfig(
    level=getattr(logging, Settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("nawab-ai")