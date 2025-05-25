import unittest
from unittest.mock import patch, MagicMock, AsyncMock, call # Ensure call is imported

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

class TestGroceryListGoogleServices(unittest.TestCase):

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    def test_get_grocery_list_existing(self, mock_collection):
        mock_doc_ref = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {'items': ['apples', 'bananas']}
        mock_doc_ref.get.return_value = mock_snapshot
        mock_collection.document.return_value = mock_doc_ref

        result = gs.get_grocery_list(TEST_USER_ID)
        self.assertEqual(result, ['apples', 'bananas'])
        mock_collection.document.assert_called_once_with(TEST_USER_ID_STR)
        mock_doc_ref.get.assert_called_once()

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    def test_get_grocery_list_no_list(self, mock_collection):
        mock_doc_ref = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.exists = False
        mock_doc_ref.get.return_value = mock_snapshot
        mock_collection.document.return_value = mock_doc_ref

        result = gs.get_grocery_list(TEST_USER_ID)
        self.assertEqual(result, []) # Should return empty list
        mock_collection.document.assert_called_once_with(TEST_USER_ID_STR)
        mock_doc_ref.get.assert_called_once()

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    def test_get_grocery_list_no_items_field(self, mock_collection):
        mock_doc_ref = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {'other_field': 'value'} # No 'items'
        mock_doc_ref.get.return_value = mock_snapshot
        mock_collection.document.return_value = mock_doc_ref

        result = gs.get_grocery_list(TEST_USER_ID)
        self.assertIsNone(result)
        mock_collection.document.assert_called_once_with(TEST_USER_ID_STR)

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    def test_get_grocery_list_items_not_list(self, mock_collection):
        mock_doc_ref = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {'items': 'not-a-list'}
        mock_doc_ref.get.return_value = mock_snapshot
        mock_collection.document.return_value = mock_doc_ref

        result = gs.get_grocery_list(TEST_USER_ID)
        self.assertIsNone(result)
        mock_collection.document.assert_called_once_with(TEST_USER_ID_STR)

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    def test_get_grocery_list_firestore_error(self, mock_collection):
        mock_doc_ref = MagicMock()
        mock_doc_ref.get.side_effect = Exception("Firestore boom!")
        mock_collection.document.return_value = mock_doc_ref

        result = gs.get_grocery_list(TEST_USER_ID)
        self.assertIsNone(result)
        mock_collection.document.assert_called_once_with(TEST_USER_ID_STR)

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    @patch('google_services.firestore.ArrayUnion') # To verify its usage
    def test_add_to_grocery_list_new(self, mock_array_union, mock_collection):
        mock_doc_ref = MagicMock()
        mock_collection.document.return_value = mock_doc_ref
        items_to_add = ['milk', 'eggs']
        mock_array_union.return_value = "ArrayUnionObject" # Mock the return of ArrayUnion

        result = gs.add_to_grocery_list(TEST_USER_ID, items_to_add)
        self.assertTrue(result)
        mock_collection.document.assert_called_once_with(TEST_USER_ID_STR)
        mock_array_union.assert_called_once_with(items_to_add)
        mock_doc_ref.set.assert_called_once_with({'items': "ArrayUnionObject"}, merge=True)

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    @patch('google_services.firestore.ArrayUnion')
    def test_add_to_grocery_list_existing(self, mock_array_union, mock_collection):
        mock_doc_ref = MagicMock()
        mock_collection.document.return_value = mock_doc_ref
        items_to_add = ['bread']
        mock_array_union.return_value = "ArrayUnionObjectBread"

        result = gs.add_to_grocery_list(TEST_USER_ID, items_to_add)
        self.assertTrue(result)
        mock_collection.document.assert_called_once_with(TEST_USER_ID_STR)
        mock_array_union.assert_called_once_with(items_to_add)
        mock_doc_ref.set.assert_called_once_with({'items': "ArrayUnionObjectBread"}, merge=True)

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    def test_add_to_grocery_list_firestore_error(self, mock_collection):
        mock_doc_ref = MagicMock()
        mock_doc_ref.set.side_effect = Exception("Firestore boom!")
        mock_collection.document.return_value = mock_doc_ref
        items_to_add = ['coffee']

        result = gs.add_to_grocery_list(TEST_USER_ID, items_to_add)
        self.assertFalse(result)
        mock_collection.document.assert_called_once_with(TEST_USER_ID_STR)

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    def test_delete_grocery_list_existing(self, mock_collection):
        mock_doc_ref = MagicMock()
        mock_collection.document.return_value = mock_doc_ref

        result = gs.delete_grocery_list(TEST_USER_ID)
        self.assertTrue(result)
        mock_collection.document.assert_called_once_with(TEST_USER_ID_STR)
        mock_doc_ref.delete.assert_called_once()

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    def test_delete_grocery_list_non_existent(self, mock_collection):
        mock_doc_ref = MagicMock()
        mock_collection.document.return_value = mock_doc_ref

        result = gs.delete_grocery_list(TEST_USER_ID)
        self.assertTrue(result)
        mock_collection.document.assert_called_once_with(TEST_USER_ID_STR)
        mock_doc_ref.delete.assert_called_once()

    @patch('google_services.FS_COLLECTION_GROCERY_LISTS')
    def test_delete_grocery_list_firestore_error(self, mock_collection):
        mock_doc_ref = MagicMock()
        mock_doc_ref.delete.side_effect = Exception("Firestore boom!")
        mock_collection.document.return_value = mock_doc_ref

        result = gs.delete_grocery_list(TEST_USER_ID)
        self.assertFalse(result)
        mock_collection.document.assert_called_once_with(TEST_USER_ID_STR)

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

        mock_gs_add.assert_called_once_with(TEST_USER_ID, items_to_add)
        mock_update.message.reply_text.assert_called_once_with(
            f"Added: {', '.join(items_to_add)} to your grocery list."
        )

    @patch('handlers.gs.add_to_grocery_list')
    async def test_glist_add_items_failure(self, mock_gs_add):
        mock_gs_add.return_value = False
        items_to_add = ['bad_item']
        mock_update, mock_context = await self._create_mock_update_context(args=items_to_add)

        await handlers.glist_add(mock_update, mock_context)

        mock_gs_add.assert_called_once_with(TEST_USER_ID, items_to_add)
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

        mock_gs_get.assert_called_once_with(TEST_USER_ID)
        expected_message = "🛒 Your Grocery List:\n" + "\n".join([f"- {item}" for item in escaped_items])
        mock_update.message.reply_text.assert_called_once_with(expected_message, parse_mode=ParseMode.HTML)

    @patch('handlers.gs.get_grocery_list')
    async def test_glist_show_empty_list(self, mock_gs_get):
        mock_gs_get.return_value = [] 
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_show(mock_update, mock_context)

        mock_gs_get.assert_called_once_with(TEST_USER_ID)
        mock_update.message.reply_text.assert_called_once_with(
            "🛒 Your grocery list is empty! Add items with /glist_add item1 item2 ..."
        )

    @patch('handlers.gs.get_grocery_list')
    async def test_glist_show_error(self, mock_gs_get):
        mock_gs_get.return_value = None 
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_show(mock_update, mock_context)

        mock_gs_get.assert_called_once_with(TEST_USER_ID)
        mock_update.message.reply_text.assert_called_once_with(
            "Sorry, there was an error trying to get your grocery list."
        )

    @patch('handlers.gs.delete_grocery_list')
    async def test_glist_clear_success(self, mock_gs_delete):
        mock_gs_delete.return_value = True
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_clear(mock_update, mock_context)

        mock_gs_delete.assert_called_once_with(TEST_USER_ID)
        mock_update.message.reply_text.assert_called_once_with(
            "🗑️ Your grocery list has been cleared."
        )

    @patch('handlers.gs.delete_grocery_list')
    async def test_glist_clear_failure(self, mock_gs_delete):
        mock_gs_delete.return_value = False
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_clear(mock_update, mock_context)

        mock_gs_delete.assert_called_once_with(TEST_USER_ID)
        mock_update.message.reply_text.assert_called_once_with(
            "Sorry, there was a problem clearing your grocery list."
        )

