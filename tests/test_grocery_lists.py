import pytest # Changed
from unittest.mock import patch, MagicMock, AsyncMock, call # Ensure call is imported
# For firestore.ArrayUnion
from google.cloud import firestore as google_firestore # To mock ArrayUnion

# Telegram specific imports for handler tests
from telegram import Update, User, Message, Chat
from telegram.ext import ContextTypes
from telegram.constants import ParseMode # For verifying parse_mode in replies

# Modules to test
import google_services as gs
import handlers
import config # To mock its attributes like FIRESTORE_DB

# For HTML escaping check
import html

# Import LLM Tools
from llm.tools.add_grocery_item_tool import AddGroceryItemTool, AddGroceryItemToolInput
from llm.tools.show_grocery_list_tool import ShowGroceryListTool
from llm.tools.clear_grocery_list_tool import ClearGroceryListTool


# Define a user ID that can be used across tests
TEST_USER_ID = 12345
TEST_USER_ID_STR = str(TEST_USER_ID)
TEST_USER_TIMEZONE = "America/New_York"

pytestmark = pytest.mark.asyncio

# --- Tests for google_services.py grocery list functions ---

async def test_get_grocery_list_existing(mock_firestore_db):
    mock_firestore_db["snapshot"].configure_mock_data({'items': ['apples', 'bananas']})

    result = await gs.get_grocery_list(TEST_USER_ID)

    assert result == ['apples', 'bananas']
    mock_firestore_db["client"].collection.assert_called_with(config.FS_COLLECTION_GROCERY_LISTS)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)
    mock_firestore_db["document"].get.assert_called_once()

async def test_get_grocery_list_no_list(mock_firestore_db):
    # Default behavior of snapshot.configure_mock_data is exists=False
    mock_firestore_db["snapshot"].configure_mock_data({}, exists_val=False)

    result = await gs.get_grocery_list(TEST_USER_ID)

    assert result == [] # Should return empty list if document doesn't exist
    mock_firestore_db["client"].collection.assert_called_with(config.FS_COLLECTION_GROCERY_LISTS)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)
    mock_firestore_db["document"].get.assert_called_once()

async def test_get_grocery_list_no_items_field(mock_firestore_db):
    mock_firestore_db["snapshot"].configure_mock_data({'other_field': 'value'})

    result = await gs.get_grocery_list(TEST_USER_ID)

    assert result is None # Items field missing
    mock_firestore_db["client"].collection.assert_called_with(config.FS_COLLECTION_GROCERY_LISTS)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)

async def test_get_grocery_list_items_not_list(mock_firestore_db):
    mock_firestore_db["snapshot"].configure_mock_data({'items': 'not-a-list'})

    result = await gs.get_grocery_list(TEST_USER_ID)

    assert result is None # Items field not a list
    mock_firestore_db["client"].collection.assert_called_with(config.FS_COLLECTION_GROCERY_LISTS)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)

async def test_get_grocery_list_firestore_error(mock_firestore_db):
    mock_firestore_db["document"].get.side_effect = Exception("Firestore boom!")

    result = await gs.get_grocery_list(TEST_USER_ID)

    assert result is None
    mock_firestore_db["client"].collection.assert_called_with(config.FS_COLLECTION_GROCERY_LISTS)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)

async def test_add_to_grocery_list_empty_items(mock_firestore_db):
    items_to_add = [] # Empty list

    # gs.add_to_grocery_list should return True and not call Firestore
    result = await gs.add_to_grocery_list(TEST_USER_ID, items_to_add)

    assert result is True
    mock_firestore_db["document"].set.assert_not_called() # Firestore 'set' should not be called

async def test_add_to_grocery_list_new(mock_firestore_db, mocker):
    items_to_add = ['milk', 'eggs']
    # Mock firestore.ArrayUnion specifically for this test
    mock_array_union = mocker.patch('google_services.firestore.ArrayUnion')
    mock_array_union.return_value = "ArrayUnionObject"

    result = await gs.add_to_grocery_list(TEST_USER_ID, items_to_add)

    assert result is True
    mock_firestore_db["client"].collection.assert_called_with(config.FS_COLLECTION_GROCERY_LISTS)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)
    mock_array_union.assert_called_once_with(items_to_add)
    mock_firestore_db["document"].set.assert_called_once_with({'items': "ArrayUnionObject"}, merge=True)

