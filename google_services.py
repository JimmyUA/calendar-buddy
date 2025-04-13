# google_services.py
import logging
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

# Google specific imports
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

# Firestore specific imports
from google.cloud import firestore
from google.api_core.exceptions import NotFound

# Date parsing library
from dateutil import parser as dateutil_parser # Use an alias to avoid confusion

import config # Import our config

logger = logging.getLogger(__name__)

# --- Firestore Client and Collections (Initialized in config.py) ---
db = config.FIRESTORE_DB # Convenience alias from config
OAUTH_STATES_COLLECTION = db.collection('oauth_states') if db else None
USER_TOKENS_COLLECTION = db.collection('user_tokens') if db else None

# --- Google Gemini Setup ---
if config.GOOGLE_API_KEY:
    try:
        genai.configure(api_key=config.GOOGLE_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-1.5-flash') # Or 'gemini-pro'
        logger.info("Google Generative AI configured successfully.")
    except Exception as e:
        logger.error(f"Failed to configure Google Generative AI: {e}")
        gemini_model = None
else:
    gemini_model = None
    logger.warning("Google API Key not found. LLM features disabled.")

# --- NEW FUNCTION: Parse Date Range using LLM ---
async def parse_date_range_llm(text_period: str) -> dict | None:
    """
    Uses LLM (Gemini) to parse a natural language time period into start and end ISO dates.

    Args:
        text_period: The natural language string describing the time period (e.g., "today", "next week").

    Returns:
        A dictionary {'start_iso': 'YYYY-MM-DDTHH:MM:SS+ZZ:ZZ', 'end_iso': 'YYYY-MM-DDTHH:MM:SS+ZZ:ZZ'}
        or None if parsing fails or LLM is unavailable.
    """
    if not gemini_model:
        logger.error("LLM not configured, cannot parse date range.")
        return None

    now = datetime.now(timezone.utc) # Use UTC for consistency reference
    current_time_str = now.isoformat()

    prompt = f"""
    Analyze the following natural language time period description.
    Determine the precise start and end datetime for this period, relative to the current time ({current_time_str}).
    Assume standard interpretations (e.g., 'today' is from 00:00:00 to 23:59:59 in the current day, 'next week' starts on the upcoming Monday 00:00:00 and ends the following Sunday 23:59:59).
    Output the result as a JSON object containing two keys: 'start_iso' and 'end_iso'.
    The values MUST be full ISO 8601 datetime strings, including the timezone offset (e.g., 'YYYY-MM-DDTHH:MM:SS+ZZ:ZZ' or 'YYYY-MM-DDTHH:MM:SSZ'). Use UTC ('Z') if the exact local timezone is ambiguous from the input.

    Time Period Description: "{text_period}"

    JSON Output:
    """
    try:
        logger.info(f"Sending date range parsing prompt to Gemini for: '{text_period}'")
        response = await gemini_model.generate_content_async(prompt)

        if response.prompt_feedback and response.prompt_feedback.block_reason:
             logger.warning(f"LLM date range parsing response blocked: {response.prompt_feedback.block_reason}")
             return None

        if not hasattr(response, 'text'):
             logger.warning("LLM response for date range parsing missing 'text'.")
             return None

        # Clean potential markdown ```json ... ``` syntax
        cleaned_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        logger.debug(f"Raw LLM output for date range parsing: {cleaned_text}")

        # Parse the JSON response
        try:
            parsed_range = json.loads(cleaned_text)
        except json.JSONDecodeError as json_err:
             logger.error(f"Failed JSON parsing from LLM date range response: {json_err}. Raw text: {cleaned_text}")
             return None

        # Validate the response structure
        if not isinstance(parsed_range, dict) or 'start_iso' not in parsed_range or 'end_iso' not in parsed_range:
            logger.error(f"LLM date range response has incorrect structure: {parsed_range}")
            return None

        # Basic validation of the ISO strings (more thorough parsing happens in handler)
        if not isinstance(parsed_range['start_iso'], str) or not isinstance(parsed_range['end_iso'], str):
             logger.error(f"LLM date range response values are not strings: {parsed_range}")
             return None

        # Optional: Try parsing here to catch immediate errors, though handler will do final parse
        try:
            dateutil_parser.isoparse(parsed_range['start_iso'])
            dateutil_parser.isoparse(parsed_range['end_iso'])
        except ValueError as parse_err:
            logger.error(f"LLM date range response contained invalid ISO string(s): {parse_err}. Range: {parsed_range}")
            return None

        logger.info(f"Successfully parsed date range from LLM: {parsed_range}")
        return parsed_range

    except Exception as e:
        logger.error(f"Error during LLM date range parsing for '{text_period}': {e}", exc_info=True)
        return None

async def classify_intent_and_extract_params(text: str) -> dict | None:
    """
    Uses LLM (Gemini) to classify user intent and extract relevant parameters.

    Intents: CALENDAR_SUMMARY, CALENDAR_CREATE, CALENDAR_DELETE, GENERAL_CHAT

    Args:
        text: The user's input message.

    Returns:
        A dictionary like:
        {'intent': 'CALENDAR_SUMMARY', 'parameters': {'time_period': 'next week'}}
        {'intent': 'CALENDAR_CREATE', 'parameters': {'event_description': 'meeting tuesday 3pm'}}
        {'intent': 'CALENDAR_DELETE', 'parameters': {'event_description': 'meeting tomorrow 2pm'}} # Extract description to find event
        {'intent': 'GENERAL_CHAT', 'parameters': {}}
        or None if classification fails.
    """
    if not gemini_model:
        logger.error("LLM not configured, cannot classify intent.")
        return None
    now = datetime.now(timezone.utc)
    current_time_str = now.isoformat()
    prompt = f"""
       Analyze the user's message based on the current time ({current_time_str}).
       Classify the user's primary intent into one of the following categories:
       - CALENDAR_SUMMARY: User wants to view or get a summary of their calendar events.
       - CALENDAR_CREATE: User wants to add a new event, meeting, appointment, or reminder.
       - CALENDAR_DELETE: User wants to remove, delete, or cancel an existing event.
       - GENERAL_CHAT: The message is conversational or doesn't fit other categories.

       If the intent is CALENDAR_SUMMARY, extract the time period description (e.g., "today", "next week").
       If the intent is CALENDAR_CREATE, extract the description of the event to be created.
       If the intent is CALENDAR_DELETE, extract a description of the event to be deleted (e.g., "meeting tomorrow 2pm", "dentist appointment").
       If the intent is GENERAL_CHAT, no parameters are needed.

       Output the result ONLY as a JSON object with two keys: 'intent' (string) and 'parameters' (object).
       For CALENDAR_SUMMARY, parameters: {{"time_period": "..."}}
       For CALENDAR_CREATE, parameters: {{"event_description": "..."}}
       For CALENDAR_DELETE, parameters: {{"event_description": "..."}}
       For GENERAL_CHAT, parameters: {{}}

       User Message: "{text}"

       JSON Output:
       """
    try:
        logger.info(f"Sending intent classification prompt to Gemini for: '{text[:100]}...'")
        response = await gemini_model.generate_content_async(prompt)

        if response.prompt_feedback and response.prompt_feedback.block_reason:
            logger.warning(f"LLM intent classification response blocked: {response.prompt_feedback.block_reason}")
            return None

        if not hasattr(response, 'text'):
            logger.warning("LLM response for intent classification missing 'text'.")
            return None

        cleaned_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        logger.debug(f"Raw LLM output for intent classification: {cleaned_text}")

        try:
            intent_data = json.loads(cleaned_text)
        except json.JSONDecodeError as json_err:
            logger.error(f"Failed JSON parsing from LLM intent classification: {json_err}. Raw text: {cleaned_text}")
            return None

        # --- MOVED VALIDATION INSIDE THE TRY BLOCK ---
        # Validate structure
        if not isinstance(intent_data, dict) or 'intent' not in intent_data or 'parameters' not in intent_data:
            logger.error(f"LLM intent classification response has incorrect structure: {intent_data}")
            return None  # Treat bad structure as failure

        # Validate intent value
        valid_intents = ["CALENDAR_SUMMARY", "CALENDAR_CREATE", "CALENDAR_DELETE", "GENERAL_CHAT"]
        intent_val = intent_data.get('intent')  # Get intent value safely
        if intent_val not in valid_intents:
            logger.warning(f"LLM returned unknown intent: {intent_val}. Defaulting to chat.")
            intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}}  # Reassign intent_data
            intent_val = 'GENERAL_CHAT'  # Update local variable too

        # Check parameters validity based on intent
        params = intent_data.get('parameters', {})
        if intent_val == "CALENDAR_SUMMARY" and not params.get("time_period"):
            logger.warning(f"LLM classified SUMMARY but missing time_period parameter. Defaulting to chat.")
            intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}}
        elif intent_val == "CALENDAR_CREATE" and not params.get("event_description"):
            logger.warning(f"LLM classified CREATE but missing event_description parameter. Defaulting to chat.")
            intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}}
        elif intent_val == "CALENDAR_DELETE" and not params.get("event_description"):
            logger.warning(f"LLM classified DELETE but missing event_description parameter. Defaulting to chat.")
            intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}}
        # --- END OF MOVED VALIDATION ---

        logger.info(f"Classified intent: {intent_data.get('intent')}, Params: {intent_data.get('parameters')}")
        return intent_data  # Return the potentially modified intent_data

    except Exception as e:
        # Catch any other exceptions during API call or processing
        logger.error(f"Error during LLM intent classification for '{text}': {e}", exc_info=True)
        return None  # Return None on any exception

