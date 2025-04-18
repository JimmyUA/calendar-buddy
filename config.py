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
GOOGLE_CLIENT_SECRETS_CONTENT = os.getenv("GOOGLE_CLIENT_SECRETS_CONTENT") # Rename env var for clarity
if not GOOGLE_CLIENT_SECRETS_CONTENT:
     # Change the error message if using content directly
     raise ValueError("Missing environment variable: GOOGLE_CLIENT_SECRETS_CONTENT")
# API Key is optional for LLM but features will be disabled
if not GOOGLE_API_KEY:
    logger.warning("Config: Missing GOOGLE_API_KEY. LLM features will be disabled.")
if not OAUTH_REDIRECT_URI:
    raise ValueError("Missing environment variable: OAUTH_REDIRECT_URI")
# Raise error if Firestore failed but is required
if FIRESTORE_DB is None:
     raise RuntimeError("Firestore client could not be initialized. Bot cannot run without Firestore.")

# --- NEW: Firestore Collection Names (Optional but good practice) ---
# Define collection names as constants
FS_COLLECTION_TOKENS = 'user_tokens'
FS_COLLECTION_STATES = 'oauth_states'
FS_COLLECTION_PREFS = 'user_preferences' # <--- New collection name

MAX_HISTORY_TURNS = 8 # Number of turns to keep in memory for conversation context
MAX_HISTORY_MESSAGES = 8 # Number of turns to keep in memory for conversation context
print(f"Config loaded. Using Firestore collections: {FS_COLLECTION_TOKENS}, {FS_COLLECTION_STATES}, {FS_COLLECTION_PREFS}")

print("Config loaded successfully.")