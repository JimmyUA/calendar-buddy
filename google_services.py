# google_services.py
import asyncio
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
from services import pending as pending_service, preferences as prefs_service

import config # Import our config
from models import CalendarAccessRequest # Import the Pydantic model

logger = logging.getLogger(__name__)

# --- Firestore Client and Collections ---
db = config.FIRESTORE_DB
OAUTH_STATES_COLLECTION = db.collection('oauth_states') if db else None
USER_TOKENS_COLLECTION = db.collection('user_tokens') if db else None
USER_PREFS_COLLECTION = db.collection(config.FS_COLLECTION_PREFS) if db else None
PENDING_EVENTS_COLLECTION = db.collection(config.FS_COLLECTION_PENDING_EVENTS) if db else None
PENDING_DELETIONS_COLLECTION = db.collection(config.FS_COLLECTION_PENDING_DELETIONS) if db else None
CALENDAR_ACCESS_REQUESTS_COLLECTION = db.collection(config.FS_COLLECTION_CALENDAR_ACCESS_REQUESTS) if db else None
GROCERY_SHARE_REQUESTS_COLLECTION = db.collection(config.FS_COLLECTION_GROCERY_SHARE_REQUESTS) if db else None


# === Pending Event Management (Firestore) ===

async def add_pending_event(user_id: int, event_data: dict) -> bool:
    """Stores event_data in Firestore for later confirmation."""
    return await pending_service.add_pending_event(user_id, event_data)

async def get_pending_event(user_id: int) -> dict | None:
    """Retrieves pending event data for a user from Firestore."""
    return await pending_service.get_pending_event(user_id)

async def delete_pending_event(user_id: int) -> bool:
    """Deletes a pending event document for a user from Firestore."""
    return await pending_service.delete_pending_event(user_id)

# === Pending Deletion Management (Firestore) ===

async def add_pending_deletion(user_id: int, deletion_data: dict) -> bool:
    """Stores deletion_data in Firestore for later confirmation."""
    return await pending_service.add_pending_deletion(user_id, deletion_data)

async def get_pending_deletion(user_id: int) -> dict | None:
    """Retrieves pending deletion data for a user from Firestore."""
    return await pending_service.get_pending_deletion(user_id)

async def delete_pending_deletion(user_id: int) -> bool:
    """Deletes a pending deletion document for a user from Firestore."""
    return await pending_service.delete_pending_deletion(user_id)

# === Google Authentication & Firestore Persistence ===

# --- Timezone Functions (Using NEW Collection) ---
async def set_user_timezone(user_id: int, timezone_str: str) -> bool:
    """Stores the user's validated IANA timezone string in Firestore."""
    return await prefs_service.set_user_timezone(user_id, timezone_str)

async def get_user_timezone_str(user_id: int) -> str | None:
    """Retrieves the user's timezone string from Firestore."""
    return await prefs_service.get_user_timezone_str(user_id)



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

async def generate_oauth_state(user_id: int) -> str | None:
    """Generates a unique state token and stores the mapping in Firestore."""
    if not OAUTH_STATES_COLLECTION: logger.error("Firestore OAUTH_STATES_COLLECTION not available."); return None
    state = str(uuid.uuid4())
    doc_ref = OAUTH_STATES_COLLECTION.document(state) # type: ignore
    try:
        # Firestore operations are blocking
        await asyncio.to_thread(doc_ref.set, {'user_id': user_id, 'created_at': firestore.SERVER_TIMESTAMP})
        # Note: write_result.update_time is not available when using to_thread this way
        logger.info(f"Successfully wrote state {state} for user {user_id} to Firestore.")
        return state
    except Exception as e:
        logger.error(f"Firestore write FAILED for state {state}, user {user_id}: {e}", exc_info=True)
        return None

@firestore.transactional
def _verify_and_delete_state(transaction, state_doc_ref):
    """Transactional helper for verify_oauth_state."""
    # This function is called by verify_oauth_state, which is synchronous.
    # If verify_oauth_state becomes async, then this can use asyncio.to_thread.
    # For now, keeping it synchronous as it's part of a synchronous transaction flow.
    try:
        snapshot = state_doc_ref.get(transaction=transaction) # This is a transactional read
        if snapshot.exists:
            user_id = snapshot.get('user_id') # type: ignore
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


