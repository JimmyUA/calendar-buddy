import unittest
from unittest.mock import patch, AsyncMock # AsyncMock for async gs functions
import asyncio # For running async functions if needed in tests directly

# LLM Tools to test
from llm.tools.add_grocery_item_tool import AddGroceryItemTool, AddGroceryItemToolInput
from llm.tools.show_grocery_list_tool import ShowGroceryListTool, ShowGroceryListToolInput
from llm.tools.clear_grocery_list_tool import ClearGroceryListTool, ClearGroceryListToolInput

# Service layer (to be mocked)
import google_services as gs 

# Common test constants - can be redefined here or imported if made common
TEST_USER_ID_INT = 12345 
TEST_USER_ID_STR = str(TEST_USER_ID_INT)
TEST_USER_TIMEZONE = "America/New_York"


class TestGroceryListLLMTools(unittest.IsolatedAsyncioTestCase): # Use IsolatedAsyncioTestCase for async mocks

    def setUp(self):
        self.user_id_int = TEST_USER_ID_INT
        self.user_id_str = TEST_USER_ID_STR
        self.user_timezone_str = TEST_USER_TIMEZONE

    # Placeholder for tests to be moved and updated
    async def test_example_llm_tool_placeholder(self): # Will be replaced
        self.assertTrue(True)

# Copied and pasted TestGroceryListLLMTools class here.
# It will need updates to its mocks to align with the new gs functions
# (e.g., user_id as str, new function names like clear_grocery_list_items).
# The TEST_USER_ID_INT and TEST_USER_TIMEZONE are defined in this file's constants.

