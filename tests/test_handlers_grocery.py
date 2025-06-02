import unittest
from unittest.mock import patch, MagicMock, AsyncMock, call
import asyncio

# Telegram specific imports
from telegram import Update, User, Message, Chat, CallbackQuery
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

# Modules to test
import handlers # Assuming your handlers are in handlers.py or a handlers package
import google_services as gs # To mock gs functions called by handlers
from models import GroceryList, GroceryListShareRequest # For constructing mock return values from gs

# Common test constants
TEST_USER_ID = 123456 # Integer, as typically used in handlers from effective_user.id
TEST_USER_ID_STR = str(TEST_USER_ID) # String version for gs calls
TEST_OTHER_USER_ID = 654321
TEST_OTHER_USER_ID_STR = str(TEST_OTHER_USER_ID)
TEST_LIST_ID = "list_xyz_789"
TEST_REQUEST_ID = "req_abc_123"
TEST_USER_FIRST_NAME = "TestUser"


class TestGroceryHandlers(unittest.IsolatedAsyncioTestCase):

    async def _create_mock_update_context(self, text_message: str = None, callback_data: str = None, command_args: list = None, user_id: int = TEST_USER_ID, first_name: str = TEST_USER_FIRST_NAME):
        mock_update = AsyncMock(spec=Update)
        mock_user = AsyncMock(spec=User)
        mock_user.id = user_id
        mock_user.first_name = first_name
        mock_user.username = f"{first_name}Username"
        mock_update.effective_user = mock_user
        
        mock_message = AsyncMock(spec=Message)
        mock_message.from_user = mock_user # For users_shared_handler
        mock_message.text = text_message
        mock_message.chat = AsyncMock(spec=Chat)
        mock_message.chat.id = user_id # Simulate private chat
        mock_update.message = mock_message

        if callback_data:
            mock_update.callback_query = AsyncMock(spec=CallbackQuery)
            mock_update.callback_query.data = callback_data
            mock_update.callback_query.from_user = mock_user
            mock_update.callback_query.message = mock_message # For edit_message_text

        mock_context = AsyncMock(spec=ContextTypes.DEFAULT_TYPE)
        mock_context.args = command_args if command_args is not None else []
        mock_context.user_data = {} # Initialize user_data
        mock_context.bot = AsyncMock() # Mock the bot attribute

        # Mock users_shared for KeyboardButtonRequestUsers response
        # This part will be populated specifically in tests that need it.
        mock_update.message.users_shared = None 
        
        return mock_update, mock_context

    # Placeholder for tests to be moved and added
    async def test_example_handler_placeholder(self): # Will be replaced by actual tests
        self.assertTrue(True)

# Copied and pasted TestGroceryListHandlers class here.
# It will need significant updates to use the new _create_mock_update_context,
# mock the new gs function signatures, and test new behaviors (like glist_show with shared lists).
# TEST_USER_ID is defined in this file's constants.
# TEST_USER_ID_STR will also be from this file.

