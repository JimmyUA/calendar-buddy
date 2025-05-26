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
from google.api_core.exceptions import NotFound
from pytz.exceptions import UnknownTimeZoneError

import config # Import our config

logger = logging.getLogger(__name__)

# --- Firestore Client and Collections ---
db = config.FIRESTORE_DB
OAUTH_STATES_COLLECTION = db.collection('oauth_states') if db else None
USER_TOKENS_COLLECTION = db.collection('user_tokens') if db else None
# ---> NEW: Reference for preferences collection <---
USER_PREFS_COLLECTION = db.collection(config.FS_COLLECTION_PREFS) if db else None
# === Google Authentication & Firestore Persistence ===
# --- NEW: Get Single Event by ID ---
async def get_calendar_event_by_id(user_id: int, event_id: str) -> dict | None:
    """Fetches a single calendar event by its ID."""
    service = _build_calendar_service_client(user_id)
    if not service: return None
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
    """Stores the user's validated IANA timezone string in Firestore."""
    # ---> Use USER_PREFS_COLLECTION <---
    if not USER_PREFS_COLLECTION:
        logger.error("Firestore USER_PREFS_COLLECTION unavailable for setting timezone.")
        return False
    user_doc_id = str(user_id) # Use user_id as document ID
    doc_ref = USER_PREFS_COLLECTION.document(user_doc_id)
    try:
        # Validate timezone before storing
        pytz.timezone(timezone_str)
        # Store/Overwrite the timezone preference in the user's preference doc
        # Using set() without merge is fine here if this doc only holds preferences
        doc_ref.set({
            'timezone': timezone_str,
            'updated_at': firestore.SERVER_TIMESTAMP # Track last update
        })
        logger.info(f"Stored timezone '{timezone_str}' for user {user_id} in '{config.FS_COLLECTION_PREFS}'")
        return True
    except UnknownTimeZoneError:
        logger.warning(f"Attempted to store invalid timezone '{timezone_str}' for user {user_id}")
        return False
    except Exception as e:
        logger.error(f"Failed to store timezone for user {user_id}: {e}", exc_info=True)
        return False

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
    if not service: return None
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
    if not service: return None
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

async def update_calendar_event(user_id: int, event_id: str, update_data: dict) -> tuple[bool, str, str | None]:
    """Updates an existing event. Returns (success, message, event_link)."""
    service = _build_calendar_service_client(user_id)
    if not service:
        return False, "Authentication failed or required. Please try /connect_calendar.", None

    if not update_data:
        logger.warning(f"GS: update_calendar_event called for user {user_id}, event {event_id} with empty update_data.")
        return False, "No changes were specified for the event update.", None

    logger.info(f"GS: Attempting to update event ID {event_id} for user {user_id} with data: {update_data}")
    try:
        # Ensure that if start or end times are provided, they include a timeZone if they are dateTime values
        # The Google API requires timeZone for dateTime, but not for date-only events.
        # This logic assumes update_data might contain start/end fields that need timezone if not already present.
        # However, the LLM preparing update_data should ideally handle this.
        # For robustness, a check could be added here if issues arise.
        # Example:
        # if 'start' in update_data and 'dateTime' in update_data['start'] and 'timeZone' not in update_data['start']:
        #     user_tz_str = get_user_timezone_str(user_id) or 'UTC' # Fallback to UTC
        #     update_data['start']['timeZone'] = user_tz_str
        # if 'end' in update_data and 'dateTime' in update_data['end'] and 'timeZone' not in update_data['end']:
        #     user_tz_str = get_user_timezone_str(user_id) or 'UTC'
        #     update_data['end']['timeZone'] = user_tz_str

        updated_event = service.events().patch(
            calendarId='primary',
            eventId=event_id,
            body=update_data,
            sendNotifications=True # Optional: To notify attendees of the change
        ).execute()

        link = updated_event.get('htmlLink')
        summary = updated_event.get('summary', 'Event') # Get summary from the updated event
        logger.info(f"GS: Event ID {event_id} updated successfully for user {user_id}. Link: {link}")
        return True, f"Event '{summary}' updated successfully.", link
    except HttpError as error:
        logger.error(f"GS: API error updating event {event_id} for user {user_id}: {error}")
        error_details = f"API Error ({error.resp.status}): {error.resp.reason}"
        try:
            error_content = json.loads(error.content.decode())
            error_details = error_content.get('error', {}).get('message', error_details)
        except: # Keep original error_details if parsing fails
            pass

        if error.resp.status == 401:
            logger.warning(f"GS: Auth error (401) updating event {event_id} for user {user_id}. Clearing token.")
            delete_user_token(user_id) # Clear token on auth error
            return False, "Authentication failed. Please /connect_calendar again and retry.", None
        elif error.resp.status == 404 or error.resp.status == 410: # Not Found or Gone
            logger.warning(f"GS: Event {event_id} not found for update by user {user_id}.")
            return False, "Couldn't update event (not found or already deleted).", None
        elif error.resp.status == 400: # Bad Request (e.g. invalid parameters in update_data)
             logger.warning(f"GS: Bad request (400) updating event {event_id} for user {user_id}. Details: {error_details}")
             return False, f"Failed to update event. The changes might be invalid. Details: {error_details}", None
        else:
            return False, f"Failed to update event. {error_details}", None
    except Exception as e:
        logger.error(f"GS: Unexpected error updating event {event_id} for user {user_id}: {e}", exc_info=True)
        return False, "An unexpected error occurred while updating the event.", None

async def delete_calendar_event(user_id: int, event_id: str) -> tuple[bool, str]:
    """Deletes a specific event. Returns (success, message)."""
    service = _build_calendar_service_client(user_id)
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