class TestGroceryListLLMTools(unittest.TestCase): # Should be IsolatedAsyncioTestCase for async gs mocks

    def setUp(self):
        self.mock_user_id = TEST_USER_ID_INT # Keep as int for tool instantiation if tool expects int
        self.mock_user_id_str = TEST_USER_ID_STR # String version for gs calls
        self.mock_user_timezone_str = TEST_USER_TIMEZONE

    # --- Tests for AddGroceryItemTool ---
    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list', new_callable=AsyncMock)
    async def test_add_item_tool_run_success(self, mock_gs_add):
        mock_gs_add.return_value = True
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        
        # The tool's _run is sync, but it calls an async gs function.
        # The mock_gs_add is AsyncMock, so we can check assert_awaited_once_with.
        # This setup assumes the tool correctly handles calling an async function 
        # from its sync _run method (e.g. by using asyncio.run internally, or if gs.add_to_grocery_list was made sync).
        # For this test, we'll focus on the interaction.
        # If AddGroceryItemTool._run was `async def`, this test method would need `await tool._arun(...)`.
        # Since it's `def _run`, the call is direct.
        
        # The previous subtask updated the tool to pass str(self.user_id)
        result = tool._run("milk, eggs") 
        mock_gs_add.assert_awaited_once_with(self.mock_user_id_str, ['milk', 'eggs'])
        self.assertEqual(result, "Successfully added: milk, eggs to your grocery list.")

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list', new_callable=AsyncMock)
    async def test_add_item_tool_run_with_spaces(self, mock_gs_add):
        mock_gs_add.return_value = True
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        tool._run("  cheese  , bread  ")
        mock_gs_add.assert_awaited_once_with(self.mock_user_id_str, ['cheese', 'bread'])

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list', new_callable=AsyncMock)
    async def test_add_item_tool_run_single_item(self, mock_gs_add):
        mock_gs_add.return_value = True
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        tool._run("apples")
        mock_gs_add.assert_awaited_once_with(self.mock_user_id_str, ['apples'])

    def test_add_item_tool_run_empty_string(self):
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run("")
        self.assertEqual(result, "Input error: No valid items provided after parsing. Please provide items like 'milk, eggs'.")

    def test_add_item_tool_run_only_comma(self):
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run(",")
        self.assertEqual(result, "Input error: No valid items provided after parsing. Please provide items like 'milk, eggs'.")
    
    def test_add_item_tool_run_input_error_none(self):
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run(None)
        self.assertEqual(result, "Input error: Please provide items as a comma-separated string.")

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list', new_callable=AsyncMock)
    async def test_add_item_tool_run_service_failure(self, mock_gs_add):
        mock_gs_add.return_value = False
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run("milk")
        self.assertEqual(result, "Failed to add items to the grocery list due to a service error.")

    @patch('llm.tools.add_grocery_item_tool.gs.add_to_grocery_list', new_callable=AsyncMock)
    async def test_add_item_tool_run_service_exception(self, mock_gs_add):
        mock_gs_add.side_effect = Exception("GS Boom!")
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run("milk")
        self.assertEqual(result, "An unexpected error occurred while trying to add items.")

    def test_add_item_tool_args_schema(self): # This test is fine as is
        tool = AddGroceryItemTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        self.assertEqual(tool.args_schema, AddGroceryItemToolInput)

    # --- Tests for ShowGroceryListTool ---
    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list', new_callable=AsyncMock)
    async def test_show_list_tool_run_with_items(self, mock_gs_get):
        mock_gs_get.return_value = ['milk', 'bread']
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run()
        mock_gs_get.assert_awaited_once_with(self.mock_user_id_str) # user_id is str
        # Description was updated to "primary grocery list"
        self.assertEqual(result, "Your primary grocery list contains: milk, bread.")


    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list', new_callable=AsyncMock)
    async def test_show_list_tool_run_empty_list(self, mock_gs_get):
        mock_gs_get.return_value = []
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run()
        self.assertEqual(result, "Your primary grocery list is currently empty.")

    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list', new_callable=AsyncMock)
    async def test_show_list_tool_run_service_error_returns_none(self, mock_gs_get):
        mock_gs_get.return_value = None # gs.get_grocery_list might return None on error
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run()
        self.assertEqual(result, "Error: Could not retrieve your primary grocery list at the moment.")

    @patch('llm.tools.show_grocery_list_tool.gs.get_grocery_list', new_callable=AsyncMock)
    async def test_show_list_tool_run_service_exception(self, mock_gs_get):
        mock_gs_get.side_effect = Exception("GS Boom!")
        tool = ShowGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run()
        self.assertEqual(result, "An unexpected error occurred while trying to show the grocery list.")

    # --- Tests for ClearGroceryListTool ---
    # Updated to mock gs.clear_grocery_list_items
    @patch('llm.tools.clear_grocery_list_tool.gs.clear_grocery_list_items', new_callable=AsyncMock)
    async def test_clear_list_tool_run_success(self, mock_gs_clear_items):
        mock_gs_clear_items.return_value = True
        tool = ClearGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run()
        mock_gs_clear_items.assert_awaited_once_with(self.mock_user_id_str, list_id=None)
        self.assertEqual(result, "Successfully cleared items from your primary grocery list.")

    @patch('llm.tools.clear_grocery_list_tool.gs.clear_grocery_list_items', new_callable=AsyncMock)
    async def test_clear_list_tool_run_service_failure(self, mock_gs_clear_items):
        mock_gs_clear_items.return_value = False
        tool = ClearGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run()
        self.assertEqual(result, "Failed to clear items from the grocery list. You might not have an owned list or a service error occurred.")

    @patch('llm.tools.clear_grocery_list_tool.gs.clear_grocery_list_items', new_callable=AsyncMock)
    async def test_clear_list_tool_run_service_exception(self, mock_gs_clear_items):
        mock_gs_clear_items.side_effect = Exception("GS Boom!")
        tool = ClearGroceryListTool(user_id=self.mock_user_id, user_timezone_str=self.mock_user_timezone_str)
        result = tool._run()
        self.assertEqual(result, "An unexpected error occurred while trying to clear the grocery list.")

if __name__ == '__main__':
    unittest.main()
