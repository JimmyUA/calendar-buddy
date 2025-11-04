import asyncio
import logging
from google.cloud import firestore
import config

logger = logging.getLogger(__name__)

db = config.FIRESTORE_DB
USER_TOKENS_COLLECTION = db.collection('user_tokens') if db else None


async def store_user_credentials(user_id: int, credentials) -> bool:
    """Stores or updates the user's Google credentials JSON in Firestore."""
    if not USER_TOKENS_COLLECTION:
        logger.error("Firestore USER_TOKENS_COLLECTION not available.")
        return False
    creds_json = credentials.to_json()
    user_doc_id = str(user_id)
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        await asyncio.to_thread(
            doc_ref.set,
            {'credentials_json': creds_json, 'updated_at': firestore.SERVER_TIMESTAMP},
            merge=False,
        )
        logger.info(f"Stored/Updated credentials in Firestore for user {user_id}")
        return True
    except Exception as e:
        logger.error(
            f"Failed to store credentials in Firestore for user {user_id}: {e}",
            exc_info=True,
        )
        return False


async def delete_user_token(user_id: int) -> bool:
    """Deletes the token document for a given user_id from Firestore."""
    if not USER_TOKENS_COLLECTION:
        return False
    user_doc_id = str(user_id)
    doc_ref = USER_TOKENS_COLLECTION.document(user_doc_id)
    try:
        await asyncio.to_thread(doc_ref.delete)
        logger.info(f"Attempted deletion of token from Firestore for user {user_id}.")
        return True
    except Exception as e:
        logger.error(
            f"Failed to delete token from Firestore for user {user_id}: {e}",
            exc_info=True,
        )
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
        return False