async def store_user_credentials(user_id: int, credentials) -> bool:
    """Stores or updates the user's Google credentials JSON in Firestore."""
    if not USER_TOKENS_COLLECTION: logger.error("Firestore USER_TOKENS_COLLECTION not available."); return False
    creds_json = credentials.to_json()
    user_doc_id = str(user_id)
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        await asyncio.to_thread(doc_ref.set, {'credentials_json': creds_json, 'updated_at': firestore.SERVER_TIMESTAMP}, merge=False)
        logger.info(f"Stored/Updated credentials in Firestore for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to store credentials in Firestore for user {user_id}: {e}", exc_info=True)
        return False

async def is_user_connected(user_id: int) -> bool:
    """Checks if a token document exists for the user in Firestore."""
    if not USER_TOKENS_COLLECTION: return False
    user_doc_id = str(user_id)
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        # Efficient check for existence
        snapshot = await asyncio.to_thread(doc_ref.get, field_paths=['updated_at'])
        return snapshot.exists
    except Exception as e:
        logger.error(f"Error checking token existence in Firestore for user {user_id}: {e}", exc_info=True)
        return False # Assume not connected on error

async def delete_user_token(user_id: int) -> bool:
    """Deletes the token document for a given user_id from Firestore."""
    if not USER_TOKENS_COLLECTION: return False
    user_doc_id = str(user_id)
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        await asyncio.to_thread(doc_ref.delete)
        # delete_result.update_time not available here
        logger.info(f"Attempted deletion of token from Firestore for user {user_id}.")
        return True # Assume success unless exception
    except Exception as e:
        logger.error(f"Failed to delete token from Firestore for user {user_id}: {e}", exc_info=True)
        return False


# === Chat History Management ===

async def get_chat_history(user_id: int, history_type: str) -> list[dict]:
    """
    Retrieves chat history from Firestore for a given user and history type.
    """
    if not db:
        logger.error("GS: Firestore client (db) is not available for get_chat_history.")
        return []

    collection_name = None
    if history_type == "lc":
        collection_name = config.FS_COLLECTION_LC_CHAT_HISTORIES
    elif history_type == "general":
        collection_name = config.FS_COLLECTION_GENERAL_CHAT_HISTORIES
    else:
        logger.error(f"GS: Unknown history_type '{history_type}' for get_chat_history.")
        return []

    if not collection_name: # Should be caught by the else above, but as a safeguard
        logger.error(f"GS: Collection name could not be determined for history_type '{history_type}'.")
        return []

    try:
        user_doc_ref = db.collection(collection_name).document(str(user_id))
        messages_ref = user_doc_ref.collection('messages')

        query = messages_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(config.MAX_HISTORY_MESSAGES)
        snapshots = await asyncio.to_thread(list, query.stream()) # type: ignore

        if not snapshots:
            logger.debug(f"GS: No chat history found for user {user_id}, type '{history_type}'.")
            return []

        messages = []
        for doc in snapshots:
            message_data = doc.to_dict()
            if message_data and 'role' in message_data and 'content' in message_data:
                messages.append({
                    'role': message_data['role'],
                    'content': message_data['content']
                })
            else:
                logger.warning(f"GS: Malformed message document found for user {user_id}, type '{history_type}', doc ID {doc.id}")

        # Messages are fetched in descending order, reverse to get ascending for chat context
        messages.reverse()
        logger.info(f"GS: Retrieved {len(messages)} messages for user {user_id}, type '{history_type}'.")
        return messages

    except Exception as e:
        logger.error(f"GS: Error fetching chat history for user {user_id}, type '{history_type}': {e}", exc_info=True)
        return []