async def test_add_to_grocery_list_existing(mock_firestore_db, mocker):
    items_to_add = ['bread']
    mock_array_union = mocker.patch('google_services.firestore.ArrayUnion')
    mock_array_union.return_value = "ArrayUnionObjectBread"

    result = await gs.add_to_grocery_list(TEST_USER_ID, items_to_add)

    assert result is True
    mock_firestore_db["client"].collection.assert_called_with(config.FS_COLLECTION_GROCERY_LISTS)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)
    mock_array_union.assert_called_once_with(items_to_add)
    mock_firestore_db["document"].set.assert_called_once_with({'items': "ArrayUnionObjectBread"}, merge=True)

async def test_add_to_grocery_list_firestore_error(mock_firestore_db):
    items_to_add = ['coffee']
    mock_firestore_db["document"].set.side_effect = Exception("Firestore boom!")

    result = await gs.add_to_grocery_list(TEST_USER_ID, items_to_add)

    assert result is False
    mock_firestore_db["client"].collection.assert_called_with(config.FS_COLLECTION_GROCERY_LISTS)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)

async def test_delete_grocery_list_existing(mock_firestore_db):
    result = await gs.delete_grocery_list(TEST_USER_ID)

    assert result is True
    mock_firestore_db["client"].collection.assert_called_with(config.FS_COLLECTION_GROCERY_LISTS)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)
    mock_firestore_db["document"].delete.assert_called_once()

async def test_delete_grocery_list_non_existent(mock_firestore_db):
    # Behavior is the same as existing, delete() doesn't raise error if doc missing
    result = await gs.delete_grocery_list(TEST_USER_ID)

    assert result is True
    mock_firestore_db["client"].collection.assert_called_with(config.FS_COLLECTION_GROCERY_LISTS)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)
    mock_firestore_db["document"].delete.assert_called_once()

async def test_delete_grocery_list_firestore_error(mock_firestore_db):
    mock_firestore_db["document"].delete.side_effect = Exception("Firestore boom!")

    result = await gs.delete_grocery_list(TEST_USER_ID)

    assert result is False
    mock_firestore_db["client"].collection.assert_called_with(config.FS_COLLECTION_GROCERY_LISTS)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)


# --- Test classes for handlers and tools remain largely unchanged for this refactoring ---
# They mock out the google_services functions directly, so are not affected by
# how google_services internally implements its Firestore logic.

