import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RUNWAYML_API_KEY = os.getenv("RUNWAYML_API_KEY")
FIRESTORE_PROJECT_ID = os.getenv("FIRESTORE_PROJECT_ID")

# Webhook settings
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-webhook-url.com/webhook")

# Video settings
VIDEO_DURATION = int(os.getenv("VIDEO_DURATION", 5))  # Default 5 seconds

# Logging level
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