async def add_chat_message(user_id: int, role: str, content: str, history_type: str) -> bool:
    """
    Adds a chat message to Firestore and trims old messages if history exceeds max length.
    """
    if not db:
        logger.error("GS: Firestore client (db) is not available for add_chat_message.")
        return False

    collection_name = None
    if history_type == "lc":
        collection_name = config.FS_COLLECTION_LC_CHAT_HISTORIES
    elif history_type == "general":
        collection_name = config.FS_COLLECTION_GENERAL_CHAT_HISTORIES
    else:
        logger.error(f"GS: Unknown history_type '{history_type}' for add_chat_message.")
        return False
    
    if not collection_name:
        logger.error(f"GS: Collection name could not be determined for history_type '{history_type}' in add_chat_message.")
        return False

    try:
        user_doc_ref = db.collection(collection_name).document(str(user_id))
        messages_ref = user_doc_ref.collection('messages')

        new_message = {
            'role': role,
            'content': content,
            'timestamp': firestore.SERVER_TIMESTAMP
        }
        # Add the new message
        await asyncio.to_thread(messages_ref.add, new_message) # add() generates a unique ID
        logger.info(f"GS: Added chat message for user {user_id}, type '{history_type}'.")

        # History Trimming Logic
        # This part is run sequentially after adding the message.
        # For higher consistency, a transaction could be used for add + trim,
        # but that adds complexity. Sequential is generally fine for chat logs.

        # Get current count of messages
        # Note: Counting all documents in a collection can be slow for very large collections.
        # Firestore recommends against this for client-side code if performance is critical.
        # However, for a limited subcollection of chat messages, it should be acceptable.
        # Consider alternative strategies for very high-traffic systems (e.g., a counter field).
        
        # Re-fetch to count. This is not ideal for performance.
        # A more optimized way would be to use a transaction to add and then check count,
        # or maintain a counter document. For simplicity now, we'll re-query.
        
        # Get all message documents to count them.
        all_messages_query = messages_ref.order_by('timestamp', direction=firestore.Query.ASCENDING)
        all_message_snapshots = await asyncio.to_thread(list, all_messages_query.stream()) # type: ignore
        current_count = len(all_message_snapshots)

        if current_count > config.MAX_HISTORY_MESSAGES:
            num_to_delete = current_count - config.MAX_HISTORY_MESSAGES
            logger.info(f"GS: Chat history for user {user_id}, type '{history_type}' exceeds limit ({current_count}/{config.MAX_HISTORY_MESSAGES}). Deleting {num_to_delete} oldest messages.")

            # The snapshots are already ordered by timestamp ASC, so the first `num_to_delete` are the oldest.
            docs_to_delete = all_message_snapshots[:num_to_delete]

            # Deleting documents one by one. Batched writes would be more efficient.
            # For simplicity, individual deletes are used here.
            # Firestore batch size limit is 500 operations.
            batch = db.batch()
            deleted_count = 0
            for doc_snapshot in docs_to_delete:
                batch.delete(doc_snapshot.reference)
                deleted_count +=1
                if deleted_count % 499 == 0: # Commit batch if it's getting full (Firestore limit 500)
                    logger.info(f"GS: Committing a batch of {deleted_count} message deletions for user {user_id}, type '{history_type}'.")
                    await asyncio.to_thread(batch.commit)
                    batch = db.batch() # Start a new batch
            
            if deleted_count % 499 != 0: # Commit any remaining operations in the batch
                 await asyncio.to_thread(batch.commit)
            
            logger.info(f"GS: Successfully deleted {deleted_count} oldest messages for user {user_id}, type '{history_type}'.")
        return True

    except Exception as e:
        logger.error(f"GS: Error adding/trimming chat message for user {user_id}, type '{history_type}': {e}", exc_info=True)
        return False

# === Calendar Access Requests ===

