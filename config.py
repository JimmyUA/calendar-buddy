# config.py
import os
import logging
from dotenv import load_dotenv
from google.cloud import firestore

load_dotenv()
logger = logging.getLogger(__name__)

# --- Core Bot/API Settings ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000")
OAUTH_CALLBACK_URL = os.getenv("OAUTH_CALLBACK_URL", "http://localhost:8081/oauth2callback")
GOOGLE_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS_FILE")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") # For Gemini / LLM Service
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-001") # Default model

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
# pending_events and pending_deletions have been moved to Firestore.

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
if not GEMINI_MODEL:
    logger.warning("Config: Missing GEMINI_MODEL. Using default model.")
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
FS_COLLECTION_GROCERY_LISTS = 'user_grocery_lists'
FS_COLLECTION_GROCERY_LIST_GROUPS = 'grocery_list_groups'
FS_COLLECTION_GROCERY_SHARE_REQUESTS = 'grocery_share_requests'
FS_COLLECTION_PENDING_EVENTS = 'pending_events'
FS_COLLECTION_PENDING_DELETIONS = 'pending_deletions'
FS_COLLECTION_CALENDAR_ACCESS_REQUESTS = 'calendar_access_requests'
FS_COLLECTION_LC_CHAT_HISTORIES = 'lc_chat_histories'
FS_COLLECTION_GENERAL_CHAT_HISTORIES = 'general_chat_histories'

MAX_HISTORY_TURNS = 8 # Number of turns to keep in memory for conversation context
MAX_HISTORY_MESSAGES = 8 # Number of turns to keep in memory for conversation context
print(
    f"Config loaded. Using Firestore collections: {FS_COLLECTION_TOKENS}, {FS_COLLECTION_STATES}, "
    f"{FS_COLLECTION_PREFS}, {FS_COLLECTION_GROCERY_LISTS}, {FS_COLLECTION_GROCERY_LIST_GROUPS}, "
    f"{FS_COLLECTION_GROCERY_SHARE_REQUESTS}, {FS_COLLECTION_PENDING_EVENTS}, {FS_COLLECTION_PENDING_DELETIONS}, "
    f"{FS_COLLECTION_CALENDAR_ACCESS_REQUESTS}, {FS_COLLECTION_LC_CHAT_HISTORIES}, {FS_COLLECTION_GENERAL_CHAT_HISTORIES}"
)

print("Config loaded successfully.")