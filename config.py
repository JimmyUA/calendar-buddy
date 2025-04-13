# config.py
import os
import logging
from dotenv import load_dotenv
from google.cloud import firestore # Import Firestore

load_dotenv()


logger = logging.getLogger(__name__)


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS_FILE")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") # For Gemini
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI")
WEB_SERVER_HOST = os.getenv("WEB_SERVER_HOST", "127.0.0.1")
WEB_SERVER_PORT = int(os.getenv("WEB_SERVER_PORT", 5000))
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if GOOGLE_APPLICATION_CREDENTIALS and not os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
    # Set environment variable if defined in .env but not already set in environment
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_APPLICATION_CREDENTIALS

# Scopes required for Google APIs
GOOGLE_CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events'
]

# --- Firestore Client Initialization ---
try:
    FIRESTORE_DB = firestore.Client()
    # Optionally test connection, e.g., list collections (might add latency)
    # list(FIRESTORE_DB.collections())
    logger.info("Firestore client initialized successfully.")
except Exception as e:
    logger.critical(f"FATAL: Failed to initialize Firestore client: {e}", exc_info=True)
    logger.critical("Ensure Firestore API is enabled and authentication is configured (ADC or GOOGLE_APPLICATION_CREDENTIALS).")
    FIRESTORE_DB = None # Indicate failure
    # Depending on your app's needs, you might want to raise an exception here
    # raise RuntimeError("Failed to initialize Firestore") from e
# --- End Firestore Init ---

# Keep pending events in memory for now
pending_events = {}
# --- NEW: Add dictionary for pending deletions ---
pending_deletions = {} # Stores {user_id: {'event_id': '...', 'summary': '...'}} for confirmation

# Basic validation
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing environment variable: TELEGRAM_BOT_TOKEN")
if not GOOGLE_CLIENT_SECRETS_FILE or not os.path.exists(GOOGLE_CLIENT_SECRETS_FILE):
     raise ValueError("Missing or invalid GOOGLE_CLIENT_SECRETS_FILE")
if not GOOGLE_API_KEY:
    print("Warning: Missing GOOGLE_API_KEY for Gemini. LLM features will fail.")
if not OAUTH_REDIRECT_URI:
    raise ValueError("Missing environment variable: OAUTH_REDIRECT_URI")

print("Config loaded successfully.")