import asyncio
import logging
import pytz
from pytz.exceptions import UnknownTimeZoneError
from google.cloud import firestore
import config

logger = logging.getLogger(__name__)

_db = config.FIRESTORE_DB
USER_PREFS_COLLECTION = _db.collection(config.FS_COLLECTION_PREFS) if _db else None

async def set_user_timezone(user_id: int, timezone_str: str) -> bool:
    if not USER_PREFS_COLLECTION:
        logger.error("Firestore USER_PREFS_COLLECTION unavailable for setting timezone.")
        return False
    doc_ref = USER_PREFS_COLLECTION.document(str(user_id))
    try:
        pytz.timezone(timezone_str)
        data_to_set = {"timezone": timezone_str, "updated_at": firestore.SERVER_TIMESTAMP}
        await asyncio.to_thread(doc_ref.set, data_to_set, merge=True)
        logger.info(f"Stored timezone '{timezone_str}' for user {user_id} in '{config.FS_COLLECTION_PREFS}'")
        return True
    except UnknownTimeZoneError:
        logger.warning(f"Attempted to store invalid timezone '{timezone_str}' for user {user_id}")
        return False
    except Exception as e:
        logger.error(f"Failed to store timezone for user {user_id}: {e}", exc_info=True)
        return False

async def get_user_timezone_str(user_id: int) -> str | None:
    if not USER_PREFS_COLLECTION:
        logger.error("Firestore USER_PREFS_COLLECTION unavailable for getting timezone.")
        return None
    doc_ref = USER_PREFS_COLLECTION.document(str(user_id))
    try:
        snapshot = await asyncio.to_thread(doc_ref.get)
        if snapshot.exists:
            prefs_data = snapshot.to_dict()  # type: ignore
            tz_str = prefs_data.get("timezone")
            if tz_str:
                try:
                    pytz.timezone(tz_str)
                    return tz_str
                except UnknownTimeZoneError:
                    logger.warning(
                        f"Found invalid timezone '{tz_str}' in DB prefs for user {user_id}. Treating as unset."
                    )
        return None
    except Exception as e:
        logger.error(f"Error fetching timezone for user {user_id}: {e}", exc_info=True)
        return None
