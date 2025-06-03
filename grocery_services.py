import asyncio
import logging
from google.cloud import firestore

import config

logger = logging.getLogger(__name__)

# Firestore Client and Collection for grocery lists
_db = config.FIRESTORE_DB
FS_COLLECTION_GROCERY_LISTS = (
    _db.collection(config.FS_COLLECTION_GROCERY_LISTS) if _db else None
)


async def get_grocery_list(user_id: int) -> list[str] | None:
    """Retrieves the user's grocery list from Firestore."""
    if not FS_COLLECTION_GROCERY_LISTS:
        logger.error(
            "GS: Firestore FS_COLLECTION_GROCERY_LISTS unavailable for get_grocery_list."
        )
        return None
    user_doc_id = str(user_id)
    doc_ref = FS_COLLECTION_GROCERY_LISTS.document(user_doc_id)
    try:
        snapshot = await asyncio.to_thread(doc_ref.get)
        if snapshot.exists:
            data = snapshot.to_dict()  # type: ignore
            items = data.get("items")  # type: ignore
            if isinstance(items, list):
                logger.info(
                    f"GS: Retrieved grocery list for user {user_id} with {len(items)} items."
                )
                return items
            else:
                logger.error(
                    f"GS: 'items' field is not a list for user {user_id} in grocery list. Found: {type(items)}"
                )
                return None
        else:
            logger.info(
                f"GS: No grocery list document found for user {user_id}. Returning empty list."
            )
            return []
    except Exception as e:
        logger.error(
            f"GS: Error fetching grocery list for user {user_id}: {e}",
            exc_info=True,
        )
        return None


async def add_to_grocery_list(user_id: int, items_to_add: list[str]) -> bool:
    """Adds items to the user's grocery list in Firestore."""
    if not FS_COLLECTION_GROCERY_LISTS:
        logger.error(
            "GS: Firestore FS_COLLECTION_GROCERY_LISTS unavailable for add_to_grocery_list."
        )
        return False
    if not items_to_add:
        logger.info("GS: No items provided to add_to_grocery_list.")
        return True

    user_doc_id = str(user_id)
    doc_ref = FS_COLLECTION_GROCERY_LISTS.document(user_doc_id)
    try:
        await asyncio.to_thread(
            doc_ref.set,
            {"items": firestore.ArrayUnion(items_to_add)},
            merge=True,
        )
        logger.info(
            f"GS: Added/Updated {len(items_to_add)} items to grocery list for user {user_id}."
        )
        return True
    except Exception as e:
        logger.error(
            f"GS: Failed to add items to grocery list for user {user_id}: {e}",
            exc_info=True,
        )
        return False


async def delete_grocery_list(user_id: int) -> bool:
    """Deletes the user's entire grocery list from Firestore."""
    if not FS_COLLECTION_GROCERY_LISTS:
        logger.error(
            "GS: Firestore FS_COLLECTION_GROCERY_LISTS unavailable for delete_grocery_list."
        )
        return False
    user_doc_id = str(user_id)
    doc_ref = FS_COLLECTION_GROCERY_LISTS.document(user_doc_id)
    try:
        await asyncio.to_thread(doc_ref.delete)
        logger.info(
            f"GS: Attempted deletion of grocery list for user {user_id}."
        )
        return True
    except Exception as e:
        logger.error(
            f"GS: Error deleting grocery list for user {user_id}: {e}",
            exc_info=True,
        )
        return False