# --- NEW FUNCTION: Delete Calendar Event ---
async def delete_calendar_event(user_id: int, event_id: str) -> tuple[bool, str]:
    """
    Deletes a specific event from the user's primary calendar.

    Args:
        user_id: The Telegram user ID.
        event_id: The Google Calendar event ID to delete.

    Returns:
        A tuple (success: bool, message: str).
    """
    service = build_google_calendar_service(user_id)
    if not service:
        if not is_user_connected(user_id):
             return False, "Authentication required. Please /connect_calendar first."
        else:
             return False, "Authentication failed. Please /disconnect_calendar and /connect_calendar again."

    logger.info(f"Attempting to delete event ID {event_id} for user {user_id}")
    try:
        service.events().delete(
            calendarId='primary',
            eventId=event_id
        ).execute()
        logger.info(f"Successfully deleted event ID {event_id} for user {user_id}.")
        return True, "Event successfully deleted."
    except HttpError as error:
        logger.error(f"An API error occurred deleting event {event_id} for user {user_id}: {error}")
        error_details = f"API Error: {error.resp.reason}"
        try:
            error_content = json.loads(error.content.decode())
            if 'error' in error_content and 'message' in error_content['error']:
                 error_details = error_content['error']['message']
        except: pass

        if error.resp.status == 404 or error.resp.status == 410: # Not Found or Gone (already deleted)
            logger.warning(f"Event {event_id} not found or already gone for user {user_id}.")
            return False, "Couldn't delete event. It might have been deleted already."
        elif error.resp.status == 401: # Unauthorized
             logger.warning(f"Credentials invalid deleting event for user {user_id}. Clearing token.")
             delete_user_token(user_id)
             return False, "Authentication failed. Please /connect_calendar again."
        else:
            return False, f"Failed to delete event. {error_details}"
    except Exception as e:
         logger.error(f"Unexpected error deleting event {event_id} for user {user_id}: {e}", exc_info=True)
         return False, "An unexpected error occurred while deleting the event."