class TestGroceryListHandlers(unittest.IsolatedAsyncioTestCase):

    async def _create_mock_update_context(self, args=None):
        mock_update = MagicMock(spec=Update)
        mock_user = MagicMock(spec=User)
        mock_user.id = TEST_USER_ID
        mock_update.effective_user = mock_user
        mock_update.message = AsyncMock(spec=Message) 
        mock_update.message.chat = MagicMock(spec=Chat) 
        mock_update.message.chat.id = TEST_USER_ID 

        mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        mock_context.args = args if args is not None else []
        
        return mock_update, mock_context

    @patch('handlers.gs.add_to_grocery_list')
    async def test_glist_add_items_success(self, mock_gs_add):
        mock_gs_add.return_value = True
        items_to_add = ['apples', 'milk']
        mock_update, mock_context = await self._create_mock_update_context(args=items_to_add)

        await handlers.glist_add(mock_update, mock_context)

        mock_gs_add.assert_awaited_once_with(TEST_USER_ID, items_to_add)
        mock_update.message.reply_text.assert_called_once_with(
            f"Added: {', '.join(items_to_add)} to your grocery list."
        )

    @patch('handlers.gs.add_to_grocery_list')
    async def test_glist_add_items_failure(self, mock_gs_add):
        mock_gs_add.return_value = False
        items_to_add = ['bad_item']
        mock_update, mock_context = await self._create_mock_update_context(args=items_to_add)

        await handlers.glist_add(mock_update, mock_context)

        mock_gs_add.assert_awaited_once_with(TEST_USER_ID, items_to_add)
        mock_update.message.reply_text.assert_called_once_with(
            "Sorry, there was a problem adding items to your grocery list."
        )

    @patch('handlers.gs.add_to_grocery_list')
    async def test_glist_add_no_items(self, mock_gs_add):
        mock_update, mock_context = await self._create_mock_update_context(args=[]) 

        await handlers.glist_add(mock_update, mock_context)

        mock_gs_add.assert_not_called()
        mock_update.message.reply_text.assert_called_once_with(
            "Please provide items to add. Usage: /glist_add item1 item2 ..."
        )

    @patch('handlers.gs.get_grocery_list')
    async def test_glist_show_with_items(self, mock_gs_get):
        items = ['apples', 'bananas <script>alert("xss")</script>']
        escaped_items = [html.escape(item) for item in items]
        mock_gs_get.return_value = items
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_show(mock_update, mock_context)

        mock_gs_get.assert_awaited_once_with(TEST_USER_ID)
        expected_message = "🛒 Your Grocery List:\n" + "\n".join([f"- {item}" for item in escaped_items])
        mock_update.message.reply_text.assert_called_once_with(expected_message, parse_mode=ParseMode.HTML)

    @patch('handlers.gs.get_grocery_list')
    async def test_glist_show_empty_list(self, mock_gs_get):
        mock_gs_get.return_value = [] 
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_show(mock_update, mock_context)

        mock_gs_get.assert_awaited_once_with(TEST_USER_ID)
        mock_update.message.reply_text.assert_called_once_with(
            "🛒 Your grocery list is empty! Add items with /glist_add item1 item2 ..."
        )

    @patch('handlers.gs.get_grocery_list')
    async def test_glist_show_error(self, mock_gs_get):
        mock_gs_get.return_value = None 
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_show(mock_update, mock_context)

        mock_gs_get.assert_awaited_once_with(TEST_USER_ID)
        mock_update.message.reply_text.assert_called_once_with(
            "Sorry, there was an error trying to get your grocery list."
        )

    @patch('handlers.gs.delete_grocery_list')
    async def test_glist_clear_success(self, mock_gs_delete):
        mock_gs_delete.return_value = True
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_clear(mock_update, mock_context)

        mock_gs_delete.assert_awaited_once_with(TEST_USER_ID)
        mock_update.message.reply_text.assert_called_once_with(
            "🗑️ Your grocery list has been cleared."
        )

    @patch('handlers.gs.delete_grocery_list')
    async def test_glist_clear_failure(self, mock_gs_delete):
        mock_gs_delete.return_value = False
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_clear(mock_update, mock_context)

        mock_gs_delete.assert_awaited_once_with(TEST_USER_ID)
        mock_update.message.reply_text.assert_called_once_with(
            "Sorry, there was a problem clearing your grocery list."
        )

