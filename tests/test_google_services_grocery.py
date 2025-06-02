import unittest
from unittest.mock import patch, MagicMock, AsyncMock, call, ANY
import asyncio # Required for IsolatedAsyncioTestCase if some test setups need await

# Required for Firestore operations and types
from google.cloud import firestore # For SERVER_TIMESTAMP if used directly in mocks
from google.cloud.firestore_v1.document import DocumentReference, DocumentSnapshot
from google.cloud.firestore_v1.collection import CollectionReference
from google.api_core.exceptions import NotFound


# Modules to test
import google_services as gs
from models import GroceryList, GroceryListShareRequest # For type hints and constructing mock data
import config # To potentially mock config.FIRESTORE_DB if it's accessed directly

# Define a common user ID for tests, ensure it's a string as per new requirements
TEST_USER_ID = "test_user_123"
TEST_OTHER_USER_ID = "test_user_456"
TEST_LIST_ID = "test_list_abc"
TEST_REQUEST_ID = "test_request_xyz"

# Helper to run async functions if not using IsolatedAsyncioTestCase
def async_test(f):
    def wrapper(*args, **kwargs):
        asyncio.run(f(*args, **kwargs))
    return wrapper

class TestGroceryListGoogleServices(unittest.IsolatedAsyncioTestCase): # Using IsolatedAsyncioTestCase for async tests

    def setUp(self):
        """Setup common mocks if any, e.g., patching config.FIRESTORE_DB"""
        # It's often cleaner to patch specific collection objects within each test 
        # or test class if the collection name is consistent.
        pass

    # Placeholder for tests to be moved and added
    async def test_example_placeholder(self): # Will be replaced by actual tests
        self.assertTrue(True)

# Copied and pasted TestGroceryListGoogleServices class here, will need significant updates
# to use IsolatedAsyncioTestCase and reflect new gs function signatures.
# For now, pasting as-is to move the code.

# Define a user ID that can be used across tests
_TEST_USER_ID_INT = 12345 # Old tests used int
_TEST_USER_ID_STR_OLD = str(_TEST_USER_ID_INT) # Old tests used this for string conversion