def get_google_auth_flow():
    """Creates and returns a Google OAuth Flow object."""
    if not config.GOOGLE_CLIENT_SECRETS_FILE or not os.path.exists(config.GOOGLE_CLIENT_SECRETS_FILE):
        logger.error(f"Client secrets file missing or invalid: {config.GOOGLE_CLIENT_SECRETS_FILE}")
        return None
    try:
        return Flow.from_client_secrets_file(
            config.GOOGLE_CLIENT_SECRETS_FILE,
            scopes=config.GOOGLE_CALENDAR_SCOPES,
            redirect_uri=config.OAUTH_REDIRECT_URI
        )
    except FileNotFoundError:
        logger.error(f"Client secrets file not found: {config.GOOGLE_CLIENT_SECRETS_FILE}")
        return None
    except Exception as e:
        logger.error(f"Error creating OAuth flow: {e}")
        return None

def build_google_calendar_service(user_id):
    """Builds and returns an authorized Google Calendar service object for a user using Firestore."""
    if not USER_TOKENS_COLLECTION:
        logger.error("Firestore USER_TOKENS_COLLECTION not available.")
        return None

    creds = None
    creds_json = None # Variable to hold JSON string from DB

    # --- Get token from Firestore ---
    user_doc_id = str(user_id) # Firestore IDs are strings
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        snapshot = doc_ref.get()
        if snapshot.exists:
            creds_json = snapshot.get('credentials_json')
            logger.debug(f"Retrieved credentials from Firestore for user {user_id}")
        else:
            logger.debug(f"No credentials found in Firestore for user {user_id}")
            return None # Explicitly return None if no credentials found
    except Exception as e:
        logger.error(f"Error fetching token from Firestore for user {user_id}: {e}")
        return None # Treat DB error as connection failure
    # --- End Firestore fetch ---

    if creds_json:
        try:
            creds_info = json.loads(creds_json)
            creds = Credentials.from_authorized_user_info(creds_info, config.GOOGLE_CALENDAR_SCOPES)
        except json.JSONDecodeError:
             logger.error(f"Failed to parse stored credentials for user {user_id}")
             # Optionally delete corrupted data
             try: doc_ref.delete()
             except Exception: pass
             return None
        except Exception as e:
            logger.error(f"Failed to load credentials from info for user {user_id}: {e}")
            return None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info(f"Refreshing credentials for user {user_id}")
                creds.refresh(Request())
                # --- Save refreshed credentials back to Firestore ---
                store_user_credentials(user_id, creds) # Use the updated Firestore function
                # --- End Firestore save ---
                logger.info(f"Credentials refreshed successfully for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to refresh credentials for user {user_id}: {e}")
                 # --- Clear the token in Firestore if refresh fails ---
                try:
                    logger.warning(f"Clearing invalid token from Firestore for user {user_id} after refresh failure.")
                    doc_ref.delete()
                except Exception as db_e:
                    logger.error(f"Failed to delete token from Firestore for user {user_id}: {db_e}")
                 # --- End Firestore clear ---
                return None
        else:
            # No valid credentials or no refresh token, prompt re-auth
            if creds_json: # Only log warning if we actually found *something* initially
                 logger.warning(f"Stored credentials for user {user_id} are invalid or missing refresh token.")
                 # Optionally delete the invalid token here too
                 try: doc_ref.delete()
                 except Exception: pass
            else:
                 logger.info(f"No valid credentials needed refresh found for user {user_id} in Firestore.")
                 # This case is handled above where snapshot doesn't exist

            return None # Indicate user needs to authenticate

    # --- Build Google Calendar Service Client ---
    try:
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        logger.info(f"Google Calendar service built successfully for user {user_id}")
        return service
    except HttpError as error:
        logger.error(f"An API error occurred building Calendar service for user {user_id}: {error}")
        if error.resp.status == 401:
             logger.warning(f"Credentials invalid for user {user_id} during service build. Clearing token from Firestore.")
             # --- Firestore Token Clearing ---
             try:
                 doc_ref.delete()
             except Exception as db_e:
                 logger.error(f"Failed to delete token from Firestore for user {user_id}: {db_e}")
             # --- End Firestore Clearing ---
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred building Calendar service for user {user_id}: {e}")
        return None

