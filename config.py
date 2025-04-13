# config.py
import os
import logging
from dotenv import load_dotenv
from google.cloud import firestore

load_dotenv()
logger = logging.getLogger(__name__)

# --- Core Bot/API Settings ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS_FILE")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") # For Gemini / LLM Service
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI")

# --- Web Server Settings ---
WEB_SERVER_HOST = os.getenv("WEB_SERVER_HOST", "127.0.0.1")
WEB_SERVER_PORT = int(os.getenv("WEB_SERVER_PORT", 5000))

# --- Firestore Client Initialization ---
FIRESTORE_DB = None
try:
    # Note: Ensure authentication is configured via ADC or GOOGLE_APPLICATION_CREDENTIALS env var
    FIRESTORE_DB = firestore.Client()
    # Optional connection test: list(FIRESTORE_DB.collections())
    logger.info("Firestore client initialized successfully.")
except Exception as e:
    logger.critical(f"FATAL: Failed to initialize Firestore client: {e}", exc_info=True)
    logger.critical("Ensure Firestore API is enabled and authentication is configured.")
    # Consider raising an exception if Firestore is mandatory
    # raise RuntimeError("Firestore client could not be initialized.") from e

# --- Google API Scopes ---
GOOGLE_CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events' # Read/Write scope covers delete too
]

# --- In-Memory State Management (for this prototype) ---
# Stores temporary states related to user interactions within the bot
pending_events = {}     # {user_id: google_event_data} for creation confirmation
pending_deletions = {}  # {user_id: {'event_id': '...', 'summary': '...'}} for deletion confirmation

# --- Basic Validation ---
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing environment variable: TELEGRAM_BOT_TOKEN")
if not GOOGLE_CLIENT_SECRETS_FILE or not os.path.exists(GOOGLE_CLIENT_SECRETS_FILE):
     raise ValueError(f"Missing or invalid GOOGLE_CLIENT_SECRETS_FILE: {GOOGLE_CLIENT_SECRETS_FILE}")
# API Key is optional for LLM but features will be disabled
if not GOOGLE_API_KEY:
    logger.warning("Config: Missing GOOGLE_API_KEY. LLM features will be disabled.")
if not OAUTH_REDIRECT_URI:
    raise ValueError("Missing environment variable: OAUTH_REDIRECT_URI")
# Raise error if Firestore failed but is required
if FIRESTORE_DB is None:
     raise RuntimeError("Firestore client could not be initialized. Bot cannot run without Firestore.")

print("Config loaded successfully.")