class TestGroceryListHandlers(unittest.IsolatedAsyncioTestCase):

    async def _create_mock_update_context(self, args=None, user_id=TEST_USER_ID): # Adjusted to use local TEST_USER_ID
        mock_update = MagicMock(spec=Update) # Should be AsyncMock for handler tests
        mock_user = MagicMock(spec=User) # Should be AsyncMock
        mock_user.id = user_id
        mock_update.effective_user = mock_user
        mock_update.message = AsyncMock(spec=Message) 
        mock_update.message.chat = MagicMock(spec=Chat) 
        mock_update.message.chat.id = user_id

        mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE) # Should be AsyncMock
        mock_context.args = args if args is not None else []
        # Ensure user_data is initialized for each test if the handler uses it
        mock_context.user_data = {}
        mock_context.bot = AsyncMock() # Add bot mock
        
        return mock_update, mock_context

    @patch('handlers.gs.add_to_grocery_list')
    async def test_glist_add_items_success(self, mock_gs_add):
        mock_gs_add.return_value = True
        items_to_add = ['apples', 'milk']
        # Use the helper from the TestGroceryHandlers class (needs to be part of it or self._create_mock_update_context)
        mock_update, mock_context = await self._create_mock_update_context(args=items_to_add)


        await handlers.glist_add(mock_update, mock_context)

        # User ID passed to gs function should be string
        mock_gs_add.assert_awaited_once_with(str(TEST_USER_ID), items_to_add) 
        mock_update.message.reply_text.assert_called_once_with(
            f"Added: {', '.join(items_to_add)} to your grocery list."
        )

    @patch('handlers.gs.add_to_grocery_list')
    async def test_glist_add_items_failure(self, mock_gs_add):
        mock_gs_add.return_value = False
        items_to_add = ['bad_item']
        mock_update, mock_context = await self._create_mock_update_context(args=items_to_add)

        await handlers.glist_add(mock_update, mock_context)

        mock_gs_add.assert_awaited_once_with(str(TEST_USER_ID), items_to_add)
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

    # test_glist_show needs significant rework for owned and shared lists.
    @patch('handlers.gs.get_user_owned_grocery_lists', new_callable=AsyncMock)
    @patch('handlers.gs.get_shared_grocery_lists_for_user', new_callable=AsyncMock)
    async def test_glist_show_owned_and_shared_lists(self, mock_get_shared, mock_get_owned):
        # This is a new test based on updated glist_show logic
        mock_get_owned.return_value = [{'id': 'owned1', 'items': ['milk', 'eggs'], 'owner_id': TEST_USER_ID_STR}]
        mock_get_shared.return_value = [{'id': 'shared1', 'items': ['cheese'], 'owner_id': 'owner2'}]
        
        mock_update, mock_context = await self._create_mock_update_context()
        await handlers.glist_show(mock_update, mock_context)

        mock_get_owned.assert_awaited_once_with(TEST_USER_ID_STR)
        mock_get_shared.assert_awaited_once_with(TEST_USER_ID_STR)
        
        # Basic check, detailed formatting can be more specific
        call_args = mock_update.message.reply_text.call_args
        self.assertIn("Your Grocery List", call_args[0][0])
        self.assertIn("milk", call_args[0][0])
        self.assertIn("Shared Grocery Lists", call_args[0][0])
        self.assertIn("cheese", call_args[0][0])
        self.assertEqual(call_args[1]['parse_mode'], ParseMode.HTML)


    # Removed old glist_show test placeholders

    @patch('handlers.gs.get_user_owned_grocery_lists', new_callable=AsyncMock)
    @patch('handlers.gs.get_shared_grocery_lists_for_user', new_callable=AsyncMock)
    async def test_glist_show_only_owned_list_not_empty(self, mock_get_shared, mock_get_owned):
        mock_get_owned.return_value = [{'id': 'owned1', 'items': ['milk', 'eggs'], 'owner_id': TEST_USER_ID_STR}]
        mock_get_shared.return_value = []
        mock_update, mock_context = await self._create_mock_update_context()
        await handlers.glist_show(mock_update, mock_context)
        
        call_args = mock_update.message.reply_text.call_args
        self.assertIn("Your Grocery List", call_args[0][0])
        self.assertNotIn("Shared Grocery Lists", call_args[0][0])
        self.assertIn("milk", call_args[0][0])

    @patch('handlers.gs.get_user_owned_grocery_lists', new_callable=AsyncMock)
    @patch('handlers.gs.get_shared_grocery_lists_for_user', new_callable=AsyncMock)
    async def test_glist_show_only_shared_list_not_empty(self, mock_get_shared, mock_get_owned):
        mock_get_owned.return_value = []
        mock_get_shared.return_value = [{'id': 'shared1', 'items': ['cheese'], 'owner_id': TEST_OTHER_USER_ID_STR}]
        mock_update, mock_context = await self._create_mock_update_context()
        await handlers.glist_show(mock_update, mock_context)

        call_args = mock_update.message.reply_text.call_args
        self.assertNotIn("Your Grocery List", call_args[0][0])
        self.assertIn("Shared Grocery Lists", call_args[0][0])
        self.assertIn(f"from User {TEST_OTHER_USER_ID_STR}", call_args[0][0])
        self.assertIn("cheese", call_args[0][0])

    @patch('handlers.gs.get_user_owned_grocery_lists', new_callable=AsyncMock)
    @patch('handlers.gs.get_shared_grocery_lists_for_user', new_callable=AsyncMock)
    async def test_glist_show_no_lists_at_all(self, mock_get_shared, mock_get_owned):
        mock_get_owned.return_value = []
        mock_get_shared.return_value = []
        mock_update, mock_context = await self._create_mock_update_context()
        await handlers.glist_show(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once_with(
            "🛒 Your grocery list is empty, and no lists are shared with you! "
            "Add items with `/glist_add <item>` or ask someone to `/glist_share` with you."
        )

    @patch('handlers.gs.get_user_owned_grocery_lists', new_callable=AsyncMock)
    @patch('handlers.gs.get_shared_grocery_lists_for_user', new_callable=AsyncMock)
    async def test_glist_show_owned_list_empty_shared_list_empty(self, mock_get_shared, mock_get_owned):
        mock_get_owned.return_value = [{'id': 'owned1', 'items': [], 'owner_id': TEST_USER_ID_STR}]
        mock_get_shared.return_value = [{'id': 'shared1', 'items': [], 'owner_id': TEST_OTHER_USER_ID_STR}]
        mock_update, mock_context = await self._create_mock_update_context()
        await handlers.glist_show(mock_update, mock_context)

        call_args = mock_update.message.reply_text.call_args
        self.assertIn("Your Grocery List is empty", call_args[0][0])
        self.assertIn(f"Shared List (ID: shared1) from User {TEST_OTHER_USER_ID_STR} is empty", call_args[0][0])


    @patch('handlers.gs.clear_grocery_list_items') # Patched to new function name
    async def test_glist_clear_success(self, mock_gs_clear):
        mock_gs_clear.return_value = True
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_clear(mock_update, mock_context)

        mock_gs_clear.assert_awaited_once_with(str(TEST_USER_ID), list_id=None) # Verify new call
        mock_update.message.reply_text.assert_called_once_with(
            "🗑️ Items from your primary grocery list have been cleared." # Updated message
        )

    @patch('handlers.gs.clear_grocery_list_items') # Patched to new function name
    async def test_glist_clear_failure(self, mock_gs_clear):
        mock_gs_clear.return_value = False
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_clear(mock_update, mock_context)

        mock_gs_clear.assert_awaited_once_with(str(TEST_USER_ID), list_id=None) # Verify new call
        mock_update.message.reply_text.assert_called_once_with(
             "Sorry, there was a problem clearing your grocery list. "
            "You might not have an owned list, or an unexpected error occurred." # Updated message
        )

    # --- Tests for /glist_share ---
    @patch('handlers.gs.get_user_owned_grocery_lists', new_callable=AsyncMock)
    async def test_glist_share_start_no_owned_list(self, mock_get_owned_lists):
        mock_get_owned_lists.return_value = [] # User has no owned lists
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_share_start(mock_update, mock_context)

        mock_get_owned_lists.assert_awaited_once_with(TEST_USER_ID_STR)
        mock_update.message.reply_text.assert_called_once_with(
            "You don't have a grocery list to share. Create one first using `/glist_add <item>`."
        )
        self.assertNotIn(handlers.GLIST_SHARE_LIST_ID_KEY, mock_context.user_data)

    @patch('handlers.gs.get_user_owned_grocery_lists', new_callable=AsyncMock)
    async def test_glist_share_start_has_owned_list(self, mock_get_owned_lists):
        owned_list_data = [{'id': TEST_LIST_ID, 'items': ['item1'], 'owner_id': TEST_USER_ID_STR}]
        mock_get_owned_lists.return_value = owned_list_data
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_share_start(mock_update, mock_context)

        mock_get_owned_lists.assert_awaited_once_with(TEST_USER_ID_STR)
        self.assertEqual(mock_context.user_data[handlers.GLIST_SHARE_LIST_ID_KEY], TEST_LIST_ID)
        self.assertIn(handlers.GLIST_SHARE_SELECT_USER_REQUEST_ID_KEY, mock_context.user_data)
        
        # Check that reply_text was called with a ReplyKeyboardMarkup containing KeyboardButtonRequestUsers
        mock_update.message.reply_text.assert_called_once()
        call_args_list = mock_update.message.reply_text.call_args_list
        args, kwargs = call_args_list[0]
        self.assertIn("Please select the user you want to share this list with", args[0])
        self.assertIsNotNone(kwargs.get('reply_markup'))
        
        reply_markup = kwargs['reply_markup']
        self.assertIsInstance(reply_markup, handlers.ReplyKeyboardMarkup)
        button = reply_markup.keyboard[0][0]
        self.assertIsInstance(button, handlers.KeyboardButton)
        self.assertIsNotNone(button.request_users)
        self.assertEqual(button.request_users.request_id, mock_context.user_data[handlers.GLIST_SHARE_SELECT_USER_REQUEST_ID_KEY])

    @patch('handlers.gs.get_user_owned_grocery_lists', new_callable=AsyncMock)
    async def test_glist_share_start_owned_list_missing_id(self, mock_get_owned_lists):
        # Simulate a list returned from gs that's missing an 'id' for some reason
        owned_list_data = [{'items': ['item1'], 'owner_id': TEST_USER_ID_STR}] # No 'id'
        mock_get_owned_lists.return_value = owned_list_data
        mock_update, mock_context = await self._create_mock_update_context()

        await handlers.glist_share_start(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once_with(
            "There was an issue identifying your grocery list. Please try again."
        )
        self.assertNotIn(handlers.GLIST_SHARE_LIST_ID_KEY, mock_context.user_data)

    # --- Tests for users_shared_handler (glist part) ---
    @patch('handlers.gs.create_grocery_list_share_request', new_callable=AsyncMock)
    async def test_users_shared_handler_glist_share_success(self, mock_create_share_request):
        mock_update, mock_context = await self._create_mock_update_context()
        
        # Setup context for glist share
        requester_id_str = TEST_USER_ID_STR
        requester_name = TEST_USER_FIRST_NAME
        mock_update.effective_user.id = TEST_USER_ID # Requester
        mock_update.effective_user.first_name = requester_name
        
        list_id_to_share = "list123_owned"
        glist_share_kb_request_id = 123456789
        mock_context.user_data[handlers.GLIST_SHARE_LIST_ID_KEY] = list_id_to_share
        mock_context.user_data[handlers.GLIST_SHARE_SELECT_USER_REQUEST_ID_KEY] = glist_share_kb_request_id

        # Simulate UsersShared object from Telegram
        mock_users_shared = MagicMock()
        mock_users_shared.request_id = glist_share_kb_request_id
        shared_user_info = MagicMock(spec=User)
        shared_user_info.user_id = TEST_OTHER_USER_ID
        shared_user_info.first_name = "SharedTarget"
        shared_user_info.username = "sharedtarget_uname"
        mock_users_shared.users = [shared_user_info]
        mock_update.message.users_shared = mock_users_shared
        
        mock_create_share_request.return_value = "new_share_req_doc_id" # Mock successful request creation

        await handlers.users_shared_handler(mock_update, mock_context)

        # Verify gs.create_grocery_list_share_request was called correctly
        mock_create_share_request.assert_awaited_once_with(
            requester_id=requester_id_str,
            requester_name=requester_name,
            target_user_id=str(TEST_OTHER_USER_ID),
            list_id=list_id_to_share
        )
        # Verify message to requester
        self.assertTrue(any("Your request to share the grocery list has been sent" in call_args[0][0] 
                            for call_args in mock_context.bot.send_message.call_args_list 
                            if call_args[1].get('chat_id') == TEST_USER_ID))
        
        # Verify message to target user
        self.assertTrue(any("wants to share their grocery list with you" in call_args[0][0]
                            for call_args in mock_context.bot.send_message.call_args_list
                            if call_args[1].get('chat_id') == TEST_OTHER_USER_ID))
        
        # Verify user_data is cleaned up
        self.assertNotIn(handlers.GLIST_SHARE_LIST_ID_KEY, mock_context.user_data)
        self.assertNotIn(handlers.GLIST_SHARE_SELECT_USER_REQUEST_ID_KEY, mock_context.user_data)

    # --- Tests for button_callback (glist part) ---
    @patch('handlers.gs.update_grocery_list_share_request_status', new_callable=AsyncMock)
    @patch('handlers.gs.get_grocery_list_share_request', new_callable=AsyncMock)
    async def test_button_callback_glist_accept_share_success(self, mock_get_request, mock_update_status):
        callback_data = f"glist_accept_share_{TEST_REQUEST_ID}"
        # User clicking is the target_user_id of the request
        mock_update, mock_context = await self._create_mock_update_context(callback_data=callback_data, user_id=TEST_OTHER_USER_ID)
        
        mock_request_doc = {
            'id': TEST_REQUEST_ID, 'requester_id': TEST_USER_ID_STR, 'target_user_id': TEST_OTHER_USER_ID_STR,
            'list_id': TEST_LIST_ID, 'status': 'pending', 'requester_name': 'OriginalSender'
        }
        mock_get_request.return_value = mock_request_doc
        mock_update_status.return_value = True # Simulate successful status update and sharing

        await handlers.button_callback(mock_update, mock_context)

        mock_get_request.assert_awaited_once_with(TEST_REQUEST_ID)
        mock_update_status.assert_awaited_once_with(TEST_REQUEST_ID, "approved", TEST_OTHER_USER_ID_STR)
        
        mock_update.callback_query.edit_message_text.assert_awaited_once_with(
            "✅ Sharing request accepted! You now have access to the grocery list."
        )
        # Check notification to original requester
        self.assertTrue(any("has ACCEPTED your grocery list sharing request" in call_args[0][0]
                            for call_args in mock_context.bot.send_message.call_args_list
                            if call_args[1].get('chat_id') == TEST_USER_ID_STR))

    @patch('handlers.gs.update_grocery_list_share_request_status', new_callable=AsyncMock)
    @patch('handlers.gs.get_grocery_list_share_request', new_callable=AsyncMock)
    async def test_button_callback_glist_deny_share_success(self, mock_get_request, mock_update_status):
        callback_data = f"glist_deny_share_{TEST_REQUEST_ID}"
        # User clicking is the target_user_id
        mock_update, mock_context = await self._create_mock_update_context(callback_data=callback_data, user_id=TEST_OTHER_USER_ID)

        mock_request_doc = {
            'id': TEST_REQUEST_ID, 'requester_id': TEST_USER_ID_STR, 'target_user_id': TEST_OTHER_USER_ID_STR,
            'list_id': TEST_LIST_ID, 'status': 'pending', 'requester_name': 'OriginalSender'
        }
        mock_get_request.return_value = mock_request_doc
        mock_update_status.return_value = True # Simulate successful status update

        await handlers.button_callback(mock_update, mock_context)

        mock_get_request.assert_awaited_once_with(TEST_REQUEST_ID)
        mock_update_status.assert_awaited_once_with(TEST_REQUEST_ID, "denied", TEST_OTHER_USER_ID_STR)

        mock_update.callback_query.edit_message_text.assert_awaited_once_with(
            "❌ Sharing request denied. The requester has been notified."
        )
        # Check notification to original requester
        self.assertTrue(any("has DENIED your grocery list sharing request" in call_args[0][0]
                            for call_args in mock_context.bot.send_message.call_args_list
                            if call_args[1].get('chat_id') == TEST_USER_ID_STR))

    @patch('handlers.gs.get_grocery_list_share_request', new_callable=AsyncMock)
    async def test_button_callback_glist_share_already_actioned(self, mock_get_request):
        callback_data = f"glist_accept_share_{TEST_REQUEST_ID}"
        mock_update, mock_context = await self._create_mock_update_context(callback_data=callback_data, user_id=TEST_OTHER_USER_ID)
        
        mock_request_doc = {'status': 'approved'} # Already actioned
        mock_get_request.return_value = mock_request_doc

        await handlers.button_callback(mock_update, mock_context)
        mock_update.callback_query.edit_message_text.assert_called_once_with(
            "This share request has already been actioned (status: approved)."
        )

    @patch('handlers.gs.get_grocery_list_share_request', new_callable=AsyncMock)
    async def test_button_callback_glist_share_wrong_user(self, mock_get_request):
        callback_data = f"glist_accept_share_{TEST_REQUEST_ID}"
        # User clicking (TEST_USER_ID) is NOT the target_user_id of the request
        mock_update, mock_context = await self._create_mock_update_context(callback_data=callback_data, user_id=TEST_USER_ID) 
        
        mock_request_doc = {'target_user_id': TEST_OTHER_USER_ID_STR, 'status': 'pending'}
        mock_get_request.return_value = mock_request_doc
        
        await handlers.button_callback(mock_update, mock_context)
        mock_update.callback_query.edit_message_text.assert_called_once_with(
            "Error: This share request is not for you to accept."
        )

if __name__ == '__main__':
    unittest.main()