async def get_calendar_events(user_id, time_min=None, time_max=None, max_results=10):
    """Fetches upcoming events from the user's calendar using Firestore."""
    service = build_google_calendar_service(user_id)
    if not service:
        # Check connection status *after* attempting to build service
        # to see if token was cleared due to invalidity during build
        if not is_user_connected(user_id):
            logger.info(f"User {user_id} needs to connect to get events.")
        else:
            # This state means token existed but was invalid/cleared during build_google_calendar_service
            logger.warning(f"Service build failed for user {user_id}, likely invalid token cleared. Cannot get events.")
        return None # Indicate authentication needed or failed

    now = datetime.now(timezone.utc)
    if time_min is None:
        time_min_dt = now
    else:
        time_min_dt = time_min.astimezone(timezone.utc) # Ensure timezone aware

    if time_max is None:
        start_of_period = time_min_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        time_max_dt = start_of_period + timedelta(days=1)
    else:
        time_max_dt = time_max.astimezone(timezone.utc)

    time_min_iso = time_min_dt.isoformat()
    time_max_iso = time_max_dt.isoformat()

    logger.info(f"Fetching events for user {user_id} from {time_min_iso} to {time_max_iso}")

    try:
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min_iso,
            timeMax=time_max_iso,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        return events
    except HttpError as error:
        logger.error(f"An API error occurred fetching events for user {user_id}: {error}")
        if error.resp.status == 401: # Unauthorized
             logger.warning(f"Credentials invalid for user {user_id} fetching events. Clearing token from Firestore.")
             # --- Firestore Token Clearing ---
             user_doc_id = str(user_id)
             doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
             try:
                 doc_ref.delete()
             except Exception as db_e:
                 logger.error(f"Failed to delete token from Firestore for user {user_id}: {db_e}")
             # --- End Firestore Clearing ---
        return None # Indicate error or re-auth needed
    except Exception as e:
        logger.error(f"Unexpected error fetching events for user {user_id}: {e}")
        return None