# Note: This class now inherits from unittest.IsolatedAsyncioTestCase
class TestGroceryListGoogleServices(unittest.IsolatedAsyncioTestCase):

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_create_grocery_list_success(self, mock_fs_collection_grocery_lists):
        """Test successful creation of a new grocery list."""
        mock_add_result = (MagicMock(), MagicMock(spec=DocumentReference)) # (timestamp, doc_ref)
        mock_add_result[1].id = TEST_LIST_ID # Mock the ID of the new document
        mock_fs_collection_grocery_lists.add = AsyncMock(return_value=mock_add_result)

        initial_items = ["apples", "bananas"]
        list_id = await gs.create_grocery_list(TEST_USER_ID, initial_items)

        self.assertEqual(list_id, TEST_LIST_ID)
        mock_fs_collection_grocery_lists.add.assert_awaited_once_with({
            'owner_id': TEST_USER_ID,
            'items': initial_items,
            'shared_with': [],
            'created_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP
        })

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_create_grocery_list_no_initial_items(self, mock_fs_collection_grocery_lists):
        """Test creating a list with no initial items."""
        mock_add_result = (MagicMock(), MagicMock(spec=DocumentReference))
        mock_add_result[1].id = "new_list_empty"
        mock_fs_collection_grocery_lists.add = AsyncMock(return_value=mock_add_result)

        list_id = await gs.create_grocery_list(TEST_USER_ID) # No initial items

        self.assertEqual(list_id, "new_list_empty")
        mock_fs_collection_grocery_lists.add.assert_awaited_once_with({
            'owner_id': TEST_USER_ID,
            'items': [], # Default empty list
            'shared_with': [],
            'created_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP
        })

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS', None) # Simulate collection not available
    async def test_create_grocery_list_collection_unavailable(self):
        """Test list creation when Firestore collection is unavailable."""
        list_id = await gs.create_grocery_list(TEST_USER_ID, ["item"])
        self.assertIsNone(list_id)

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_create_grocery_list_firestore_exception(self, mock_fs_collection_grocery_lists):
        """Test list creation when Firestore add() raises an exception."""
        mock_fs_collection_grocery_lists.add = AsyncMock(side_effect=Exception("Firestore connection error"))
        
        list_id = await gs.create_grocery_list(TEST_USER_ID, ["item"])
        self.assertIsNone(list_id)
    
    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_get_user_owned_grocery_lists_found(self, mock_fs_collection_grocery_lists):
        """Test retrieving owned grocery lists for a user."""
        mock_snapshot1 = MagicMock(spec=DocumentSnapshot)
        mock_snapshot1.id = "list1"
        mock_snapshot1.to_dict.return_value = {'owner_id': TEST_USER_ID, 'items': ['milk']}
        
        mock_snapshot2 = MagicMock(spec=DocumentSnapshot)
        mock_snapshot2.id = "list2"
        mock_snapshot2.to_dict.return_value = {'owner_id': TEST_USER_ID, 'items': ['eggs']}

        mock_query = MagicMock(spec=firestore.CollectionReference) # Mocking the query object
        mock_query.stream = AsyncMock(return_value=[mock_snapshot1, mock_snapshot2])
        mock_fs_collection_grocery_lists.where = MagicMock(return_value=mock_query)

        owned_lists = await gs.get_user_owned_grocery_lists(TEST_USER_ID)

        self.assertEqual(len(owned_lists), 2)
        self.assertIn({'id': 'list1', 'owner_id': TEST_USER_ID, 'items': ['milk']}, owned_lists)
        self.assertIn({'id': 'list2', 'owner_id': TEST_USER_ID, 'items': ['eggs']}, owned_lists)
        mock_fs_collection_grocery_lists.where.assert_called_once_with(filter=ANY) # ANY for FieldFilter
        # Check that the FieldFilter was for owner_id (more complex check)
        args, _ = mock_fs_collection_grocery_lists.where.call_args
        self.assertEqual(args[0].field_path, "owner_id")
        self.assertEqual(args[0].op_string, "==")
        self.assertEqual(args[0].value, TEST_USER_ID)


    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_get_user_owned_grocery_lists_not_found(self, mock_fs_collection_grocery_lists):
        """Test retrieving owned lists when none exist."""
        mock_query = MagicMock(spec=firestore.CollectionReference)
        mock_query.stream = AsyncMock(return_value=[]) # No snapshots
        mock_fs_collection_grocery_lists.where = MagicMock(return_value=mock_query)

        owned_lists = await gs.get_user_owned_grocery_lists(TEST_USER_ID)
        self.assertEqual(owned_lists, [])
        mock_fs_collection_grocery_lists.where.assert_called_once_with(filter=ANY)


    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_get_user_owned_grocery_list_doc_found(self, mock_fs_collection_grocery_lists):
        """Test helper get_user_owned_grocery_list_doc when a list is found."""
        mock_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_snapshot.id = "owned_list_1"
        mock_snapshot.exists = True # Ensure exists is True for the snapshot itself
        
        mock_query = MagicMock()
        mock_query.limit = MagicMock(return_value=mock_query) # query.limit() returns self
        mock_query.stream = AsyncMock(return_value=[mock_snapshot]) # stream returns a list of snapshots
        mock_fs_collection_grocery_lists.where = MagicMock(return_value=mock_query)

        result_snapshot = await gs.get_user_owned_grocery_list_doc(TEST_USER_ID)

        self.assertIsNotNone(result_snapshot)
        self.assertEqual(result_snapshot.id, "owned_list_1")
        mock_fs_collection_grocery_lists.where.assert_called_once_with(filter=ANY)
        mock_query.limit.assert_called_once_with(1)

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_get_user_owned_grocery_list_doc_not_found(self, mock_fs_collection_grocery_lists):
        """Test helper get_user_owned_grocery_list_doc when no list is found."""
        mock_query = MagicMock()
        mock_query.limit = MagicMock(return_value=mock_query)
        mock_query.stream = AsyncMock(return_value=[]) # Empty list of snapshots
        mock_fs_collection_grocery_lists.where = MagicMock(return_value=mock_query)

        result_snapshot = await gs.get_user_owned_grocery_list_doc(TEST_USER_ID)
        self.assertIsNone(result_snapshot)

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_get_grocery_list_by_id_found(self, mock_fs_collection_grocery_lists):
        """Test retrieving a specific grocery list by its ID when it exists."""
        mock_doc_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_doc_snapshot.exists = True
        mock_doc_snapshot.id = TEST_LIST_ID
        mock_doc_data = {'owner_id': TEST_USER_ID, 'items': ['test item'], 'shared_with': []}
        mock_doc_snapshot.to_dict.return_value = mock_doc_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_doc_snapshot)
        mock_fs_collection_grocery_lists.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.get_grocery_list_by_id(TEST_LIST_ID)

        self.assertIsNotNone(result)
        self.assertEqual(result['id'], TEST_LIST_ID)
        self.assertEqual(result['owner_id'], TEST_USER_ID)
        self.assertEqual(result['items'], ['test item'])
        mock_fs_collection_grocery_lists.document.assert_called_once_with(TEST_LIST_ID)
        mock_doc_ref.get.assert_awaited_once()

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_get_grocery_list_by_id_not_found(self, mock_fs_collection_grocery_lists):
        """Test retrieving a specific grocery list by ID when it does not exist."""
        mock_doc_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_doc_snapshot.exists = False
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_doc_snapshot)
        mock_fs_collection_grocery_lists.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.get_grocery_list_by_id("non_existent_list")
        self.assertIsNone(result)
        mock_fs_collection_grocery_lists.document.assert_called_once_with("non_existent_list")

    @patch('google_services.gs.create_grocery_list', new_callable=AsyncMock) # Mock create_grocery_list within gs
    @patch('google_services.gs.get_user_owned_grocery_list_doc', new_callable=AsyncMock)
    @patch('google_services.FS_COLLECTION_GROCERY_LISTS') # Still need to mock the collection for direct access if any
    async def test_add_to_grocery_list_existing_owned_list(self, mock_fs_collection_grocery_lists, mock_get_owned_doc, mock_create_list):
        """Test adding items to an existing owned grocery list."""
        mock_owned_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_owned_list_snapshot.exists = True
        mock_owned_list_snapshot.reference = MagicMock(spec=DocumentReference)
        mock_owned_list_snapshot.id = "owned_list_123"
        mock_get_owned_doc.return_value = mock_owned_list_snapshot
        
        items_to_add = ["cheese", "crackers"]
        result = await gs.add_to_grocery_list(TEST_USER_ID, items_to_add)

        self.assertTrue(result)
        mock_get_owned_doc.assert_awaited_once_with(TEST_USER_ID)
        mock_owned_list_snapshot.reference.update.assert_awaited_once_with({
            'items': firestore.ArrayUnion(items_to_add),
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        mock_create_list.assert_not_awaited()

    @patch('google_services.gs.create_grocery_list', new_callable=AsyncMock)
    @patch('google_services.gs.get_user_owned_grocery_list_doc', new_callable=AsyncMock)
    async def test_add_to_grocery_list_no_owned_list_creates_new(self, mock_get_owned_doc, mock_create_list):
        """Test add_to_grocery_list creates a new list if no owned list exists."""
        mock_get_owned_doc.return_value = None # No owned list found
        mock_create_list.return_value = "newly_created_list_id" # Mock successful creation
        
        items_to_add = ["new item 1", "new item 2"]
        result = await gs.add_to_grocery_list(TEST_USER_ID, items_to_add)

        self.assertTrue(result)
        mock_get_owned_doc.assert_awaited_once_with(TEST_USER_ID)
        mock_create_list.assert_awaited_once_with(TEST_USER_ID, initial_items=items_to_add)

    @patch('google_services.gs.get_user_owned_grocery_list_doc', new_callable=AsyncMock)
    async def test_add_to_grocery_list_existing_list_update_fails(self, mock_get_owned_doc):
        """Test add_to_grocery_list fails if updating existing list fails."""
        mock_owned_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_owned_list_snapshot.exists = True
        mock_owned_list_snapshot.reference = MagicMock(spec=DocumentReference)
        mock_owned_list_snapshot.reference.update = AsyncMock(side_effect=Exception("Firestore update error"))
        mock_get_owned_doc.return_value = mock_owned_list_snapshot
        
        result = await gs.add_to_grocery_list(TEST_USER_ID, ["item"])
        self.assertFalse(result)

    @patch('google_services.gs.get_user_owned_grocery_list_doc', new_callable=AsyncMock)
    @patch('google_services.gs.create_grocery_list', new_callable=AsyncMock)
    async def test_add_to_grocery_list_no_owned_list_creation_fails(self, mock_create_list, mock_get_owned_doc):
        """Test add_to_grocery_list fails if new list creation fails."""
        mock_get_owned_doc.return_value = None # No owned list
        mock_create_list.return_value = None # Creation fails
        
        result = await gs.add_to_grocery_list(TEST_USER_ID, ["item"])
        self.assertFalse(result)
        mock_create_list.assert_awaited_once()

    async def test_add_to_grocery_list_no_items(self):
        """Test add_to_grocery_list returns True if no items are provided."""
        # No mocks needed as it should return early
        result = await gs.add_to_grocery_list(TEST_USER_ID, [])
        self.assertTrue(result)

    @patch('google_services.gs.get_user_owned_grocery_list_doc', new_callable=AsyncMock)
    async def test_get_grocery_list_owned_list_with_items(self, mock_get_owned_doc):
        """Test get_grocery_list returns items from an owned list."""
        mock_owned_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_owned_list_snapshot.exists = True
        mock_owned_list_snapshot.id = "owned_list_items"
        mock_owned_list_data = {'owner_id': TEST_USER_ID, 'items': ['itemA', 'itemB'], 'shared_with': []}
        mock_owned_list_snapshot.to_dict.return_value = mock_owned_list_data
        mock_get_owned_doc.return_value = mock_owned_list_snapshot

        items = await gs.get_grocery_list(TEST_USER_ID)
        self.assertEqual(items, ['itemA', 'itemB'])
        mock_get_owned_doc.assert_awaited_once_with(TEST_USER_ID)

    @patch('google_services.gs.get_user_owned_grocery_list_doc', new_callable=AsyncMock)
    async def test_get_grocery_list_owned_list_no_items(self, mock_get_owned_doc):
        """Test get_grocery_list returns empty list if owned list has no items."""
        mock_owned_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_owned_list_snapshot.exists = True
        mock_owned_list_snapshot.id = "owned_list_empty"
        mock_owned_list_data = {'owner_id': TEST_USER_ID, 'items': [], 'shared_with': []}
        mock_owned_list_snapshot.to_dict.return_value = mock_owned_list_data
        mock_get_owned_doc.return_value = mock_owned_list_snapshot

        items = await gs.get_grocery_list(TEST_USER_ID)
        self.assertEqual(items, [])

    @patch('google_services.gs.get_user_owned_grocery_list_doc', new_callable=AsyncMock)
    async def test_get_grocery_list_no_owned_list(self, mock_get_owned_doc):
        """Test get_grocery_list returns empty list if no owned list exists."""
        mock_get_owned_doc.return_value = None # No owned list

        items = await gs.get_grocery_list(TEST_USER_ID)
        self.assertEqual(items, [])

    @patch('google_services.gs.get_user_owned_grocery_list_doc', new_callable=AsyncMock)
    async def test_get_grocery_list_owned_list_malformed_items(self, mock_get_owned_doc):
        """Test get_grocery_list returns empty list if items field is not a list."""
        mock_owned_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_owned_list_snapshot.exists = True
        mock_owned_list_snapshot.id = "owned_list_malformed"
        mock_owned_list_data = {'owner_id': TEST_USER_ID, 'items': "not-a-list"} # Malformed
        mock_owned_list_snapshot.to_dict.return_value = mock_owned_list_data
        mock_get_owned_doc.return_value = mock_owned_list_snapshot
        
        items = await gs.get_grocery_list(TEST_USER_ID)
        self.assertEqual(items, []) # Should default to empty list on malformed data

    @patch('google_services.gs.get_user_owned_grocery_list_doc', new_callable=AsyncMock)
    async def test_clear_grocery_list_items_owned_list(self, mock_get_owned_doc):
        """Test clearing items from an owned list."""
        mock_owned_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_owned_list_snapshot.exists = True
        mock_owned_list_snapshot.reference = MagicMock(spec=DocumentReference)
        mock_owned_list_snapshot.id = "owned_list_to_clear"
        mock_get_owned_doc.return_value = mock_owned_list_snapshot

        result = await gs.clear_grocery_list_items(TEST_USER_ID)
        self.assertTrue(result)
        mock_get_owned_doc.assert_awaited_once_with(TEST_USER_ID)
        mock_owned_list_snapshot.reference.update.assert_awaited_once_with({
            'items': [],
            'updated_at': firestore.SERVER_TIMESTAMP
        })

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_clear_grocery_list_items_specific_list_owner(self, mock_fs_collection):
        """Test clearing items from a specific list by owner."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        mock_list_snapshot.id = TEST_LIST_ID
        mock_list_data = {'owner_id': TEST_USER_ID, 'items': ['item1'], 'shared_with': [TEST_OTHER_USER_ID]}
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_doc_ref.update = AsyncMock() # For the items clear
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.clear_grocery_list_items(TEST_USER_ID, list_id=TEST_LIST_ID)
        self.assertTrue(result)
        mock_fs_collection.document.assert_called_once_with(TEST_LIST_ID)
        mock_doc_ref.update.assert_awaited_once_with({
            'items': [],
            'updated_at': firestore.SERVER_TIMESTAMP
        })

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_clear_grocery_list_items_specific_list_shared_user(self, mock_fs_collection):
        """Test clearing items from a specific list by a shared user."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        mock_list_snapshot.id = TEST_LIST_ID
        mock_list_data = {'owner_id': TEST_OTHER_USER_ID, 'items': ['item1'], 'shared_with': [TEST_USER_ID]}
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_doc_ref.update = AsyncMock()
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.clear_grocery_list_items(TEST_USER_ID, list_id=TEST_LIST_ID)
        self.assertTrue(result)
        mock_doc_ref.update.assert_awaited_once_with({
            'items': [],
            'updated_at': firestore.SERVER_TIMESTAMP
        })

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_clear_grocery_list_items_specific_list_no_permission(self, mock_fs_collection):
        """Test clearing items fails if user has no permission to the specific list."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        mock_list_snapshot.id = TEST_LIST_ID
        mock_list_data = {'owner_id': TEST_OTHER_USER_ID, 'items': ['item1'], 'shared_with': ["another_user"]}
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.clear_grocery_list_items(TEST_USER_ID, list_id=TEST_LIST_ID)
        self.assertFalse(result)
        mock_doc_ref.update.assert_not_called()


    @patch('google_services.gs.get_user_owned_grocery_list_doc', new_callable=AsyncMock)
    async def test_clear_grocery_list_items_no_owned_list(self, mock_get_owned_doc):
        """Test clearing items when no owned list exists (list_id is None)."""
        mock_get_owned_doc.return_value = None
        result = await gs.clear_grocery_list_items(TEST_USER_ID)
        self.assertTrue(result) # Vacuously true as no list to clear

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_permanently_delete_grocery_list_owner_success(self, mock_fs_collection):
        """Test permanent deletion of a list by its owner."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        mock_list_snapshot.id = TEST_LIST_ID
        mock_list_data = {'owner_id': TEST_USER_ID} # User is the owner
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_doc_ref.delete = AsyncMock()
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.permanently_delete_grocery_list(TEST_USER_ID, TEST_LIST_ID)
        self.assertTrue(result)
        mock_fs_collection.document.assert_called_once_with(TEST_LIST_ID)
        mock_doc_ref.delete.assert_awaited_once()

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_permanently_delete_grocery_list_not_owner(self, mock_fs_collection):
        """Test permanent deletion fails if user is not the owner."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        mock_list_snapshot.id = TEST_LIST_ID
        mock_list_data = {'owner_id': TEST_OTHER_USER_ID} # Different owner
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.permanently_delete_grocery_list(TEST_USER_ID, TEST_LIST_ID)
        self.assertFalse(result)
        mock_doc_ref.delete.assert_not_called()

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_permanently_delete_grocery_list_not_found(self, mock_fs_collection):
        """Test permanent deletion if list does not exist."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = False # List not found
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.permanently_delete_grocery_list(TEST_USER_ID, "non_existent_list_id")
        self.assertFalse(result) # Or True if idempotent deletion preferred and logged

    # --- Placeholder for old tests that need complete rewrite or removal ---
    # The following tests from the old class are heavily based on user_id being the document ID
    # and direct doc.get() / doc.set() / doc.update() patterns which are different now.

    # --- Tests for Sharing Functionality ---

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_get_shared_grocery_lists_for_user_found(self, mock_fs_collection):
        """Test retrieving lists shared with a user."""
        mock_snapshot1 = MagicMock(spec=DocumentSnapshot)
        mock_snapshot1.id = "shared_list1"
        mock_snapshot1.to_dict.return_value = {'owner_id': TEST_OTHER_USER_ID, 'items': ['itemS1'], 'shared_with': [TEST_USER_ID]}
        
        mock_snapshot2 = MagicMock(spec=DocumentSnapshot)
        mock_snapshot2.id = "shared_list2"
        mock_snapshot2.to_dict.return_value = {'owner_id': "another_owner", 'items': ['itemS2'], 'shared_with': [TEST_USER_ID, "yet_another_user"]}

        mock_query = MagicMock()
        mock_query.stream = AsyncMock(return_value=[mock_snapshot1, mock_snapshot2])
        mock_fs_collection.where = MagicMock(return_value=mock_query)

        shared_lists = await gs.get_shared_grocery_lists_for_user(TEST_USER_ID)

        self.assertEqual(len(shared_lists), 2)
        # Verify the content, ensuring 'id' is added
        expected_list1_data = {'id': 'shared_list1', 'owner_id': TEST_OTHER_USER_ID, 'items': ['itemS1'], 'shared_with': [TEST_USER_ID]}
        expected_list2_data = {'id': 'shared_list2', 'owner_id': "another_owner", 'items': ['itemS2'], 'shared_with': [TEST_USER_ID, "yet_another_user"]}
        self.assertIn(expected_list1_data, shared_lists)
        self.assertIn(expected_list2_data, shared_lists)
        
        mock_fs_collection.where.assert_called_once()
        args, _ = mock_fs_collection.where.call_args
        self.assertEqual(args[0].field_path, "shared_with")
        self.assertEqual(args[0].op_string, "array_contains")
        self.assertEqual(args[0].value, TEST_USER_ID)

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_get_shared_grocery_lists_for_user_not_found(self, mock_fs_collection):
        """Test retrieving shared lists when none are shared with the user."""
        mock_query = MagicMock()
        mock_query.stream = AsyncMock(return_value=[]) # No lists shared
        mock_fs_collection.where = MagicMock(return_value=mock_query)

        shared_lists = await gs.get_shared_grocery_lists_for_user(TEST_USER_ID)
        self.assertEqual(shared_lists, [])

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_add_user_to_shared_list_success_owner(self, mock_fs_collection):
        """Test owner successfully adding a user to a shared list."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        mock_list_data = {'owner_id': TEST_USER_ID, 'shared_with': []} # Current user is owner
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_doc_ref.update = AsyncMock()
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.add_user_to_shared_list(TEST_LIST_ID, TEST_OTHER_USER_ID, TEST_USER_ID)
        self.assertTrue(result)
        mock_fs_collection.document.assert_called_once_with(TEST_LIST_ID)
        mock_doc_ref.update.assert_awaited_once_with({
            'shared_with': firestore.ArrayUnion([TEST_OTHER_USER_ID]),
            'updated_at': firestore.SERVER_TIMESTAMP
        })

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_add_user_to_shared_list_not_owner(self, mock_fs_collection):
        """Test adding user to shared list fails if not initiated by owner."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        mock_list_data = {'owner_id': "someone_else_id", 'shared_with': []} 
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.add_user_to_shared_list(TEST_LIST_ID, TEST_OTHER_USER_ID, TEST_USER_ID) # TEST_USER_ID is not owner
        self.assertFalse(result)
        mock_doc_ref.update.assert_not_called()

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_add_user_to_shared_list_list_not_found(self, mock_fs_collection):
        """Test adding user to shared list fails if list doesn't exist."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = False # List not found
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.add_user_to_shared_list("non_existent_list", TEST_OTHER_USER_ID, TEST_USER_ID)
        self.assertFalse(result)

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_add_user_to_shared_list_target_already_shared(self, mock_fs_collection):
        """Test adding user who is already in shared_with list."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        mock_list_data = {'owner_id': TEST_USER_ID, 'shared_with': [TEST_OTHER_USER_ID]} # Target already shared
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.add_user_to_shared_list(TEST_LIST_ID, TEST_OTHER_USER_ID, TEST_USER_ID)
        self.assertTrue(result) # Should be idempotent, considered success
        mock_doc_ref.update.assert_not_called() # No update needed

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_add_user_to_shared_list_target_is_owner(self, mock_fs_collection):
        """Test adding owner to shared_with list (should be no-op and success)."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        mock_list_data = {'owner_id': TEST_USER_ID, 'shared_with': []}
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        # Attempting to add owner (TEST_USER_ID) to their own list's shared_with
        result = await gs.add_user_to_shared_list(TEST_LIST_ID, TEST_USER_ID, TEST_USER_ID)
        self.assertTrue(result)
        mock_doc_ref.update.assert_not_called()

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_remove_user_from_shared_list_owner_removes_other(self, mock_fs_collection):
        """Test owner successfully removing another user from shared list."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        # TEST_OTHER_USER_ID is in shared_with, TEST_USER_ID is owner
        mock_list_data = {'owner_id': TEST_USER_ID, 'shared_with': [TEST_OTHER_USER_ID, "another_user"]}
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_doc_ref.update = AsyncMock()
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.remove_user_from_shared_list(TEST_LIST_ID, TEST_OTHER_USER_ID, TEST_USER_ID)
        self.assertTrue(result)
        mock_fs_collection.document.assert_called_once_with(TEST_LIST_ID)
        mock_doc_ref.update.assert_awaited_once_with({
            'shared_with': firestore.ArrayRemove([TEST_OTHER_USER_ID]),
            'updated_at': firestore.SERVER_TIMESTAMP
        })

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_remove_user_from_shared_list_user_removes_self(self, mock_fs_collection):
        """Test user successfully removing themselves from a shared list."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        # TEST_USER_ID is in shared_with, owner is TEST_OTHER_USER_ID
        mock_list_data = {'owner_id': TEST_OTHER_USER_ID, 'shared_with': [TEST_USER_ID, "another_user"]}
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_doc_ref.update = AsyncMock()
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        # TEST_USER_ID (unsharing_user_id) is removing themselves (target_user_id)
        result = await gs.remove_user_from_shared_list(TEST_LIST_ID, TEST_USER_ID, TEST_USER_ID)
        self.assertTrue(result)
        mock_doc_ref.update.assert_awaited_once_with({
            'shared_with': firestore.ArrayRemove([TEST_USER_ID]),
            'updated_at': firestore.SERVER_TIMESTAMP
        })

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_remove_user_from_shared_list_not_owner_nor_self(self, mock_fs_collection):
        """Test removal fails if unsharing_user is not owner and not the target_user."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        mock_list_data = {'owner_id': "owner_A", 'shared_with': [TEST_OTHER_USER_ID, "user_B"]}
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        # TEST_USER_ID is trying to remove TEST_OTHER_USER_ID, but is not owner and not TEST_OTHER_USER_ID
        result = await gs.remove_user_from_shared_list(TEST_LIST_ID, TEST_OTHER_USER_ID, TEST_USER_ID)
        self.assertFalse(result)
        mock_doc_ref.update.assert_not_called()
    
    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_remove_user_from_shared_list_target_not_in_list(self, mock_fs_collection):
        """Test removal is successful (idempotent) if target user is not in shared_with."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = True
        mock_list_data = {'owner_id': TEST_USER_ID, 'shared_with': ["another_user"]} # TEST_OTHER_USER_ID is not here
        mock_list_snapshot.to_dict.return_value = mock_list_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.remove_user_from_shared_list(TEST_LIST_ID, TEST_OTHER_USER_ID, TEST_USER_ID)
        self.assertTrue(result) # Idempotent success
        mock_doc_ref.update.assert_not_called() # No update needed

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    async def test_remove_user_from_shared_list_list_not_found(self, mock_fs_collection):
        """Test removal fails if the list itself is not found."""
        mock_list_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_list_snapshot.exists = False # List does not exist
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_list_snapshot)
        mock_fs_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.remove_user_from_shared_list("non_existent_list", TEST_OTHER_USER_ID, TEST_USER_ID)
        self.assertFalse(result)

    # --- Grocery List Share Request Tests ---

    @patch('google_services.gs.get_grocery_list_by_id', new_callable=AsyncMock) # Mock the helper
    @patch('google_services.GROCERY_LIST_SHARE_REQUESTS_COLLECTION')
    async def test_create_grocery_list_share_request_success(self, mock_share_req_collection, mock_get_list):
        """Test successful creation of a share request."""
        mock_get_list.return_value = {'owner_id': TEST_OTHER_USER_ID, 'id': TEST_LIST_ID, 'items': []} # Target user owns the list
        
        mock_add_result = (MagicMock(), MagicMock(spec=DocumentReference))
        mock_add_result[1].id = TEST_REQUEST_ID
        mock_share_req_collection.add = AsyncMock(return_value=mock_add_result)

        req_id = await gs.create_grocery_list_share_request(
            requester_id=TEST_USER_ID,
            requester_name="Test Requester",
            target_user_id=TEST_OTHER_USER_ID,
            list_id=TEST_LIST_ID
        )
        self.assertEqual(req_id, TEST_REQUEST_ID)
        mock_get_list.assert_awaited_once_with(TEST_LIST_ID)
        mock_share_req_collection.add.assert_awaited_once_with({
            'requester_id': TEST_USER_ID,
            'requester_name': "Test Requester",
            'target_user_id': TEST_OTHER_USER_ID,
            'list_id': TEST_LIST_ID,
            'status': 'pending',
            'request_timestamp': firestore.SERVER_TIMESTAMP
        })

    @patch('google_services.gs.get_grocery_list_by_id', new_callable=AsyncMock)
    async def test_create_grocery_list_share_request_list_not_found_or_not_owned(self, mock_get_list):
        """Test share request creation fails if list not found or not owned by target."""
        mock_get_list.return_value = None # Simulate list not found
        req_id = await gs.create_grocery_list_share_request(TEST_USER_ID, "ReqName", TEST_OTHER_USER_ID, TEST_LIST_ID)
        self.assertIsNone(req_id)

        mock_get_list.return_value = {'owner_id': "someone_else", 'id': TEST_LIST_ID} # Simulate list owned by someone else
        req_id = await gs.create_grocery_list_share_request(TEST_USER_ID, "ReqName", TEST_OTHER_USER_ID, TEST_LIST_ID)
        self.assertIsNone(req_id)
    
    @patch('google_services.GROCERY_LIST_SHARE_REQUESTS_COLLECTION')
    async def test_get_grocery_list_share_request_found(self, mock_share_req_collection):
        """Test retrieving an existing share request."""
        mock_req_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_req_snapshot.exists = True
        mock_req_snapshot.id = TEST_REQUEST_ID
        mock_req_data = {'requester_id': TEST_USER_ID, 'list_id': TEST_LIST_ID, 'status': 'pending'}
        mock_req_snapshot.to_dict.return_value = mock_req_data

        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_req_snapshot)
        mock_share_req_collection.document = MagicMock(return_value=mock_doc_ref)

        request_data = await gs.get_grocery_list_share_request(TEST_REQUEST_ID)
        self.assertIsNotNone(request_data)
        self.assertEqual(request_data['id'], TEST_REQUEST_ID)
        self.assertEqual(request_data['status'], 'pending')
        mock_share_req_collection.document.assert_called_once_with(TEST_REQUEST_ID)

    @patch('google_services.GROCERY_LIST_SHARE_REQUESTS_COLLECTION')
    async def test_get_grocery_list_share_request_not_found(self, mock_share_req_collection):
        """Test retrieving a non-existent share request."""
        mock_req_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_req_snapshot.exists = False
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_req_snapshot)
        mock_share_req_collection.document = MagicMock(return_value=mock_doc_ref)

        request_data = await gs.get_grocery_list_share_request("non_existent_req")
        self.assertIsNone(request_data)
        
    @patch('google_services.gs.add_user_to_shared_list', new_callable=AsyncMock)
    @patch('google_services.GROCERY_LIST_SHARE_REQUESTS_COLLECTION')
    async def test_update_grocery_list_share_request_status_approved(self, mock_share_req_collection, mock_add_to_shared):
        """Test approving a share request."""
        mock_req_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_req_snapshot.exists = True
        original_req_data = {
            'requester_id': TEST_USER_ID, 
            'target_user_id': TEST_OTHER_USER_ID, 
            'list_id': TEST_LIST_ID, 
            'status': 'pending'
        }
        mock_req_snapshot.to_dict.return_value = original_req_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_req_snapshot)
        mock_doc_ref.update = AsyncMock()
        mock_share_req_collection.document = MagicMock(return_value=mock_doc_ref)
        
        mock_add_to_shared.return_value = True # Mock that adding user to list succeeds

        result = await gs.update_grocery_list_share_request_status(TEST_REQUEST_ID, "approved", TEST_OTHER_USER_ID) # Respondee is target
        self.assertTrue(result)
        mock_doc_ref.update.assert_awaited_once_with({
            'status': 'approved',
            'response_timestamp': firestore.SERVER_TIMESTAMP
        })
        mock_add_to_shared.assert_awaited_once_with(TEST_LIST_ID, TEST_USER_ID, TEST_OTHER_USER_ID)

    @patch('google_services.GROCERY_LIST_SHARE_REQUESTS_COLLECTION')
    async def test_update_grocery_list_share_request_status_denied(self, mock_share_req_collection):
        """Test denying a share request."""
        mock_req_snapshot = MagicMock(spec=DocumentSnapshot)
        mock_req_snapshot.exists = True
        original_req_data = {'target_user_id': TEST_OTHER_USER_ID, 'status': 'pending'}
        mock_req_snapshot.to_dict.return_value = original_req_data
        
        mock_doc_ref = MagicMock(spec=DocumentReference)
        mock_doc_ref.get = AsyncMock(return_value=mock_req_snapshot)
        mock_doc_ref.update = AsyncMock()
        mock_share_req_collection.document = MagicMock(return_value=mock_doc_ref)

        result = await gs.update_grocery_list_share_request_status(TEST_REQUEST_ID, "denied", TEST_OTHER_USER_ID)
        self.assertTrue(result)
        mock_doc_ref.update.assert_awaited_once_with({
            'status': 'denied',
            'response_timestamp': firestore.SERVER_TIMESTAMP
        })

    @patch('google_services.GROCERY_LIST_SHARE_REQUESTS_COLLECTION')
    async def test_update_glist_share_req_status_wrong_respondee(self, mock_share_req_collection):
        """Test update fails if respondee is not the target_user_id of the request."""
        mock_req_snapshot = MagicMock()
        mock_req_snapshot.exists = True
        mock_req_snapshot.to_dict.return_value = {'target_user_id': "correct_target_user", 'status': 'pending'}
        mock_doc_ref = MagicMock()
        mock_doc_ref.get = AsyncMock(return_value=mock_req_snapshot)
        mock_share_req_collection.document.return_value = mock_doc_ref

        result = await gs.update_grocery_list_share_request_status(TEST_REQUEST_ID, "approved", "wrong_user_responding")
        self.assertFalse(result)
        mock_doc_ref.update.assert_not_called()

    @patch('google_services.GROCERY_LIST_SHARE_REQUESTS_COLLECTION')
    async def test_update_glist_share_req_status_already_actioned(self, mock_share_req_collection):
        """Test update fails if request status is not 'pending'."""
        mock_req_snapshot = MagicMock()
        mock_req_snapshot.exists = True
        mock_req_snapshot.to_dict.return_value = {'target_user_id': TEST_USER_ID, 'status': 'approved'} # Already approved
        mock_doc_ref = MagicMock()
        mock_doc_ref.get = AsyncMock(return_value=mock_req_snapshot)
        mock_share_req_collection.document.return_value = mock_doc_ref
        
        result = await gs.update_grocery_list_share_request_status(TEST_REQUEST_ID, "denied", TEST_USER_ID)
        self.assertFalse(result) # Should not allow changing status from approved to denied
        mock_doc_ref.update.assert_not_called()

    @patch('google_services.gs.add_user_to_shared_list', new_callable=AsyncMock)
    @patch('google_services.GROCERY_LIST_SHARE_REQUESTS_COLLECTION')
    async def test_update_glist_share_req_approved_sharing_fails(self, mock_share_req_collection, mock_add_to_shared):
        """Test update returns False if status is 'approved' but adding to shared list fails."""
        mock_req_snapshot = MagicMock()
        mock_req_snapshot.exists = True
        mock_req_snapshot.to_dict.return_value = {
            'requester_id': 'req1', 'target_user_id': TEST_USER_ID, 
            'list_id': 'list1', 'status': 'pending'
        }
        mock_doc_ref = MagicMock()
        mock_doc_ref.get = AsyncMock(return_value=mock_req_snapshot)
        mock_share_req_collection.document.return_value = mock_doc_ref
        mock_add_to_shared.return_value = False # Simulate sharing failure

        result = await gs.update_grocery_list_share_request_status(TEST_REQUEST_ID, "approved", TEST_USER_ID)
        self.assertFalse(result)
        mock_doc_ref.update.assert_awaited_once() # Status still updated to approved initially
        mock_add_to_shared.assert_awaited_once()
    # They will be replaced by tests for the new service logic (e.g., add_to_grocery_list based on owned list).

    # @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    # async def test_get_grocery_list_existing(self, mock_collection): pass
    # @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    # async def test_get_grocery_list_no_list(self, mock_collection): pass
    # @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    # async def test_get_grocery_list_no_items_field(self, mock_collection): pass
    # @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    # async def test_get_grocery_list_items_not_list(self, mock_collection): pass
    # @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    # async def test_get_grocery_list_firestore_error(self, mock_collection): pass
    # @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    # @patch('google_services.firestore.ArrayUnion') 
    # async def test_add_to_grocery_list_new(self, mock_array_union, mock_collection): pass
    # @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    # @patch('google_services.firestore.ArrayUnion')
    # async def test_add_to_grocery_list_existing(self, mock_array_union, mock_collection): pass
    # @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    # async def test_add_to_grocery_list_firestore_error(self, mock_collection): pass
    # @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    # async def test_delete_grocery_list_existing(self, mock_collection): pass
    # @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    # async def test_delete_grocery_list_non_existent(self, mock_collection): pass
    # @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    # async def test_delete_grocery_list_firestore_error(self, mock_collection): pass


if __name__ == '__main__':
    unittest.main()
