import asyncio
import logging
from google.cloud import firestore
import config

logger = logging.getLogger(__name__)

# Firestore collections
_db = config.FIRESTORE_DB
PENDING_EVENTS_COLLECTION = _db.collection(config.FS_COLLECTION_PENDING_EVENTS) if _db else None
PENDING_DELETIONS_COLLECTION = _db.collection(config.FS_COLLECTION_PENDING_DELETIONS) if _db else None

async def add_pending_event(user_id: int, event_data: dict) -> bool:
    if not PENDING_EVENTS_COLLECTION:
        logger.error("Firestore PENDING_EVENTS_COLLECTION unavailable for adding pending event.")
        return False
    doc_ref = PENDING_EVENTS_COLLECTION.document(str(user_id))
    try:
        await asyncio.to_thread(
            doc_ref.set,
            {"event_data": event_data, "created_at": firestore.SERVER_TIMESTAMP},
        )
        logger.info(f"Stored pending event for user {user_id} in '{config.FS_COLLECTION_PENDING_EVENTS}'")
        return True
    except Exception as e:
        logger.error(f"Failed to store pending event for user {user_id}: {e}", exc_info=True)
        return False

async def get_pending_event(user_id: int) -> dict | None:
    if not PENDING_EVENTS_COLLECTION:
        logger.error("Firestore PENDING_EVENTS_COLLECTION unavailable for getting pending event.")
        return None
    doc_ref = PENDING_EVENTS_COLLECTION.document(str(user_id))
    try:
        snapshot = await asyncio.to_thread(doc_ref.get)
        if snapshot.exists:
            data = snapshot.to_dict()  # type: ignore
            logger.debug(f"Retrieved pending event for user {user_id}.")
            return data.get("event_data")
        return None
    except Exception as e:
        logger.error(f"Error fetching pending event for user {user_id}: {e}", exc_info=True)
        return None

async def delete_pending_event(user_id: int) -> bool:
    if not PENDING_EVENTS_COLLECTION:
        logger.error("Firestore PENDING_EVENTS_COLLECTION unavailable for deleting pending event.")
        return False
    doc_ref = PENDING_EVENTS_COLLECTION.document(str(user_id))
    try:
        await asyncio.to_thread(doc_ref.delete)
        logger.info(f"Deleted pending event for user {user_id} (if it existed).")
        return True
    except Exception as e:
        logger.error(f"Failed to delete pending event for user {user_id}: {e}", exc_info=True)
        return False

async def add_pending_deletion(user_id: int, deletion_data: dict) -> bool:
    if not PENDING_DELETIONS_COLLECTION:
        logger.error("Firestore PENDING_DELETIONS_COLLECTION unavailable for adding pending deletion.")
        return False
    doc_ref = PENDING_DELETIONS_COLLECTION.document(str(user_id))
    try:
        await asyncio.to_thread(
            doc_ref.set,
            {"deletion_data": deletion_data, "created_at": firestore.SERVER_TIMESTAMP},
        )
        logger.info(
            f"Stored pending deletion for user {user_id} in '{config.FS_COLLECTION_PENDING_DELETIONS}'"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to store pending deletion for user {user_id}: {e}", exc_info=True)
        return False

async def get_pending_deletion(user_id: int) -> dict | None:
    if not PENDING_DELETIONS_COLLECTION:
        logger.error("Firestore PENDING_DELETIONS_COLLECTION unavailable for getting pending deletion.")
        return None
    doc_ref = PENDING_DELETIONS_COLLECTION.document(str(user_id))
    try:
        snapshot = await asyncio.to_thread(doc_ref.get)
        if snapshot.exists:
            data = snapshot.to_dict()  # type: ignore
            logger.debug(f"Retrieved pending deletion for user {user_id}.")
            return data.get("deletion_data")
        return None
    except Exception as e:
        logger.error(f"Error fetching pending deletion for user {user_id}: {e}", exc_info=True)
        return None

async def delete_pending_deletion(user_id: int) -> bool:
    if not PENDING_DELETIONS_COLLECTION:
        logger.error("Firestore PENDING_DELETIONS_COLLECTION unavailable for deleting pending deletion.")
        return False
    doc_ref = PENDING_DELETIONS_COLLECTION.document(str(user_id))
    try:
        await asyncio.to_thread(doc_ref.delete)
        logger.info(f"Deleted pending deletion for user {user_id} (if it existed).")
        return True
    except Exception as e:
        logger.error(f"Failed to delete pending deletion for user {user_id}: {e}", exc_info=True)
        return False