async def create_calendar_event(user_id, event_details):
    """Creates an event in the user's primary calendar using Firestore."""
    service = build_google_calendar_service(user_id)
    if not service:
        if not is_user_connected(user_id):
             logger.info(f"User {user_id} needs to connect before creating event.")
             return False, "Authentication required. Please /connect_calendar first."
        else:
             # Token existed but was invalid/cleared during build
             logger.warning(f"Service build failed for user {user_id}, likely invalid token cleared. Cannot create event.")
             return False, "Authentication failed. Please /disconnect_calendar and /connect_calendar again."

    logger.info(f"Attempting to create event for user {user_id}: {event_details}")
    try:
        event = service.events().insert(
            calendarId='primary',
            body=event_details
        ).execute()
        logger.info(f"Event created successfully for user {user_id}: {event.get('htmlLink')}")
        return True, f"Event created: {event.get('summary')} ({event.get('htmlLink')})"
    except HttpError as error:
        logger.error(f"An API error occurred creating event for user {user_id}: {error}")
        error_details = error.resp.reason
        try: # Try to get more details from error content
            error_content = json.loads(error.content.decode())
            if 'error' in error_content and 'message' in error_content['error']:
                 error_details = error_content['error']['message']
        except:
            pass # Ignore if parsing fails

        if error.resp.status == 401:
             logger.warning(f"Credentials invalid for user {user_id} creating event. Clearing token from Firestore.")
             # --- Firestore Token Clearing ---
             user_doc_id = str(user_id)
             doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
             try:
                 doc_ref.delete()
             except Exception as db_e:
                 logger.error(f"Failed to delete token from Firestore for user {user_id}: {db_e}")
             # --- End Firestore Clearing ---
             return False, "Authentication failed. Please /connect_calendar again."
        return False, f"Failed to create event. API Error: {error_details}"
    except Exception as e:
         logger.error(f"Unexpected error creating event for user {user_id}: {e}")
         return False, "An unexpected error occurred while creating the event."