class TestGroceryListLLMTools(unittest.TestCase):

    def setUp(self):
        self.mock_user_id = TEST_USER_ID
        self.mock_user_timezone_str = TEST_USER_TIMEZONE

    # --- Tests for AddGroceryItemTool ---
    # NOTE: Tool._run methods are synchronous. If they call async gs functions,
    # they would need to use asyncio.run() or be run in a thread, which is beyond this refactor.
    # For now, we'll mock the gs functions as AsyncMock and assume the tool handles the async call if needed.
    # If the tool directly calls the async function without await/asyncio.run, these tests would fail
    # or the tool itself would error. This refactoring focuses on gs.py and its direct callers in handlers.
    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list', new_callable=AsyncMock)
    async def test_add_item_tool_run_success(self, mock_gs_add):
        mock_gs_add.return_value = True
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        # Assuming tool._run internally handles calling the async gs.add_to_grocery_list
        # For this test, we'll assume it has to be run in an event loop or the tool itself uses asyncio.run
        # This test might need to be run with asyncio.run(tool._run(...)) if tool._run becomes async
        # or if it uses asyncio.run internally, this direct call is fine for testing the mock.
        # For now, let's assume the tool's _run method isn't changing to async def.
        # The mock will check if the (now async) gs function was awaited.
        result = tool._run("milk, eggs") # This call itself is sync
        mock_gs_add.assert_awaited_once_with(self.mock_user_id, ['milk', 'eggs'])
        self.assertEqual(result, "Successfully added: milk, eggs to your grocery list.")

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list', new_callable=AsyncMock)
    async def test_add_item_tool_run_with_spaces(self, mock_gs_add):
        mock_gs_add.return_value = True
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        tool._run("  cheese  , bread  ")
        mock_gs_add.assert_awaited_once_with(self.mock_user_id, ['cheese', 'bread'])

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list', new_callable=AsyncMock)
    async def test_add_item_tool_run_single_item(self, mock_gs_add):
        mock_gs_add.return_value = True
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        tool._run("apples")
        mock_gs_add.assert_awaited_once_with(self.mock_user_id, ['apples'])

    def test_add_item_tool_run_empty_string(self):
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run("")
        self.assertEqual(result, "Input error: No valid items provided after parsing. Please provide items like 'milk, eggs'.")

    def test_add_item_tool_run_only_comma(self):
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run(",")
        self.assertEqual(result, "Input error: No valid items provided after parsing. Please provide items like 'milk, eggs'.")
    
    def test_add_item_tool_run_input_error_none(self): # Test for non-string input as per tool's initial check
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run(None)
        self.assertEqual(result, "Input error: Please provide items as a comma-separated string.")

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list', new_callable=AsyncMock)
    async def test_add_item_tool_run_service_failure(self, mock_gs_add):
        mock_gs_add.return_value = False
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run("milk") # Tool's _run is sync
        self.assertEqual(result, "Failed to add items to the grocery list due to a service error.")

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list', new_callable=AsyncMock)
    async def test_add_item_tool_run_service_exception(self, mock_gs_add):
        mock_gs_add.side_effect = Exception("GS Boom!")
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run("milk") # Tool's _run is sync
        self.assertEqual(result, "An unexpected error occurred while trying to add items.")

    def test_add_item_tool_args_schema(self):
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        self.assertEqual(tool.args_schema, AddGroceryItemToolInput)

    # --- Tests for ShowGroceryListTool ---
    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list', new_callable=AsyncMock)
    async def test_show_list_tool_run_with_items(self, mock_gs_get):
        mock_gs_get.return_value = ['milk', 'bread']
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run() # Tool's _run is sync
        mock_gs_get.assert_awaited_once_with(self.mock_user_id)
        self.assertEqual(result, "Your grocery list: milk, bread.")

    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list', new_callable=AsyncMock)
    async def test_show_list_tool_run_empty_list(self, mock_gs_get):
        mock_gs_get.return_value = []
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run() # Tool's _run is sync
        self.assertEqual(result, "Your grocery list is currently empty.")

    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list', new_callable=AsyncMock)
    async def test_show_list_tool_run_service_error(self, mock_gs_get):
        mock_gs_get.return_value = None
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run() # Tool's _run is sync
        self.assertEqual(result, "Error: Could not retrieve the grocery list at the moment.")

    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list', new_callable=AsyncMock)
    async def test_show_list_tool_run_service_exception(self, mock_gs_get):
        mock_gs_get.side_effect = Exception("GS Boom!")
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run() # Tool's _run is sync
        self.assertEqual(result, "An unexpected error occurred while trying to show the grocery list.")

    # --- Tests for ClearGroceryListTool ---
    @patch('llm.tools.clear_grocery_list_tool.gs.delete_grocery_list', new_callable=AsyncMock)
    async def test_clear_list_tool_run_success(self, mock_gs_delete):
        mock_gs_delete.return_value = True
        tool = ClearGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run() # Tool's _run is sync
        mock_gs_delete.assert_awaited_once_with(self.mock_user_id)
        self.assertEqual(result, "Successfully cleared your grocery list.")

    @patch('llm.tools.clear_grocery_list_tool.gs.delete_grocery_list', new_callable=AsyncMock)
    async def test_clear_list_tool_run_service_failure(self, mock_gs_delete):
        mock_gs_delete.return_value = False
        tool = ClearGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run() # Tool's _run is sync
        self.assertEqual(result, "Failed to clear the grocery list due to a service error.")

    @patch('llm.tools.clear_grocery_list_tool.gs.delete_grocery_list', new_callable=AsyncMock)
    async def test_clear_list_tool_run_service_exception(self, mock_gs_delete):
        mock_gs_delete.side_effect = Exception("GS Boom!")
        tool = ClearGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run() # Tool's _run is sync
        self.assertEqual(result, "An unexpected error occurred while trying to clear the grocery list.")

if __name__ == '__main__':
    unittest.main()
