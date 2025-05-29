# google_services.py
import logging
import json
import os
import uuid
from datetime import datetime, timezone, timedelta # Ensure timedelta is imported
from dateutil import parser as dateutil_parser
from google.cloud import secretmanager # Import Secret Manager client

import pytz # <--- ADD IMPORT

# Google specific imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

# Firestore specific imports
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.api_core.exceptions import NotFound
from pytz.exceptions import UnknownTimeZoneError

import config # Import our config
from models import CalendarAccessRequest # Import the Pydantic model

logger = logging.getLogger(__name__)

# --- Firestore Client and Collections ---
db = config.FIRESTORE_DB
OAUTH_STATES_COLLECTION = db.collection('oauth_states') if db else None
USER_TOKENS_COLLECTION = db.collection('user_tokens') if db else None
USER_PREFS_COLLECTION = db.collection(config.FS_COLLECTION_PREFS) if db else None
FS_COLLECTION_GROCERY_LISTS = db.collection(config.FS_COLLECTION_GROCERY_LISTS) if db else None
PENDING_EVENTS_COLLECTION = db.collection(config.FS_COLLECTION_PENDING_EVENTS) if db else None
PENDING_DELETIONS_COLLECTION = db.collection(config.FS_COLLECTION_PENDING_DELETIONS) if db else None
CALENDAR_ACCESS_REQUESTS_COLLECTION = db.collection(config.FS_COLLECTION_CALENDAR_ACCESS_REQUESTS) if db else None


# === Pending Event Management (Firestore) ===