async def get_llm_chat_response(prompt: str) -> str:
    """Gets a chat response from the configured LLM (Gemini)."""
    if not gemini_model:
        return "LLM is not configured."
    try:
        logger.info(f"Sending prompt to Gemini: {prompt[:100]}...")
        response = await gemini_model.generate_content_async(prompt) # Using async version
        logger.info("Received response from Gemini.")
        # Basic safety check
        if response.prompt_feedback and response.prompt_feedback.block_reason:
             logger.warning(f"LLM response blocked: {response.prompt_feedback.block_reason}")
             return "I cannot respond to that request due to safety settings."
        # Handle potential lack of 'text' attribute gracefully
        if hasattr(response, 'text'):
            return response.text
        else:
            logger.warning(f"LLM response did not contain 'text'. Parts: {response.parts}")
            # Attempt to construct text from parts if available
            try:
                 return "".join(part.text for part in response.parts)
            except Exception:
                 logger.error("Could not extract text from LLM response parts.")
                 return "Sorry, I received an unusual response from the AI."
    except Exception as e:
        logger.error(f"Error calling LLM: {e}")
        return "Sorry, I encountered an error trying to process that."

async def extract_event_details_llm(text: str) -> dict | None:
    """Uses LLM (Gemini) to extract event details from text."""
    if not gemini_model:
        logger.error("LLM not configured, cannot extract event details.")
        return None

    prompt = f"""
    Extract calendar event details from the following text. Provide the output as a JSON object with keys: 'summary', 'start_time', 'end_time', 'description', 'location'.
    - The current date is {datetime.now().strftime('%Y-%m-%d %A')}. Interpret relative dates like "tomorrow", "next Tuesday at 3pm" based on this.
    - Output dates and times in ISO 8601 format (YYYY-MM-DDTHH:MM:SS). You MUST determine the correct timezone offset based on common interpretations or specify UTC (e.g., +00:00 or Z) if unsure. Example: 2024-05-15T14:00:00-07:00 or 2024-05-16T09:00:00Z.
    - If only a start time is given, assume a 1-hour duration for the end time unless otherwise specified (e.g., 'meeting 2pm to 4pm').
    - If any detail is missing, omit the key or set its value to null in the JSON.
    - Prioritize extracting specific times and dates accurately. If the text is ambiguous, make a reasonable assumption but ensure the format is correct.

    Text: "{text}"

    JSON Output:
    """
    try:
        logger.info("Sending event extraction prompt to Gemini...")
        response = await gemini_model.generate_content_async(prompt)
        logger.info("Received event extraction response from Gemini.")

        if response.prompt_feedback and response.prompt_feedback.block_reason:
             logger.warning(f"LLM event extraction response blocked: {response.prompt_feedback.block_reason}")
             return None

        # Clean potential markdown ```json ... ``` syntax
        if not hasattr(response, 'text'):
             logger.warning("LLM response for event extraction missing 'text'.")
             return None # Cannot proceed without text
        cleaned_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()

        logger.debug(f"Raw LLM output for event extraction: {cleaned_text}")
        # Add robustness for potential parsing errors
        try:
            event_details = json.loads(cleaned_text)
        except json.JSONDecodeError as json_err:
             logger.error(f"Failed JSON parsing from LLM event extraction: {json_err}. Raw text: {cleaned_text}")
             # Maybe try a fallback LLM call or regex here if critical
             return None

        # Basic validation of critical fields
        if not isinstance(event_details, dict) or not event_details.get('summary') or not event_details.get('start_time'):
            logger.warning(f"LLM extraction missing critical fields (summary/start_time). Parsed: {event_details}")
            # Don't return partially valid data if core parts are missing
            return None

        logger.info(f"Parsed event details from LLM: {event_details}")
        return event_details
    except Exception as e:
        logger.error(f"Error during LLM event extraction: {e}", exc_info=True)
        return None

# --- OAuth Flow Functions using Firestore ---

def generate_oauth_state(user_id):
    """Generates a unique state token and stores the user_id mapping in Firestore."""
    if not OAUTH_STATES_COLLECTION:
        logger.error("Firestore OAUTH_STATES_COLLECTION not available.")
        return None
    state = str(uuid.uuid4())
    doc_ref = OAUTH_STATES_COLLECTION.document(state) # State is the document ID
    try:
        doc_ref.set({
            'user_id': user_id,
            'created_at': firestore.SERVER_TIMESTAMP # Use Firestore server timestamp
        })
        logger.info(f"Stored OAuth state {state} for user {user_id} in Firestore")
        return state
    except Exception as e:
        logger.error(f"Failed to store OAuth state in Firestore for user {user_id}: {e}")
        return None