async def add_calendar_access_request(
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
        doc_ref_new = CALENDAR_ACCESS_REQUESTS_COLLECTION.document() # type: ignore
        await asyncio.to_thread(doc_ref_new.set, data_to_store)

        logger.info(f"Calendar access request from {requester_id} to {target_user_id} stored with ID: {doc_ref_new.id}")
        return doc_ref_new.id
    except Exception as e:
        logger.error(f"Failed to add calendar access request from {requester_id} to {target_user_id}: {e}", exc_info=True)
        return None

async def get_calendar_access_request(request_id: str) -> dict | None:
    """
    Retrieves a specific calendar access request document from Firestore.
    """
    if not CALENDAR_ACCESS_REQUESTS_COLLECTION:
        logger.error("Firestore CALENDAR_ACCESS_REQUESTS_COLLECTION unavailable for get_calendar_access_request.")
        return None
    try:
        doc_ref = CALENDAR_ACCESS_REQUESTS_COLLECTION.document(request_id)
        snapshot = await asyncio.to_thread(doc_ref.get)
        if snapshot.exists:
            request_data = snapshot.to_dict() # type: ignore
            logger.info(f"Retrieved calendar access request with ID: {request_id}")
            return request_data
        else:
            logger.warning(f"Calendar access request with ID: {request_id} not found.")
            return None
    except Exception as e:
        logger.error(f"Error fetching calendar access request {request_id}: {e}", exc_info=True)
        return None

async def update_calendar_access_request_status(request_id: str, status: str) -> bool:
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
        await asyncio.to_thread(doc_ref.update, update_data)
        logger.info(f"Updated calendar access request {request_id} to status '{status}'.")
        return True
    except NotFound:
        logger.warning(f"Calendar access request {request_id} not found during status update.")
        return False
    except Exception as e:
        logger.error(f"Failed to update status for calendar access request {request_id}: {e}", exc_info=True)
        return False

# === Grocery List Share Requests ===

async def add_grocery_share_request(
    requester_id: str,
    requester_name: str,
    target_user_id: str,
) -> str | None:
    """Creates a new grocery list share request document."""
    if not GROCERY_SHARE_REQUESTS_COLLECTION:
        logger.error("Firestore GROCERY_SHARE_REQUESTS_COLLECTION unavailable.")
        return None

    try:
        request_data = {
            "requester_id": requester_id,
            "requester_name": requester_name,
            "target_user_id": target_user_id,
            "status": "pending",
            "request_timestamp": firestore.SERVER_TIMESTAMP,
        }
        doc_ref_new = GROCERY_SHARE_REQUESTS_COLLECTION.document()  # type: ignore
        await asyncio.to_thread(doc_ref_new.set, request_data)
        logger.info(
            f"Grocery share request from {requester_id} to {target_user_id} stored with ID: {doc_ref_new.id}"
        )
        return doc_ref_new.id
    except Exception as e:
        logger.error(
            f"Failed to add grocery share request from {requester_id} to {target_user_id}: {e}",
            exc_info=True,
        )
        return None


async def get_grocery_share_request(request_id: str) -> dict | None:
    """Retrieves a grocery list share request document."""
    if not GROCERY_SHARE_REQUESTS_COLLECTION:
        logger.error(
            "Firestore GROCERY_SHARE_REQUESTS_COLLECTION unavailable for get_grocery_share_request."
        )
        return None
    try:
        doc_ref = GROCERY_SHARE_REQUESTS_COLLECTION.document(request_id)
        snapshot = await asyncio.to_thread(doc_ref.get)
        if snapshot.exists:
            request_data = snapshot.to_dict()  # type: ignore
            logger.info(f"Retrieved grocery share request with ID: {request_id}")
            return request_data
        else:
            logger.warning(f"Grocery share request with ID: {request_id} not found.")
            return None
    except Exception as e:
        logger.error(f"Error fetching grocery share request {request_id}: {e}", exc_info=True)
        return None


async def update_grocery_share_request_status(request_id: str, status: str) -> bool:
    """Updates the status of a grocery list share request."""
    if not GROCERY_SHARE_REQUESTS_COLLECTION:
        logger.error(
            "Firestore GROCERY_SHARE_REQUESTS_COLLECTION unavailable for update_grocery_share_request_status."
        )
        return False
    try:
        doc_ref = GROCERY_SHARE_REQUESTS_COLLECTION.document(request_id)
        update_data = {"status": status, "response_timestamp": firestore.SERVER_TIMESTAMP}
        await asyncio.to_thread(doc_ref.update, update_data)
        logger.info(f"Updated grocery share request {request_id} to status '{status}'.")
        return True
    except NotFound:
        logger.warning(f"Grocery share request {request_id} not found during status update.")
        return False
    except Exception as e:
        logger.error(
            f"Failed to update status for grocery share request {request_id}: {e}",
            exc_info=True,
        )
        return False