class TestGroceryListLLMTools(unittest.TestCase):

    def setUp(self):
        self.mock_user_id = TEST_USER_ID
        self.mock_user_timezone_str = TEST_USER_TIMEZONE

    # --- Tests for AddGroceryItemTool ---
    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list')
    def test_add_item_tool_run_success(self, mock_gs_add):
        mock_gs_add.return_value = True
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run("milk, eggs")
        mock_gs_add.assert_called_once_with(self.mock_user_id, ['milk', 'eggs'])
        self.assertEqual(result, "Successfully added: milk, eggs to your grocery list.")

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list')
    def test_add_item_tool_run_with_spaces(self, mock_gs_add):
        mock_gs_add.return_value = True
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        tool._run("  cheese  , bread  ")
        mock_gs_add.assert_called_once_with(self.mock_user_id, ['cheese', 'bread'])

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list')
    def test_add_item_tool_run_single_item(self, mock_gs_add):
        mock_gs_add.return_value = True
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        tool._run("apples")
        mock_gs_add.assert_called_once_with(self.mock_user_id, ['apples'])

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

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list')
    def test_add_item_tool_run_service_failure(self, mock_gs_add):
        mock_gs_add.return_value = False
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run("milk")
        self.assertEqual(result, "Failed to add items to the grocery list due to a service error.")

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list')
    def test_add_item_tool_run_service_exception(self, mock_gs_add):
        mock_gs_add.side_effect = Exception("GS Boom!")
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run("milk")
        self.assertEqual(result, "An unexpected error occurred while trying to add items.")

    def test_add_item_tool_args_schema(self):
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        self.assertEqual(tool.args_schema, AddGroceryItemToolInput)

    # --- Tests for ShowGroceryListTool ---
    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list')
    def test_show_list_tool_run_with_items(self, mock_gs_get):
        mock_gs_get.return_value = ['milk', 'bread']
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run()
        mock_gs_get.assert_called_once_with(self.mock_user_id)
        self.assertEqual(result, "Your grocery list: milk, bread.")

    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list')
    def test_show_list_tool_run_empty_list(self, mock_gs_get):
        mock_gs_get.return_value = []
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run()
        self.assertEqual(result, "Your grocery list is currently empty.")

    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list')
    def test_show_list_tool_run_service_error(self, mock_gs_get):
        mock_gs_get.return_value = None
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run()
        self.assertEqual(result, "Error: Could not retrieve the grocery list at the moment.")

    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list')
    def test_show_list_tool_run_service_exception(self, mock_gs_get):
        mock_gs_get.side_effect = Exception("GS Boom!")
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run()
        self.assertEqual(result, "An unexpected error occurred while trying to show the grocery list.")

    # --- Tests for ClearGroceryListTool ---
    @patch('llm.tools.clear_grocery_list_tool.gs.delete_grocery_list')
    def test_clear_list_tool_run_success(self, mock_gs_delete):
        mock_gs_delete.return_value = True
        tool = ClearGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run()
        mock_gs_delete.assert_called_once_with(self.mock_user_id)
        self.assertEqual(result, "Successfully cleared your grocery list.")

    @patch('llm.tools.clear_grocery_list_tool.gs.delete_grocery_list')
    def test_clear_list_tool_run_service_failure(self, mock_gs_delete):
        mock_gs_delete.return_value = False
        tool = ClearGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run()
        self.assertEqual(result, "Failed to clear the grocery list due to a service error.")

    @patch('llm.tools.clear_grocery_list_tool.gs.delete_grocery_list')
    def test_clear_list_tool_run_service_exception(self, mock_gs_delete):
        mock_gs_delete.side_effect = Exception("GS Boom!")
        tool = ClearGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        result = tool._run()
        self.assertEqual(result, "An unexpected error occurred while trying to clear the grocery list.")

if __name__ == '__main__':
    unittest.main()
