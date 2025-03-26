import logging
import config

def setup_logger():
    """Sets up a global logger for the bot and API."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    )
    return logging.getLogger(__name__)

logger = setup_logger()
