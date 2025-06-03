# config.py
import os
import logging
try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - stubbed in tests
    def load_dotenv(*args, **kwargs):
        return False

try:
    from google.cloud import firestore
except Exception:  # pragma: no cover - provide a minimal stub if google libs missing
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    firestore = SimpleNamespace(
        Client=lambda *a, **k: MagicMock(name="FirestoreClient"),
        SERVER_TIMESTAMP=None,
        ArrayUnion=lambda x: x,
    )

load_dotenv()
logger = logging.getLogger(__name__)

# --- Core Bot/API Settings ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TEST_TOKEN")
GOOGLE_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "client.json")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "TEST")  # For Gemini / LLM Service
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost/oauth")

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
# Provide empty dicts so tests expecting them can patch safely.
pending_events = {}
pending_deletions = {}

# --- Basic Validation ---
if not TELEGRAM_BOT_TOKEN:
    logger.warning("Config: TELEGRAM_BOT_TOKEN not set; using dummy token for tests")
GOOGLE_CLIENT_SECRETS_CONTENT = os.getenv("GOOGLE_CLIENT_SECRETS_CONTENT", "{}")
if not GOOGLE_CLIENT_SECRETS_CONTENT:
    logger.warning("Config: GOOGLE_CLIENT_SECRETS_CONTENT not provided; using empty JSON")
if not GOOGLE_API_KEY:
    logger.warning("Config: Missing GOOGLE_API_KEY. LLM features will be disabled.")
if not OAUTH_REDIRECT_URI:
    logger.warning("Config: OAUTH_REDIRECT_URI not set; using http://localhost/oauth")
if FIRESTORE_DB is None:
    from unittest.mock import MagicMock
    FIRESTORE_DB = MagicMock(name="FirestoreClientStub")

# --- NEW: Firestore Collection Names (Optional but good practice) ---
# Define collection names as constants
FS_COLLECTION_TOKENS = 'user_tokens'
FS_COLLECTION_STATES = 'oauth_states'
FS_COLLECTION_PREFS = 'user_preferences' # <--- New collection name
FS_COLLECTION_GROCERY_LISTS = 'user_grocery_lists'
FS_COLLECTION_PENDING_EVENTS = 'pending_events'
FS_COLLECTION_PENDING_DELETIONS = 'pending_deletions'
FS_COLLECTION_CALENDAR_ACCESS_REQUESTS = 'calendar_access_requests'
FS_COLLECTION_LC_CHAT_HISTORIES = 'lc_chat_histories'
FS_COLLECTION_GENERAL_CHAT_HISTORIES = 'general_chat_histories'

MAX_HISTORY_TURNS = 8 # Number of turns to keep in memory for conversation context
MAX_HISTORY_MESSAGES = 8 # Number of turns to keep in memory for conversation context
print(f"Config loaded. Using Firestore collections: {FS_COLLECTION_TOKENS}, {FS_COLLECTION_STATES}, {FS_COLLECTION_PREFS}, {FS_COLLECTION_GROCERY_LISTS}, {FS_COLLECTION_PENDING_EVENTS}, {FS_COLLECTION_PENDING_DELETIONS}, {FS_COLLECTION_CALENDAR_ACCESS_REQUESTS}, {FS_COLLECTION_LC_CHAT_HISTORIES}, {FS_COLLECTION_GENERAL_CHAT_HISTORIES}")

print("Config loaded successfully.")
