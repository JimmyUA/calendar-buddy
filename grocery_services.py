import asyncio
import logging
import uuid
from google.cloud import firestore

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