def add_pending_event(user_id: int, event_data: dict) -> bool:
    """Stores event_data in Firestore for later confirmation."""
    if not PENDING_EVENTS_COLLECTION:
        logger.error("Firestore PENDING_EVENTS_COLLECTION unavailable for adding pending event.")
        return False
    user_doc_id = str(user_id)
    doc_ref = PENDING_EVENTS_COLLECTION.document(user_doc_id)
    try:
        doc_ref.set({
            'event_data': event_data,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        logger.info(f"Stored pending event for user {user_id} in '{config.FS_COLLECTION_PENDING_EVENTS}'")
        return True
    except Exception as e:
        logger.error(f"Failed to store pending event for user {user_id}: {e}", exc_info=True)
        return False

def get_pending_event(user_id: int) -> dict | None:
    """Retrieves pending event data for a user from Firestore."""
    if not PENDING_EVENTS_COLLECTION:
        logger.error("Firestore PENDING_EVENTS_COLLECTION unavailable for getting pending event.")
        return None
    user_doc_id = str(user_id)
    doc_ref = PENDING_EVENTS_COLLECTION.document(user_doc_id)
    try:
        snapshot = doc_ref.get()
        if snapshot.exists:
            data = snapshot.to_dict()
            logger.debug(f"Retrieved pending event for user {user_id}.")
            return data.get('event_data') # Return only the event_data part
        else:
            logger.debug(f"No pending event found for user {user_id}.")
            return None
    except Exception as e:
        logger.error(f"Error fetching pending event for user {user_id}: {e}", exc_info=True)
        return None

def delete_pending_event(user_id: int) -> bool:
    """Deletes a pending event document for a user from Firestore."""
    if not PENDING_EVENTS_COLLECTION:
        logger.error("Firestore PENDING_EVENTS_COLLECTION unavailable for deleting pending event.")
        return False
    user_doc_id = str(user_id)
    doc_ref = PENDING_EVENTS_COLLECTION.document(user_doc_id)
    try:
        doc_ref.delete()
        logger.info(f"Deleted pending event for user {user_id} (if it existed).")
        return True # Success even if doc didn't exist, as per Firestore behavior
    except Exception as e:
        logger.error(f"Failed to delete pending event for user {user_id}: {e}", exc_info=True)
        return False

# === Pending Deletion Management (Firestore) ===

def add_pending_deletion(user_id: int, deletion_data: dict) -> bool:
    """Stores deletion_data (e.g., event_id, summary) in Firestore for later confirmation."""
    if not PENDING_DELETIONS_COLLECTION:
        logger.error("Firestore PENDING_DELETIONS_COLLECTION unavailable for adding pending deletion.")
        return False
    user_doc_id = str(user_id)
    doc_ref = PENDING_DELETIONS_COLLECTION.document(user_doc_id)
    try:
        # Store the provided deletion_data directly, ensure it includes event_id and summary
        doc_ref.set({
            'deletion_data': deletion_data, # e.g., {'event_id': 'xyz', 'summary': 'Event to delete'}
            'created_at': firestore.SERVER_TIMESTAMP
        })
        logger.info(f"Stored pending deletion for user {user_id} in '{config.FS_COLLECTION_PENDING_DELETIONS}'")
        return True
    except Exception as e:
        logger.error(f"Failed to store pending deletion for user {user_id}: {e}", exc_info=True)
        return False

def get_pending_deletion(user_id: int) -> dict | None:
    """Retrieves pending deletion data for a user from Firestore."""
    if not PENDING_DELETIONS_COLLECTION:
        logger.error("Firestore PENDING_DELETIONS_COLLECTION unavailable for getting pending deletion.")
        return None
    user_doc_id = str(user_id)
    doc_ref = PENDING_DELETIONS_COLLECTION.document(user_doc_id)
    try:
        snapshot = doc_ref.get()
        if snapshot.exists:
            data = snapshot.to_dict()
            logger.debug(f"Retrieved pending deletion for user {user_id}.")
            return data.get('deletion_data') # Return only the deletion_data part
        else:
            logger.debug(f"No pending deletion found for user {user_id}.")
            return None
    except Exception as e:
        logger.error(f"Error fetching pending deletion for user {user_id}: {e}", exc_info=True)
        return None

def delete_pending_deletion(user_id: int) -> bool:
    """Deletes a pending deletion document for a user from Firestore."""
    if not PENDING_DELETIONS_COLLECTION:
        logger.error("Firestore PENDING_DELETIONS_COLLECTION unavailable for deleting pending deletion.")
        return False
    user_doc_id = str(user_id)
    doc_ref = PENDING_DELETIONS_COLLECTION.document(user_doc_id)
    try:
        doc_ref.delete()
        logger.info(f"Deleted pending deletion for user {user_id} (if it existed).")
        return True # Success even if doc didn't exist
    except Exception as e:
        logger.error(f"Failed to delete pending deletion for user {user_id}: {e}", exc_info=True)
        return False

# === Google Authentication & Firestore Persistence ===
# --- NEW: Get Single Event by ID ---
async def get_calendar_event_by_id(user_id: int, event_id: str) -> dict | None:
    """Fetches a single calendar event by its ID."""
    service = _build_calendar_service_client(user_id)
    if not service: return None # type: ignore
    logger.info(f"GS: Fetching event details for ID {event_id} for user {user_id}")
    try:
        event = service.events().get(calendarId='primary', eventId=event_id).execute()
        return event # Returns the full event resource
    except HttpError as error:
        logger.error(f"GS: API error fetching event {event_id} for {user_id}: {error}")
        if error.resp.status == 404 or error.resp.status == 410: # Not Found or Gone
             logger.warning(f"GS: Event {event_id} not found for user {user_id}.")
        elif error.resp.status == 401: delete_user_token(user_id) # Clear token on auth error
        return None
    except Exception as e:
        logger.error(f"GS: Unexpected error fetching event {event_id} for {user_id}: {e}", exc_info=True)
        return None

# --- Timezone Functions (Using NEW Collection) ---
def set_user_timezone(user_id: int, timezone_str: str) -> bool:
    """
    Stores the user's validated IANA timezone string in Firestore.
    """
    if not USER_PREFS_COLLECTION:
        logger.error("Firestore USER_PREFS_COLLECTION unavailable for setting timezone/username.")
        return False
    user_doc_id = str(user_id)
    doc_ref = USER_PREFS_COLLECTION.document(user_doc_id)
    try:
        # Validate timezone before storing
        pytz.timezone(timezone_str)

        data_to_set = {
            'timezone': timezone_str,
            'updated_at': firestore.SERVER_TIMESTAMP
        }
        logger.info(f"Preparing to store timezone '{timezone_str}' for user {user_id}")

        # Using set with merge=True to avoid overwriting other potential preferences
        # (like a previously stored username, though we are removing that functionality)
        # and to create the document if it doesn't exist.
        doc_ref.set(data_to_set, merge=True)

        logger.info(f"Stored timezone '{timezone_str}' for user {user_id} in '{config.FS_COLLECTION_PREFS}'")
        return True
    except UnknownTimeZoneError:
        logger.warning(f"Attempted to store invalid timezone '{timezone_str}' for user {user_id}")
        return False
    except Exception as e:
        logger.error(f"Failed to store timezone/username for user {user_id}: {e}", exc_info=True)
        return False

def get_user_id_by_username(username: str) -> str | None:
    """
    Queries USER_PREFS_COLLECTION for a document with a matching telegram_username.
    Returns the document ID (user_id) if found, otherwise None.
    Performs a case-insensitive search by querying for both original, lower, and upper case.
    Note: Firestore is case-sensitive for direct queries. For true case-insensitivity
    without multiple queries or storing a normalized field, client-side filtering or
    a more complex setup (e.g., search service) would be needed.
    This implementation tries a few common casings. A more robust solution is to store
    a normalized (e.g., lowercase) version of the username.
    """
    if not USER_PREFS_COLLECTION:
        logger.error("Firestore USER_PREFS_COLLECTION unavailable for get_user_id_by_username.")
        return None

    # Attempt common casings. For true case-insensitivity, store a normalized username.
    # usernames_to_check = list(set([username, username.lower(), username.capitalize()]))
    # For now, we assume the username is stored as is, and we will query for that.
    # A better solution is to store username.lower() and query for username.lower().
    # We will assume for now that the username is stored as it's passed.

    try:
        # Query for the exact username match first (common case)
        query = USER_PREFS_COLLECTION.where(filter=FieldFilter("telegram_username", "==", username)).limit(1)
        results = list(query.stream())

        if results:
            user_doc = results[0]
            logger.info(f"Found user ID '{user_doc.id}' for username '{username}' (exact match).")
            return user_doc.id # Document ID is the user_id

        # If no exact match, try lowercase (if different from original)
        # This is a common way to handle case-insensitivity if not storing a normalized field
        # However, this requires the stored username to also be lowercase for this to work reliably.
        # Given the current set_user_timezone, it stores the username as is.
        # So, for now, we will only do an exact match.
        # if username.lower() != username:
        #     query_lower = USER_PREFS_COLLECTION.where(filter=FieldFilter("telegram_username", "==", username.lower())).limit(1)
        #     results_lower = list(query_lower.stream())
        #     if results_lower:
        #         user_doc_lower = results_lower[0]
        #         logger.info(f"Found user ID '{user_doc_lower.id}' for username '{username}' (lowercase match).")
        #         return user_doc_lower.id

        logger.info(f"No user found with username '{username}' in '{config.FS_COLLECTION_PREFS}'.")
        return None
    except Exception as e:
        logger.error(f"Error querying for user by username '{username}': {e}", exc_info=True)
        return None

def get_user_timezone_str(user_id: int) -> str | None:
    """Retrieves the user's timezone string from Firestore."""
    # ---> Use USER_PREFS_COLLECTION <---
    if not USER_PREFS_COLLECTION:
        logger.error("Firestore USER_PREFS_COLLECTION unavailable for getting timezone.")
        return None
    user_doc_id = str(user_id)
    doc_ref = USER_PREFS_COLLECTION.document(user_doc_id)
    try:
        snapshot = doc_ref.get() # Fetch the preferences document

        if snapshot.exists:
            prefs_data = snapshot.to_dict()
            if 'timezone' in prefs_data: # Check if the field exists
                tz_str = prefs_data.get('timezone')
                # Optional re-validation
                try:
                    pytz.timezone(tz_str)
                    logger.debug(f"Found timezone '{tz_str}' for user {user_id} in '{config.FS_COLLECTION_PREFS}'")
                    return tz_str
                except UnknownTimeZoneError:
                    logger.warning(f"Found invalid timezone '{tz_str}' in DB prefs for user {user_id}. Treating as unset.")
                    return None
            else:
                logger.debug(f"Timezone field not found in prefs for user {user_id}")
                return None
        else:
            logger.debug(f"User preferences document not found for user {user_id}, timezone not set.")
            return None
    except Exception as e:
        logger.error(f"Error fetching timezone for user {user_id}: {e}", exc_info=True)
        return None

async def get_calendar_events(user_id: int, time_min_iso: str, time_max_iso: str, max_results: int = 25) -> list | None:
    """
    Fetches events given ISO datetime strings.
    Returns list of event dicts or None on error.
    """
    service = _build_calendar_service_client(user_id)
    if not service: return None # type: ignore
    logger.debug(f"GS: Fetching events for {user_id} from {time_min_iso} to {time_max_iso}")
    try:
        events_result = service.events().list(
            calendarId='primary', timeMin=time_min_iso, timeMax=time_max_iso,
            maxResults=max_results, singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        # Return essential info for the agent
        return [
            {
                "id": e.get("id"),
                "summary": e.get("summary"),
                "start": e.get("start"),
                "end": e.get("end"),
                "description": e.get("description"),
                "location": e.get("location"),
            } for e in events
        ]
    except HttpError as error:
        # ... (error handling as before, including delete_user_token on 401) ...
        logger.error(f"GS: API error fetching events for {user_id}: {error}")
        if error.resp.status == 401: delete_user_token(user_id)
        return None
    except Exception as e: logger.error(f"GS: Unexpected error fetching events for {user_id}: {e}", exc_info=True); return None

# --- NEW: Dedicated Search Function ---
async def search_calendar_events(user_id: int, query: str, time_min_iso: str, time_max_iso: str, max_results: int = 10) -> list | None:
    """
    Searches events using a query string within a time range.
    Returns list of essential event info dicts or None on error.
    """
    service = _build_calendar_service_client(user_id)
    if not service: return None # type: ignore
    logger.info(f"GS: Searching events for {user_id} with query '{query}' from {time_min_iso} to {time_max_iso}")
    try:
        events_result = service.events().list(
            calendarId='primary',
            q=query, # Use the q parameter for searching
            timeMin=time_min_iso,
            timeMax=time_max_iso,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime' # Or 'relevance' if preferred for search
        ).execute()
        events = events_result.get('items', [])
        logger.info(f"GS: Found {len(events)} events matching search.")
        # Return essential info
        return [
            {
                "id": e.get("id"),
                "summary": e.get("summary"),
                "start": e.get("start"),
                "end": e.get("end"),
            } for e in events
        ]
    except HttpError as error:
        # ... (error handling as before) ...
        logger.error(f"GS: API error searching events for {user_id}: {error}")
        if error.resp.status == 401: delete_user_token(user_id)
        return None
    except Exception as e: logger.error(f"GS: Unexpected error searching events for {user_id}: {e}", exc_info=True); return None

def get_google_auth_flow():
    """Creates OAuth Flow using config from environment variable."""
    client_secrets_content = os.getenv("GOOGLE_CLIENT_SECRETS_CONTENT") # Use the content env var
    if not client_secrets_content:
        logger.error("GOOGLE_CLIENT_SECRETS_CONTENT environment variable not set.")
        return None

    try:
        client_config_dict = json.loads(client_secrets_content)
        # Determine key ('web' or 'installed') - IMPORTANT
        flow_key = "web" if "web" in client_config_dict else "installed"
        if flow_key not in client_config_dict:
            logger.error("Client secrets content missing 'web' or 'installed' key.")
            return None

        # Use from_client_config
        return Flow.from_client_config(
            client_config_dict, # Pass the loaded dictionary
            scopes=config.GOOGLE_CALENDAR_SCOPES,
            redirect_uri=config.OAUTH_REDIRECT_URI
        )
    except json.JSONDecodeError as e:
         logger.error(f"Failed to parse client secrets JSON from env var: {e}")
         return None
    except Exception as e:
        logger.error(f"Error creating OAuth flow from env var config: {e}", exc_info=True)
        return None

def generate_oauth_state(user_id: int) -> str | None:
    """Generates a unique state token and stores the mapping in Firestore."""
    if not OAUTH_STATES_COLLECTION: logger.error("Firestore OAUTH_STATES_COLLECTION not available."); return None
    state = str(uuid.uuid4())
    doc_ref = OAUTH_STATES_COLLECTION.document(state)
    try:
        write_result = doc_ref.set({'user_id': user_id, 'created_at': firestore.SERVER_TIMESTAMP})
        logger.info(f"Successfully wrote state {state} for user {user_id} to Firestore. Write time: {write_result.update_time}")
        return state
    except Exception as e:
        logger.error(f"Firestore write FAILED for state {state}, user {user_id}: {e}", exc_info=True)
        return None

@firestore.transactional
def _verify_and_delete_state(transaction, state_doc_ref):
    """Transactional helper for verify_oauth_state."""
    try:
        snapshot = state_doc_ref.get(transaction=transaction)
        if snapshot.exists:
            user_id = snapshot.get('user_id')
            transaction.delete(state_doc_ref)
            return user_id
        else:
            return None
    except Exception as e:
        logger.error(f"Error within Firestore transaction for state verification: {e}", exc_info=True)
        raise # Re-raise to make transaction fail

def verify_oauth_state(state: str) -> int | None:
    """Verifies state token from Firestore, consumes it, and returns user_id."""
    if not OAUTH_STATES_COLLECTION: logger.error("Firestore OAUTH_STATES_COLLECTION not available."); return None
    state_doc_ref = OAUTH_STATES_COLLECTION.document(state)
    transaction = db.transaction()
    try:
        user_id = _verify_and_delete_state(transaction, state_doc_ref)
        if user_id:
            logger.info(f"Verified and consumed OAuth state {state} for user {user_id} from Firestore")
            return user_id
        else:
            logger.warning(f"Invalid or expired OAuth state received (not found in Firestore): {state}")
            return None
    except Exception as e:
        logger.error(f"Error verifying OAuth state {state} in Firestore transaction: {e}", exc_info=True)
        return None


def store_user_credentials(user_id: int, credentials) -> bool:
    """Stores or updates the user's Google credentials JSON in Firestore."""
    if not USER_TOKENS_COLLECTION: logger.error("Firestore USER_TOKENS_COLLECTION not available."); return False
    creds_json = credentials.to_json()
    user_doc_id = str(user_id)
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        doc_ref.set({'credentials_json': creds_json, 'updated_at': firestore.SERVER_TIMESTAMP}, merge=False)
        logger.info(f"Stored/Updated credentials in Firestore for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to store credentials in Firestore for user {user_id}: {e}", exc_info=True)
        return False

def is_user_connected(user_id: int) -> bool:
    """Checks if a token document exists for the user in Firestore."""
    if not USER_TOKENS_COLLECTION: return False
    user_doc_id = str(user_id)
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        # Efficient check for existence
        snapshot = doc_ref.get(field_paths=['updated_at'])
        return snapshot.exists
    except Exception as e:
        logger.error(f"Error checking token existence in Firestore for user {user_id}: {e}", exc_info=True)
        return False # Assume not connected on error

def delete_user_token(user_id: int) -> bool:
    """Deletes the token document for a given user_id from Firestore."""
    if not USER_TOKENS_COLLECTION: return False
    user_doc_id = str(user_id)
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        delete_result = doc_ref.delete()
        logger.info(f"Attempted deletion of token from Firestore for user {user_id}. Result time: {delete_result.update_time}")
        return True # Assume success unless exception
    except Exception as e:
        logger.error(f"Failed to delete token from Firestore for user {user_id}: {e}", exc_info=True)
        return False


# === Google Calendar API Services ===

def _build_calendar_service_client(user_id: int):
    """Internal helper to get authorized Google Calendar service client."""
    if not USER_TOKENS_COLLECTION: logger.error("Firestore unavailable for Calendar service."); return None

    creds = None
    creds_json = None
    user_doc_id = str(user_id)
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)

    try:
        snapshot = doc_ref.get()
        if snapshot.exists: creds_json = snapshot.get('credentials_json')
        else: logger.info(f"_build_calendar_service_client: No creds found for {user_id}."); return None
    except Exception as e: logger.error(f"Error fetching token for Calendar service for {user_id}: {e}"); return None

    if not creds_json: return None

    try:
        creds_info = json.loads(creds_json)
        creds = Credentials.from_authorized_user_info(creds_info, config.GOOGLE_CALENDAR_SCOPES)
    except Exception as e: logger.error(f"Failed to load creds from info for {user_id}: {e}"); return None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info(f"Refreshing Calendar credentials for user {user_id}")
                creds.refresh(Request())
                if not store_user_credentials(user_id, creds): # Check if storing failed
                    logger.error(f"Failed to store refreshed credentials for user {user_id}")
                    # Decide if we should proceed with the temporary creds or fail
                    return None # Safer to fail if store fails
                logger.info(f"Calendar Credentials refreshed successfully for {user_id}")
            except Exception as e:
                logger.error(f"Failed to refresh Calendar credentials for {user_id}: {e}")
                try: logger.warning(f"Clearing invalid token from Firestore for {user_id} after refresh failure."); doc_ref.delete()
                except Exception as db_e: logger.error(f"Failed to delete token for {user_id}: {db_e}")
                return None
        else:
            logger.warning(f"Stored Calendar credentials for {user_id} invalid/missing refresh token.");
            try: doc_ref.delete()
            except Exception: pass
            return None

    try:
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        return service
    except HttpError as error:
        logger.error(f"API error building Calendar service for {user_id}: {error}")
        if error.resp.status == 401: logger.warning(f"Auth error (401) building Calendar service for {user_id}. Clearing token."); delete_user_token(user_id)
        return None
    except Exception as e:
        logger.error(f"Unexpected error building Calendar service for {user_id}: {e}"); return None

async def create_calendar_event(user_id: int, event_data: dict) -> tuple[bool, str, str | None]:
    """Creates an event. Returns (success, message, event_link)."""
    service = _build_calendar_service_client(user_id)
    service = _build_calendar_service_client(user_id) # type: ignore
    if not service: return False, "Authentication failed or required.", None

    logger.info(f"Attempting to create event for user {user_id}: {event_data.get('summary')}")
    try:
        event = service.events().insert(calendarId='primary', body=event_data).execute()
        link = event.get('htmlLink')
        summary = event.get('summary', 'Event')
        logger.info(f"Event created for {user_id}: {link}")
        return True, f"Event '{summary}' created successfully.", link
    except HttpError as error:
        logger.error(f"API error creating event for {user_id}: {error}")
        error_details = f"API Error ({error.resp.status}): {error.resp.reason}"
        try: error_content = json.loads(error.content.decode()); error_details = error_content.get('error', {}).get('message', error_details)
        except: pass
        if error.resp.status == 401: logger.warning(f"Auth error (401) creating event for {user_id}. Clearing token."); delete_user_token(user_id); return False, "Authentication failed. Please /connect_calendar again.", None
        return False, f"Failed to create event. {error_details}", None
    except Exception as e:
        logger.error(f"Unexpected error creating event for {user_id}: {e}", exc_info=True)
        return False, "An unexpected error occurred.", None

async def delete_calendar_event(user_id: int, event_id: str) -> tuple[bool, str]:
    """Deletes a specific event. Returns (success, message)."""
    service = _build_calendar_service_client(user_id) # type: ignore
    if not service: return False, "Authentication failed or required."

    logger.info(f"Attempting to delete event ID {event_id} for user {user_id}")
    try:
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        logger.info(f"Successfully deleted event ID {event_id} for user {user_id}.")
        return True, "Event successfully deleted."
    except HttpError as error:
        logger.error(f"API error deleting event {event_id} for {user_id}: {error}")
        error_details = f"API Error ({error.resp.status}): {error.resp.reason}"
        try: error_content = json.loads(error.content.decode()); error_details = error_content.get('error', {}).get('message', error_details)
        except: pass
        if error.resp.status == 404 or error.resp.status == 410: return False, "Couldn't delete event (not found or already deleted)."
        elif error.resp.status == 401: logger.warning(f"Auth error (401) deleting event for {user_id}. Clearing token."); delete_user_token(user_id); return False, "Authentication failed. Please /connect_calendar again."
        return False, f"Failed to delete event. {error_details}"
    except Exception as e:
        logger.error(f"Unexpected error deleting event {event_id} for {user_id}: {e}", exc_info=True)
        return False, "An unexpected error occurred while deleting the event."

# === Grocery List Management ===

def get_grocery_list(user_id: int) -> list[str] | None:
    """Retrieves the user's grocery list from Firestore."""
    if not FS_COLLECTION_GROCERY_LISTS:
        logger.error("GS: Firestore FS_COLLECTION_GROCERY_LISTS unavailable for get_grocery_list.")
        return None
    user_doc_id = str(user_id)
    doc_ref = FS_COLLECTION_GROCERY_LISTS.document(user_doc_id)
    try:
        snapshot = doc_ref.get()
        if snapshot.exists:
            data = snapshot.to_dict()
            items = data.get('items')
            if isinstance(items, list):
                logger.info(f"GS: Retrieved grocery list for user {user_id} with {len(items)} items.")
                return items
            else:
                logger.error(f"GS: 'items' field is not a list for user {user_id} in grocery list. Found: {type(items)}")
                return None # Or an empty list if preferred for this specific error
        else:
            logger.info(f"GS: No grocery list document found for user {user_id}. Returning empty list.")
            return [] # Return empty list if document doesn't exist
    except Exception as e:
        logger.error(f"GS: Error fetching grocery list for user {user_id}: {e}", exc_info=True)
        return None

def add_to_grocery_list(user_id: int, items_to_add: list[str]) -> bool:
    """Adds items to the user's grocery list in Firestore."""
    if not FS_COLLECTION_GROCERY_LISTS:
        logger.error("GS: Firestore FS_COLLECTION_GROCERY_LISTS unavailable for add_to_grocery_list.")
        return False
    if not items_to_add: # Nothing to add
        logger.info("GS: No items provided to add_to_grocery_list.")
        return True # Or False, depending on desired behavior for empty input

    user_doc_id = str(user_id)
    doc_ref = FS_COLLECTION_GROCERY_LISTS.document(user_doc_id)
    try:
        # Using set with merge=True and ArrayUnion to add/update items
        # This creates the document if it doesn't exist, or merges into existing.
        # ArrayUnion ensures items are added only if they are not already present.
        doc_ref.set({'items': firestore.ArrayUnion(items_to_add)}, merge=True)
        logger.info(f"GS: Added/Updated {len(items_to_add)} items to grocery list for user {user_id}.")
        return True
    except Exception as e:
        logger.error(f"GS: Failed to add items to grocery list for user {user_id}: {e}", exc_info=True)
        return False

def delete_grocery_list(user_id: int) -> bool:
    """Deletes the user's entire grocery list from Firestore."""
    if not FS_COLLECTION_GROCERY_LISTS:
        logger.error("GS: Firestore FS_COLLECTION_GROCERY_LISTS unavailable for delete_grocery_list.")
        return False
    user_doc_id = str(user_id)
    doc_ref = FS_COLLECTION_GROCERY_LISTS.document(user_doc_id)
    try:
        # delete() does not raise an error if the document does not exist.
        doc_ref.delete()
        logger.info(f"GS: Attempted deletion of grocery list for user {user_id}.")
        # To confirm it was deleted, we could try a get(), but for this function,
        # simply calling delete is often sufficient and idempotent.
        return True
    except Exception as e:
        logger.error(f"GS: Error deleting grocery list for user {user_id}: {e}", exc_info=True)
        return False

# === Calendar Access Requests ===

def add_calendar_access_request(
    requester_id: str,
    requester_name: str,
    target_user_id: str,
    start_time_iso: str,
    end_time_iso: str
) -> str | None:
    """
    Creates a new calendar access request document in Firestore.
    Returns the ID of the newly created request document, or None if creation fails.
    """
    if not CALENDAR_ACCESS_REQUESTS_COLLECTION:
        logger.error("Firestore CALENDAR_ACCESS_REQUESTS_COLLECTION unavailable.")
        return None

    try:
        # Create a CalendarAccessRequest Pydantic model instance first for validation (optional)
        # This helps ensure data consistency if you have complex validation rules in the model.
        # However, for direct Firestore storage, a dictionary is also fine.
        request_data = CalendarAccessRequest(
            requester_id=requester_id,
            requester_name=requester_name,
            target_user_id=target_user_id,
            start_time_iso=start_time_iso,
            end_time_iso=end_time_iso,
            status="pending",
            # request_timestamp will be set by Firestore using SERVER_TIMESTAMP
        )

        # Prepare data for Firestore, excluding fields that should not be set client-side initially
        # (like response_timestamp or if request_timestamp was purely server-side)
        # The Pydantic model by default includes all fields.
        # We need to ensure `request_timestamp` is set to the server value.
        data_to_store = request_data.model_dump(exclude_none=True)
        data_to_store['request_timestamp'] = firestore.SERVER_TIMESTAMP
        # response_timestamp is not set on creation

        # Add a new document with an auto-generated ID
        doc_ref = CALENDAR_ACCESS_REQUESTS_COLLECTION.document()
        doc_ref.set(data_to_store)

        logger.info(f"Calendar access request from {requester_id} to {target_user_id} stored with ID: {doc_ref.id}")
        return doc_ref.id
    except Exception as e:
        logger.error(f"Failed to add calendar access request from {requester_id} to {target_user_id}: {e}", exc_info=True)
        return None

def get_calendar_access_request(request_id: str) -> dict | None:
    """
    Retrieves a specific calendar access request document from Firestore.
    """
    if not CALENDAR_ACCESS_REQUESTS_COLLECTION:
        logger.error("Firestore CALENDAR_ACCESS_REQUESTS_COLLECTION unavailable for get_calendar_access_request.")
        return None
    try:
        doc_ref = CALENDAR_ACCESS_REQUESTS_COLLECTION.document(request_id)
        snapshot = doc_ref.get()
        if snapshot.exists:
            request_data = snapshot.to_dict()
            logger.info(f"Retrieved calendar access request with ID: {request_id}")
            return request_data
        else:
            logger.warning(f"Calendar access request with ID: {request_id} not found.")
            return None
    except Exception as e:
        logger.error(f"Error fetching calendar access request {request_id}: {e}", exc_info=True)
        return None

def update_calendar_access_request_status(request_id: str, status: str) -> bool:
    """
    Updates the status and response_timestamp of a calendar access request in Firestore.
    Valid statuses could be "approved", "denied", "expired", "error".
    """
    if not CALENDAR_ACCESS_REQUESTS_COLLECTION:
        logger.error("Firestore CALENDAR_ACCESS_REQUESTS_COLLECTION unavailable for update_calendar_access_request_status.")
        return False
    try:
        doc_ref = CALENDAR_ACCESS_REQUESTS_COLLECTION.document(request_id)
        update_data = {
            'status': status,
            'response_timestamp': firestore.SERVER_TIMESTAMP
        }
        doc_ref.update(update_data)
        logger.info(f"Updated calendar access request {request_id} to status '{status}'.")
        return True
    except NotFound:
        logger.warning(f"Calendar access request {request_id} not found during status update.")
        return False
    except Exception as e:
        logger.error(f"Failed to update status for calendar access request {request_id}: {e}", exc_info=True)
        return False