@firestore.transactional
def _verify_and_delete_state(transaction, state_doc_ref):
    """Transactional helper for verify_oauth_state."""
    try:
        snapshot = state_doc_ref.get(transaction=transaction)
        if snapshot.exists:
            user_id = snapshot.get('user_id')
            transaction.delete(state_doc_ref) # Delete within the transaction
            return user_id
        else:
            return None
    except Exception as e:
        logger.error(f"Error within Firestore transaction for state verification: {e}")
        # Propagate exception to make transaction fail
        raise

def verify_oauth_state(state):
    """Verifies the state token from Firestore and returns the associated user_id, consuming the state."""
    if not OAUTH_STATES_COLLECTION:
        logger.error("Firestore OAUTH_STATES_COLLECTION not available.")
        return None

    state_doc_ref = OAUTH_STATES_COLLECTION.document(state)
    transaction = db.transaction()
    try:
        user_id = _verify_and_delete_state(transaction, state_doc_ref)
        if user_id:
            logger.info(f"Verified and consumed OAuth state {state} for user {user_id} from Firestore")
            return user_id
        else:
            logger.warning(f"Invalid or expired OAuth state received from Google (not found in Firestore): {state}")
            return None
    except Exception as e:
        # Catch exception raised from transactional function or transaction itself
        logger.error(f"Error verifying OAuth state {state} in Firestore transaction: {e}")
        return None

def store_user_credentials(user_id, credentials):
    """Stores or updates the user's credentials JSON in Firestore."""
    if not USER_TOKENS_COLLECTION:
        logger.error("Firestore USER_TOKENS_COLLECTION not available.")
        return False # Indicate failure

    creds_json = credentials.to_json()
    user_doc_id = str(user_id) # Firestore IDs are strings
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        doc_ref.set({
            'credentials_json': creds_json,
            'updated_at': firestore.SERVER_TIMESTAMP
        }, merge=False) # Use set without merge to overwrite completely
        logger.info(f"Stored/Updated credentials in Firestore for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to store credentials in Firestore for user {user_id}: {e}")
        return False


# --- Status/Delete Functions using Firestore ---

def is_user_connected(user_id):
    """Checks if a token document exists for the user in Firestore."""
    if not USER_TOKENS_COLLECTION: return False
    user_doc_id = str(user_id)
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        # Use get() with field_paths=[''] or a known small field to check existence efficiently
        snapshot = doc_ref.get(field_paths=['updated_at']) # Only get one field
        exists = snapshot.exists
        logger.debug(f"Firestore existence check for user {user_id}: {exists}")
        return exists
    except Exception as e:
        logger.error(f"Error checking token existence in Firestore for user {user_id}: {e}")
        return False # Assume not connected on error

def delete_user_token(user_id):
    """Deletes the token document for a given user_id from Firestore."""
    if not USER_TOKENS_COLLECTION: return False
    user_doc_id = str(user_id)
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        delete_result = doc_ref.delete()
        # delete() returns a WriteResult, doesn't raise error if doc doesn't exist.
        logger.info(f"Attempted deletion of token from Firestore for user {user_id}. Result time: {delete_result.update_time}")
        return True # Assume success unless exception
    except Exception as e:
        logger.error(f"Failed to delete token from Firestore for user {user_id}: {e}")
        return False

