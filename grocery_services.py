import asyncio
import logging
import uuid
from google.cloud import firestore
from google.api_core.exceptions import NotFound

import config

logger = logging.getLogger(__name__)

# Firestore Client and Collection for grocery lists
_db = config.FIRESTORE_DB
FS_COLLECTION_GROCERY_LISTS = (
    _db.collection(config.FS_COLLECTION_GROCERY_LISTS) if _db else None
)
FS_COLLECTION_GROCERY_GROUPS = (
    _db.collection(config.FS_COLLECTION_GROCERY_LIST_GROUPS) if _db else None
)
GROCERY_SHARE_REQUESTS_COLLECTION = (
    _db.collection(config.FS_COLLECTION_GROCERY_SHARE_REQUESTS) if _db else None
)

async def get_grocery_list(user_id: int) -> list[str] | None:
    """Retrieves the user's grocery list, following group link if present."""
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
            data = snapshot.to_dict() or {}
            group_id = data.get("group_id")
            if group_id and FS_COLLECTION_GROCERY_GROUPS:
                group_ref = FS_COLLECTION_GROCERY_GROUPS.document(group_id)
                group_snap = await asyncio.to_thread(group_ref.get)
                if group_snap.exists:
                    group_data = group_snap.to_dict() or {}
                    items = group_data.get("items")
                    if isinstance(items, list):
                        return items
            items = data.get("items")
            if isinstance(items, list):
                return items
            logger.error(
                f"GS: 'items' field is not a list for user {user_id}. Found: {type(items)}"
            )
            return None
        else:
            return []
    except Exception as e:
        logger.error(
            f"GS: Error fetching grocery list for user {user_id}: {e}", exc_info=True
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
        snapshot = await asyncio.to_thread(doc_ref.get)
        group_id = None
        if snapshot.exists:
            data = snapshot.to_dict() or {}
            group_id = data.get("group_id")

        if group_id and FS_COLLECTION_GROCERY_GROUPS:
            group_ref = FS_COLLECTION_GROCERY_GROUPS.document(group_id)
            await asyncio.to_thread(
                group_ref.set,
                {"items": firestore.ArrayUnion(items_to_add)},
                merge=True,
            )
        else:
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
            f"GS: Failed to add items to grocery list for user {user_id}: {e}", exc_info=True
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
        snapshot = await asyncio.to_thread(doc_ref.get)
        group_id = None
        if snapshot.exists:
            data = snapshot.to_dict() or {}
            group_id = data.get("group_id")

        if group_id and FS_COLLECTION_GROCERY_GROUPS:
            group_ref = FS_COLLECTION_GROCERY_GROUPS.document(group_id)
            await asyncio.to_thread(group_ref.update, {"items": []})
        else:
            await asyncio.to_thread(doc_ref.delete)
        logger.info(
            f"GS: Attempted deletion of grocery list for user {user_id}."
        )
        return True
    except Exception as e:
        logger.error(
            f"GS: Error deleting grocery list for user {user_id}: {e}", exc_info=True
        )
        return False


async def merge_grocery_lists(user_a: int, user_b: int) -> bool:
    """Merges grocery lists for two users into a shared group."""
    if not FS_COLLECTION_GROCERY_LISTS or not FS_COLLECTION_GROCERY_GROUPS:
        logger.error("GS: Firestore collections unavailable for merge_grocery_lists.")
        return False

    list_a = await get_grocery_list(user_a) or []
    list_b = await get_grocery_list(user_b) or []
    merged = list(dict.fromkeys(list_a + list_b))

    group_id = str(uuid.uuid4())
    group_ref = FS_COLLECTION_GROCERY_GROUPS.document(group_id)
    try:
        await asyncio.to_thread(group_ref.set, {"items": merged, "members": [str(user_a), str(user_b)]})
        for uid in (user_a, user_b):
            user_ref = FS_COLLECTION_GROCERY_LISTS.document(str(uid))
            await asyncio.to_thread(user_ref.set, {"group_id": group_id}, merge=True)
        logger.info(f"GS: Created grocery group {group_id} for users {user_a} and {user_b}")
        return True
    except Exception as e:
        logger.error(f"GS: Error merging grocery lists for {user_a} and {user_b}: {e}", exc_info=True)
        return False

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