# --- NEW FUNCTION: Find Matching Event using LLM ---
async def find_event_match_llm(user_request: str, candidate_events: list) -> dict | None:
    """
    Uses LLM (Gemini) to determine which candidate event best matches the user's request.

    Args:
        user_request: The user's original text describing the event to delete/modify.
        candidate_events: A list of event objects fetched from Google Calendar.

    Returns:
        A dictionary indicating the match result, e.g.:
        {'match_type': 'SINGLE', 'event_index': 0} # Index corresponds to candidate_events list
        {'match_type': 'MULTIPLE', 'indices': [0, 2]} # Optional: indices if LLM can identify multiple possibles
        {'match_type': 'NONE'}
        or None if the LLM call fails.
    """
    if not gemini_model:
        logger.error("LLM not configured, cannot match event.")
        return None
    if not candidate_events:
        logger.info("No candidate events provided to LLM for matching.")
        return {'match_type': 'NONE'} # No events to match against

    now = datetime.now(timezone.utc)
    current_time_str = now.isoformat()

    # Format candidate events for the prompt
    formatted_events = []
    for i, event in enumerate(candidate_events):
        summary = event.get('summary', 'No Title')
        start_str = event['start'].get('dateTime', event['start'].get('date'))
        # Basic time formatting for prompt clarity
        try:
            if 'date' in event['start']: time_disp = dateutil_parser.isoparse(start_str).strftime('%Y-%m-%d (All day)')
            else: time_disp = dateutil_parser.isoparse(start_str).strftime('%Y-%m-%d %H:%M %Z')
        except Exception: time_disp = start_str # Fallback
        formatted_events.append(f"{i}: Title='{summary}', Time='{time_disp}'")

    events_list_str = "\n".join(formatted_events)

    prompt = f"""
    Current time is {current_time_str}.
    The user wants to interact with (likely delete) an event described as: "{user_request}"

    Here is a list of relevant calendar events fetched from their calendar:
    --- Start Event List ---
    {events_list_str}
    --- End Event List ---

    Analyze the user's request and the event list. Determine which event, specified by its index number (0, 1, 2, ...), is the MOST likely match for the user's request. Consider the event title, time, and any other details mentioned by the user relative to the current time and the event times.

    Respond ONLY with a JSON object indicating the result:
    - If you find exactly ONE clear match: {{"match_type": "SINGLE", "event_index": <index_number>}}
    - If you are unsure or find MULTIPLE plausible matches: {{"match_type": "MULTIPLE"}} (You don't need to list the indices for MULTIPLE)
    - If NONE of the events seem to match the user's request: {{"match_type": "NONE"}}

    JSON Output:
    """
    try:
        logger.info(f"Sending event matching prompt to Gemini for request: '{user_request[:50]}...' with {len(candidate_events)} candidates.")
        response = await gemini_model.generate_content_async(prompt)

        if response.prompt_feedback and response.prompt_feedback.block_reason:
             logger.warning(f"LLM event matching response blocked: {response.prompt_feedback.block_reason}")
             return None # Treat blocking as failure

        if not hasattr(response, 'text'):
             logger.warning("LLM response for event matching missing 'text'.")
             return None

        cleaned_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        logger.debug(f"Raw LLM output for event matching: {cleaned_text}")

        try:
            match_result = json.loads(cleaned_text)
        except json.JSONDecodeError as json_err:
             logger.error(f"Failed JSON parsing from LLM event matching: {json_err}. Raw text: {cleaned_text}")
             return None

        # Validate the result structure
        match_type = match_result.get('match_type')
        if match_type not in ['SINGLE', 'MULTIPLE', 'NONE']:
            logger.error(f"LLM event matching returned invalid match_type: {match_type}")
            return None
        if match_type == 'SINGLE' and 'event_index' not in match_result:
            logger.error(f"LLM event matching returned SINGLE match without event_index: {match_result}")
            return None
        if match_type == 'SINGLE':
            try:
                # Ensure index is valid for the original list
                event_idx = int(match_result['event_index'])
                if not (0 <= event_idx < len(candidate_events)):
                     logger.error(f"LLM returned invalid event_index {event_idx} for candidate list size {len(candidate_events)}")
                     return {'match_type': 'NONE'} # Treat invalid index as no match
            except (ValueError, TypeError):
                 logger.error(f"LLM returned non-integer event_index: {match_result.get('event_index')}")
                 return {'match_type': 'NONE'} # Treat invalid index as no match


        logger.info(f"LLM event matching result: {match_result}")
        return match_result

    except Exception as e:
        logger.error(f"Error during LLM event matching for '{user_request}': {e}", exc_info=True)
        return None
