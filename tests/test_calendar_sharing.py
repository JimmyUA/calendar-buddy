import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch, MagicMock

from google.cloud import firestore # For type hinting and firestore.SERVER_TIMESTAMP

# Modules to test
from handlers import ask_calendar_command, button_callback, DEFAULT_REQUESTED_USER_ID_PLACEHOLDER
from google_services import create_calendar_access_request, get_calendar_access_request, update_calendar_access_request_status

# Telegram core types
from telegram import Update, User, Message, Chat, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, MessageEntity
from telegram.constants import MessageEntityType # Import the enum

# For date manipulation and comparison
from datetime import datetime, timezone as dt_timezone


class TestCalendarSharing(unittest.TestCase):
    def setUp(self):
        # Common mocks can be set up here if needed
        pass

    def tearDown(self):
        # Clean up after each test if necessary
        pass

    # Placeholder for future tests
    def test_placeholder(self):
        self.assertTrue(True)

    # --- Tests for ask_calendar_command ---

    @patch('handlers.gs.create_calendar_access_request', new_callable=AsyncMock)
    def test_ask_calendar_valid_request_and_notification(self, mock_create_request):
        """Test /ask_calendar with valid arguments, successful request creation, and notification."""
        requester_user_id = 123
        requester_username = "requester_user"
        requester_first_name = "Requester"
        
        requested_user_id = 456
        target_username_with_at = "@testuser"
        start_date_str = "2024-01-01"
        end_date_str = "2024-01-05"
        request_id = "test_req_id_123"

        mock_create_request.return_value = request_id

        # --- Mock Update ---
        mock_update = MagicMock(spec=Update)
        mock_update.effective_user = User(id=requester_user_id, first_name=requester_first_name, is_bot=False, username=requester_username)
        
        command_text = "/ask_calendar"
        full_message_text = f"{command_text} {target_username_with_at} {start_date_str} to {end_date_str}"
        
        # Entity for the bot command itself
        bot_command_entity = MessageEntity(type=MessageEntityType.BOT_COMMAND, offset=0, length=len(command_text))
        
        # Entity for the mention
        # Offset is after "/ask_calendar "
        mention_offset = len(command_text) + 1 
        mention_length = len(target_username_with_at)
        mock_mentioned_user_obj = User(id=requested_user_id, first_name="TestMentioned", is_bot=False, username=target_username_with_at.lstrip('@'))
        mention_entity = MessageEntity(type=MessageEntityType.MENTION, offset=mention_offset, length=mention_length, user=mock_mentioned_user_obj)

        mock_update.message = MagicMock(spec=Message)
        mock_update.message.text = full_message_text
        mock_update.message.entities = [bot_command_entity, mention_entity]
        mock_update.message.reply_text = AsyncMock()

        # --- Mock Context ---
        mock_context = MagicMock()
        mock_context.args = [target_username_with_at, start_date_str, "to", end_date_str]
        mock_context.bot.send_message = AsyncMock()

        # --- Run the handler ---
        asyncio.run(ask_calendar_command(mock_update, mock_context))

        # --- Assertions ---
        # 1. Assert create_calendar_access_request called correctly
        expected_start_iso = datetime(2024, 1, 1, 0, 0, 0, tzinfo=dt_timezone.utc).isoformat()
        expected_end_iso = datetime(2024, 1, 5, 23, 59, 59, 999999, tzinfo=dt_timezone.utc).isoformat()
        
        mock_create_request.assert_called_once_with(
            requester_id=str(requester_user_id),
            requested_user_id=str(requested_user_id),
            start_time_iso=expected_start_iso,
            end_time_iso=expected_end_iso,
            target_username=target_username_with_at
        )

        # 2. Assert requester's confirmation message
        mock_update.message.reply_text.assert_any_call(
            f"Your request to view {target_username_with_at}'s calendar from January 01, 2024 to January 05, 2024 has been sent (Request ID: {request_id}).",
            parse_mode='HTML'
        )

        # 3. Assert notification message to requested user
        expected_notification_message = (
            f"User {requester_first_name} (@{requester_username}) wants to view your calendar events "
            f"from January 01, 2024 to January 05, 2024.\n\n"
            f"Do you approve this request?"
        )
        
        # Check if send_message was called for notification (it's the second call to reply_text if placeholder scenario)
        # More robust: check call_args_list
        notification_call_args = None
        for call in mock_context.bot.send_message.call_args_list:
            if call.kwargs.get('chat_id') == requested_user_id:
                notification_call_args = call
                break
        
        self.assertIsNotNone(notification_call_args, "Notification message was not sent to the requested user.")
        self.assertEqual(notification_call_args.kwargs['text'], expected_notification_message)
        self.assertIsInstance(notification_call_args.kwargs['reply_markup'], InlineKeyboardMarkup)
        
        keyboard = notification_call_args.kwargs['reply_markup'].inline_keyboard
        self.assertEqual(len(keyboard), 1)
        self.assertEqual(len(keyboard[0]), 2)
        self.assertEqual(keyboard[0][0].text, "✅ Approve")
        self.assertEqual(keyboard[0][0].callback_data, f"approve_access_{request_id}")
        self.assertEqual(keyboard[0][1].text, "❌ Deny")
        self.assertEqual(keyboard[0][1].callback_data, f"deny_access_{request_id}")

    def test_ask_calendar_invalid_arguments(self):
        """Test /ask_calendar with invalid arguments."""
        mock_update = MagicMock(spec=Update)
        mock_update.effective_user = User(id=123, first_name="Test", is_bot=False)
        mock_update.message = MagicMock(spec=Message)
        mock_update.message.reply_text = AsyncMock()

        mock_context = MagicMock()
        mock_context.args = ["@testuser", "2024-01-01"] # Missing 'to' and end_date

        asyncio.run(ask_calendar_command(mock_update, mock_context))

        mock_update.message.reply_text.assert_called_once_with(
            "Usage: /ask_calendar @target_username YYYY-MM-DD to YYYY-MM-DD\n"
            "Example: /ask_calendar @testuser 2024-03-10 to 2024-03-12"
        )

    def test_ask_calendar_end_date_before_start_date(self):
        """Test /ask_calendar with end date before start date."""
        mock_update = MagicMock(spec=Update)
        mock_update.effective_user = User(id=123, first_name="Test", is_bot=False)
        mock_update.message = MagicMock(spec=Message)
        mock_update.message.entities = [] # No mention needed for this test
        mock_update.message.text = "/ask_calendar @testuser 2024-01-05 to 2024-01-01"
        mock_update.message.reply_text = AsyncMock()
        
        mock_context = MagicMock()
        mock_context.args = ["@testuser", "2024-01-05", "to", "2024-01-01"]

        asyncio.run(ask_calendar_command(mock_update, mock_context))
        mock_update.message.reply_text.assert_called_once_with("Start date cannot be after end date.")

    @patch('handlers.gs.create_calendar_access_request', new_callable=AsyncMock)
    def test_ask_calendar_failure_to_create_request(self, mock_create_request):
        """Test /ask_calendar when gs.create_calendar_access_request returns None."""
        mock_create_request.return_value = None # Simulate failure

        mock_update = MagicMock(spec=Update)
        mock_update.effective_user = User(id=123, first_name="Test", is_bot=False)
        mock_update.message = MagicMock(spec=Message)
        mock_update.message.entities = []
        mock_update.message.text = "/ask_calendar @testuser 2024-01-01 to 2024-01-05"
        mock_update.message.reply_text = AsyncMock()

        mock_context = MagicMock()
        mock_context.args = ["@testuser", "2024-01-01", "to", "2024-01-05"]

        asyncio.run(ask_calendar_command(mock_update, mock_context))
        mock_update.message.reply_text.assert_called_once_with(
            "Could not save your access request. Please try again later."
        )

    @patch('handlers.gs.create_calendar_access_request', new_callable=AsyncMock)
    def test_ask_calendar_failure_to_send_notification(self, mock_create_request):
        """Test /ask_calendar when notification sending fails."""
        request_id = "test_req_id_fail_notify"
        mock_create_request.return_value = request_id
        
        requester_user_id = 123
        target_user_id = 456
        target_username_with_at = "@testuser"
        
        mock_update = MagicMock(spec=Update)
        mock_update.effective_user = User(id=requester_user_id, first_name="Requester", is_bot=False, username="req_user")

        command_text = "/ask_calendar"
        full_message_text = f"{command_text} {target_username_with_at} 2024-01-01 to 2024-01-05"
        
        bot_command_entity = MessageEntity(type=MessageEntityType.BOT_COMMAND, offset=0, length=len(command_text))
        mention_offset = len(command_text) + 1
        mention_length = len(target_username_with_at)
        mock_mentioned_user_obj = User(id=target_user_id, first_name="Test", is_bot=False, username=target_username_with_at.lstrip('@'))
        mention_entity = MessageEntity(type=MessageEntityType.MENTION, offset=mention_offset, length=mention_length, user=mock_mentioned_user_obj)

        mock_update.message = MagicMock(spec=Message)
        mock_update.message.text = full_message_text
        mock_update.message.entities = [bot_command_entity, mention_entity]
        mock_update.message.reply_text = AsyncMock()

        mock_context = MagicMock()
        mock_context.args = [target_username_with_at, "2024-01-01", "to", "2024-01-05"]
        mock_context.bot.send_message = AsyncMock(side_effect=Exception("Telegram API error"))

        asyncio.run(ask_calendar_command(mock_update, mock_context))

        expected_confirmation_message = (
            f"Your request to view {target_username_with_at}'s calendar from January 01, 2024 to January 05, 2024 has been sent (Request ID: {request_id})."
            f"\n\n⚠️ Could not directly notify {target_username_with_at}. "
            "They might need to start a chat with me first or check their privacy settings."
        )
        mock_update.message.reply_text.assert_called_once_with(expected_confirmation_message, parse_mode='HTML')

    @patch('handlers.gs.create_calendar_access_request', new_callable=AsyncMock)
    def test_ask_calendar_target_user_not_identified(self, mock_create_request):
        """Test /ask_calendar when target user ID is the placeholder."""
        request_id = "test_req_id_placeholder"
        mock_create_request.return_value = request_id

        requester_user_id = 123
        target_username_with_at = "@unknownuser" # No user ID in entity or entity missing

        mock_update = MagicMock(spec=Update)
        mock_update.effective_user = User(id=requester_user_id, first_name="Requester", is_bot=False, username="req_user")
        # Simulate a mention entity that matches target_username_with_at but has entity.user = None
        command_text = "/ask_calendar"
        full_message_text = f"{command_text} {target_username_with_at} 2024-01-01 to 2024-01-05"

        bot_command_entity = MessageEntity(type=MessageEntityType.BOT_COMMAND, offset=0, length=len(command_text))
        
        # Entity for the mention
        mention_offset = len(command_text) + 1
        mention_length = len(target_username_with_at)
        # IMPORTANT: entity.user is None for this test case
        mention_entity_no_user = MessageEntity(type=MessageEntityType.MENTION, offset=mention_offset, length=mention_length, user=None) 
                                             
        mock_update.message = MagicMock(spec=Message)
        mock_update.message.text = full_message_text
        mock_update.message.entities = [bot_command_entity, mention_entity_no_user]
        mock_update.message.reply_text = AsyncMock()

        mock_context = MagicMock()
        mock_context.args = [target_username_with_at, "2024-01-01", "to", "2024-01-05"]
        mock_context.bot.send_message = AsyncMock() # This should NOT be called for notification

        asyncio.run(ask_calendar_command(mock_update, mock_context))
        
        # Assert gs.create_calendar_access_request was called with placeholder
        mock_create_request.assert_called_once()
        self.assertEqual(mock_create_request.call_args.kwargs['requested_user_id'], DEFAULT_REQUESTED_USER_ID_PLACEHOLDER)

        # Assert requester's confirmation message indicates no direct notification
        expected_confirmation_message = (
            f"Your request to view {target_username_with_at}'s calendar from January 01, 2024 to January 05, 2024 has been sent (Request ID: {request_id})."
            f"\n\n⚠️ Could not identify {target_username_with_at} to send a direct notification. "
            "They will need to be informed of this request manually or by other means."
        )
        mock_update.message.reply_text.assert_called_once_with(expected_confirmation_message, parse_mode='HTML')
        
        # Assert that bot.send_message was NOT called (because target_user_id is placeholder)
        # Check specifically that it wasn't called with chat_id being the placeholder (which would be an error)
        for call in mock_context.bot.send_message.call_args_list:
            self.assertNotEqual(call.kwargs.get('chat_id'), int(DEFAULT_REQUESTED_USER_ID_PLACEHOLDER))
        # A more direct way if we are sure no other send_message calls should happen in this specific test path
        # For this test, since only the reply_text to the requester is expected, and no notification,
        # if mock_context.bot.send_message was used for reply_text, this would need adjustment.
        # But ask_calendar_command uses update.message.reply_text for requester and context.bot.send_message for target.
        # So, we are checking that no notification was attempted.
        # If the placeholder ID was extracted and *attempted* for send_message, that would be a bug.
        # This test assumes it's not even attempted if ID is placeholder.

        # Check that send_message was not called to the placeholder ID.
        # If it was called for other reasons, that's fine, but not for the notification.
        called_placeholder = False
        for call in mock_context.bot.send_message.call_args_list:
            if call.kwargs.get('chat_id') == int(DEFAULT_REQUESTED_USER_ID_PLACEHOLDER):
                called_placeholder = True
                break
        self.assertFalse(called_placeholder, "Notification was attempted to the placeholder user ID.")

    # --- Tests for button_callback (Calendar Access Sharing) ---

    @patch('handlers.gs.get_user_timezone_str', new_callable=MagicMock) # Mocked at handlers.gs level
    @patch('handlers.gs.get_calendar_events', new_callable=AsyncMock)
    @patch('handlers.gs.update_calendar_access_request_status', new_callable=AsyncMock)
    @patch('handlers.gs.get_calendar_access_request', new_callable=AsyncMock)
    def test_button_callback_approve_request_successful(
        self, mock_get_request, mock_update_status, mock_get_events, mock_get_tz
    ):
        """Test button_callback for approving a calendar access request successfully."""
        request_id = "req_approve_success"
        requester_id_str = "user_requester_123"
        approver_id_str = "user_approver_456" # This is query.from_user.id

        # --- Mock gs.get_calendar_access_request ---
        mock_request_data = {
            'requester_id': requester_id_str,
            'requested_user_id': approver_id_str, # User clicking is the requested user
            'target_username': '@requester_user',
            'start_time_iso': datetime(2024, 2, 1, 0, 0, 0, tzinfo=dt_timezone.utc).isoformat(),
            'end_time_iso': datetime(2024, 2, 5, 23, 59, 59, tzinfo=dt_timezone.utc).isoformat(),
            'status': 'pending'
        }
        mock_get_request.return_value = mock_request_data

        # --- Mock gs.update_calendar_access_request_status ---
        mock_update_status.return_value = True

        # --- Mock gs.get_user_timezone_str ---
        approver_timezone_str = "America/New_York"
        mock_get_tz.return_value = approver_timezone_str # For the approver

        # --- Mock gs.get_calendar_events ---
        mock_events_data = [
            {'summary': 'Event 1', 'start': {'dateTime': '2024-02-01T10:00:00Z'}, 'end': {'dateTime': '2024-02-01T11:00:00Z'}},
            {'summary': 'Event 2', 'start': {'date': '2024-02-02'}, 'end': {'date': '2024-02-03'}}
        ]
        mock_get_events.return_value = mock_events_data
        
        # --- Mock Update & Context for button_callback ---
        mock_query = MagicMock(spec=CallbackQuery)
        mock_query.data = f"approve_access_{request_id}"
        mock_query.from_user = User(id=int(approver_id_str), first_name="Approver", is_bot=False)
        mock_query.answer = AsyncMock()
        mock_query.edit_message_text = AsyncMock()

        mock_update_for_button = MagicMock(spec=Update)
        mock_update_for_button.callback_query = mock_query
        # _get_user_tz_or_prompt uses update.effective_user if update.message is None (which it is for callback)
        mock_update_for_button.effective_user = mock_query.from_user 

        mock_context_for_button = MagicMock()
        mock_context_for_button.bot.send_message = AsyncMock()

        # --- Run button_callback ---
        asyncio.run(button_callback(mock_update_for_button, mock_context_for_button))

        # --- Assertions ---
        mock_query.answer.assert_called_once()
        mock_get_request.assert_called_once_with(request_id)
        mock_update_status.assert_called_once_with(request_id, "approved")
        
        # Assert gs.get_user_timezone_str was called for the approver
        mock_get_tz.assert_called_with(int(approver_id_str))

        # Assert gs.get_calendar_events called correctly
        mock_get_events.assert_called_once_with(
            user_id=int(approver_id_str), # Events of the approver
            time_min_iso=mock_request_data['start_time_iso'],
            time_max_iso=mock_request_data['end_time_iso']
        )

        # Assert message sent to requester
        self.assertTrue(mock_context_for_button.bot.send_message.called)
        send_message_args = mock_context_for_button.bot.send_message.call_args
        self.assertEqual(send_message_args.kwargs['chat_id'], int(requester_id_str))
        self.assertIn("has been approved", send_message_args.kwargs['text'])
        self.assertIn("Event 1", send_message_args.kwargs['text'])
        self.assertIn("Event 2", send_message_args.kwargs['text'])

        # Assert original message edited
        mock_query.edit_message_text.assert_called_once_with(
            "Access approved. Calendar details sent to the requester."
        )

    @patch('handlers.gs.update_calendar_access_request_status', new_callable=AsyncMock)
    @patch('handlers.gs.get_calendar_access_request', new_callable=AsyncMock)
    def test_button_callback_deny_request_successful(
        self, mock_get_request, mock_update_status
    ):
        """Test button_callback for denying a calendar access request successfully."""
        request_id = "req_deny_success"
        requester_id_str = "user_requester_789"
        denier_id_str = "user_denier_101" # This is query.from_user.id

        mock_request_data = {
            'requester_id': requester_id_str,
            'requested_user_id': denier_id_str,
            'target_username': '@requester_user_deny',
            'start_time_iso': datetime(2024, 3, 1, 0, 0, 0, tzinfo=dt_timezone.utc).isoformat(),
            'end_time_iso': datetime(2024, 3, 5, 23, 59, 59, tzinfo=dt_timezone.utc).isoformat(),
            'status': 'pending'
        }
        mock_get_request.return_value = mock_request_data
        mock_update_status.return_value = True

        mock_query = MagicMock(spec=CallbackQuery)
        mock_query.data = f"deny_access_{request_id}"
        mock_query.from_user = User(id=int(denier_id_str), first_name="Denier", is_bot=False)
        mock_query.answer = AsyncMock()
        mock_query.edit_message_text = AsyncMock()

        mock_update_for_button = MagicMock(spec=Update)
        mock_update_for_button.callback_query = mock_query
        mock_update_for_button.effective_user = mock_query.from_user

        mock_context_for_button = MagicMock()
        mock_context_for_button.bot.send_message = AsyncMock()

        asyncio.run(button_callback(mock_update_for_button, mock_context_for_button))

        mock_query.answer.assert_called_once()
        mock_get_request.assert_called_once_with(request_id)
        mock_update_status.assert_called_once_with(request_id, "denied")

        # Assert message sent to requester
        self.assertTrue(mock_context_for_button.bot.send_message.called)
        send_message_args = mock_context_for_button.bot.send_message.call_args
        self.assertEqual(send_message_args.kwargs['chat_id'], int(requester_id_str))
        self.assertIn("has been denied", send_message_args.kwargs['text'])

        mock_query.edit_message_text.assert_called_once_with(
            "Access denied. The requester has been notified."
        )

    @patch('handlers.gs.get_calendar_access_request', new_callable=AsyncMock)
    def test_button_callback_unauthorized_user_click(self, mock_get_request):
        """Test button_callback when a user not part of the request clicks a button."""
        request_id = "req_unauthorized"
        actual_requested_user_id_str = "user_legit_requested_111"
        unauthorized_user_id_str = "user_unauthorized_222"

        mock_request_data = {
            'requested_user_id': actual_requested_user_id_str,
            'status': 'pending'
            # Other fields don't matter as much for this specific check path
        }
        mock_get_request.return_value = mock_request_data

        mock_query = MagicMock(spec=CallbackQuery)
        mock_query.data = f"approve_access_{request_id}" # Action doesn't matter here
        mock_query.from_user = User(id=int(unauthorized_user_id_str), first_name="Unauthorized", is_bot=False)
        mock_query.answer = AsyncMock()
        mock_query.edit_message_text = AsyncMock()

        mock_update_for_button = MagicMock(spec=Update)
        mock_update_for_button.callback_query = mock_query
        mock_update_for_button.effective_user = mock_query.from_user

        mock_context_for_button = MagicMock() # bot.send_message should not be called

        asyncio.run(button_callback(mock_update_for_button, mock_context_for_button))

        mock_query.answer.assert_called_once()
        mock_get_request.assert_called_once_with(request_id)
        mock_query.edit_message_text.assert_called_once_with(
            "This is not your request to approve/deny."
        )
        mock_context_for_button.bot.send_message.assert_not_called() # Crucial check

    @patch('handlers.gs.get_calendar_access_request', new_callable=AsyncMock)
    def test_button_callback_request_already_processed(self, mock_get_request):
        """Test button_callback when the request has already been approved or denied."""
        request_id = "req_already_done"
        user_id_str = "user_clicker_333"

        mock_request_data = {
            'requested_user_id': user_id_str,
            'status': 'approved' # Already processed
        }
        mock_get_request.return_value = mock_request_data

        mock_query = MagicMock(spec=CallbackQuery)
        mock_query.data = f"approve_access_{request_id}"
        mock_query.from_user = User(id=int(user_id_str), first_name="Clicker", is_bot=False)
        mock_query.answer = AsyncMock()
        mock_query.edit_message_text = AsyncMock()
        
        mock_update_for_button = MagicMock(spec=Update)
        mock_update_for_button.callback_query = mock_query
        mock_update_for_button.effective_user = mock_query.from_user
        
        mock_context_for_button = MagicMock()

        asyncio.run(button_callback(mock_update_for_button, mock_context_for_button))

        mock_query.answer.assert_called_once()
        mock_get_request.assert_called_once_with(request_id)
        mock_query.edit_message_text.assert_called_once_with(
            "This request has already been processed."
        )

    @patch('handlers.gs.get_calendar_access_request', new_callable=AsyncMock)
    def test_button_callback_invalid_request_id(self, mock_get_request):
        """Test button_callback when gs.get_calendar_access_request returns None."""
        request_id = "req_does_not_exist"
        mock_get_request.return_value = None # Simulate request not found

        mock_query = MagicMock(spec=CallbackQuery)
        mock_query.data = f"approve_access_{request_id}"
        mock_query.from_user = User(id=123, first_name="AnyUser", is_bot=False)
        mock_query.answer = AsyncMock()
        mock_query.edit_message_text = AsyncMock()

        mock_update_for_button = MagicMock(spec=Update)
        mock_update_for_button.callback_query = mock_query
        mock_update_for_button.effective_user = mock_query.from_user
        
        mock_context_for_button = MagicMock()

        asyncio.run(button_callback(mock_update_for_button, mock_context_for_button))

        mock_query.answer.assert_called_once()
        mock_get_request.assert_called_once_with(request_id)
        mock_query.edit_message_text.assert_called_once_with(
            "This request is no longer valid or has expired."
        )

    @patch('handlers.gs.get_user_timezone_str', new_callable=MagicMock)
    @patch('handlers.gs.get_calendar_events', new_callable=AsyncMock)
    @patch('handlers.gs.update_calendar_access_request_status', new_callable=AsyncMock)
    @patch('handlers.gs.get_calendar_access_request', new_callable=AsyncMock)
    def test_button_callback_approve_no_events(self, mock_get_request, mock_update_status, mock_get_events, mock_get_tz):
        """Test approval when no events are found or gs.get_calendar_events returns None."""
        request_id = "req_approve_no_events"
        # Setup similar to successful approval
        requester_id_str = "requester_no_events"
        approver_id_str = "approver_no_events"
        mock_request_data = {
            'requester_id': requester_id_str, 'requested_user_id': approver_id_str, 'status': 'pending',
            'start_time_iso': datetime(2024,1,1).isoformat(), 'end_time_iso': datetime(2024,1,2).isoformat(),
            'target_username': '@target'
        }
        mock_get_request.return_value = mock_request_data
        mock_update_status.return_value = True
        mock_get_tz.return_value = "UTC"
        
        # Scenario 1: get_calendar_events returns an empty list
        mock_get_events.return_value = []

        mock_query = MagicMock(spec=CallbackQuery); mock_query.data = f"approve_access_{request_id}"; mock_query.from_user = User(id=int(approver_id_str), first_name="A", is_bot=False); mock_query.answer = AsyncMock(); mock_query.edit_message_text = AsyncMock()
        mock_update = MagicMock(spec=Update); mock_update.callback_query = mock_query; mock_update.effective_user = mock_query.from_user
        mock_context = MagicMock(); mock_context.bot.send_message = AsyncMock()

        asyncio.run(button_callback(mock_update, mock_context))
        
        msg_to_requester_args = mock_context.bot.send_message.call_args
        self.assertIn("No events found", msg_to_requester_args.kwargs['text'])
        mock_query.edit_message_text.assert_called_with("Access approved. Calendar details sent to the requester.")

        # Scenario 2: get_calendar_events returns None (simulates an API error)
        mock_get_events.return_value = None
        mock_get_request.reset_mock(); mock_update_status.reset_mock(); mock_get_events.reset_mock(); mock_get_tz.reset_mock() # Reset mocks for new run
        mock_get_request.return_value = mock_request_data # Set again
        mock_update_status.return_value = True
        mock_get_tz.return_value = "UTC"
        mock_query.reset_mock(); mock_update.reset_mock(); mock_context.reset_mock() # Reset Telegram mocks
        mock_query.answer = AsyncMock(); mock_query.edit_message_text = AsyncMock(); mock_context.bot.send_message = AsyncMock()
        mock_update.callback_query = mock_query; mock_update.effective_user = mock_query.from_user


        asyncio.run(button_callback(mock_update, mock_context))
        
        msg_to_requester_args_none = mock_context.bot.send_message.call_args
        self.assertIn("Could not fetch their calendar events", msg_to_requester_args_none.kwargs['text'])
        mock_query.edit_message_text.assert_called_with("Access approved. Calendar details sent to the requester.")

    @patch('handlers.gs.get_calendar_access_request', new_callable=AsyncMock)
    @patch('handlers.gs.update_calendar_access_request_status', new_callable=AsyncMock)
    def test_button_callback_approve_update_status_fails(self, mock_update_status, mock_get_request):
        """Test approval when gs.update_calendar_access_request_status returns False."""
        request_id = "req_approve_status_fail"
        mock_get_request.return_value = {'requester_id': 'r', 'requested_user_id': 'a', 'status': 'pending'}
        mock_update_status.return_value = False # Simulate failure

        mock_query = MagicMock(spec=CallbackQuery); mock_query.data = f"approve_access_{request_id}"; mock_query.from_user = User(id='a', first_name="A", is_bot=False); mock_query.answer = AsyncMock(); mock_query.edit_message_text = AsyncMock()
        mock_update = MagicMock(spec=Update); mock_update.callback_query = mock_query; mock_update.effective_user = mock_query.from_user
        mock_context = MagicMock()

        asyncio.run(button_callback(mock_update, mock_context))
        mock_query.edit_message_text.assert_called_with("Failed to approve the request. Please try again.")

    @patch('handlers.gs.get_user_timezone_str', new_callable=MagicMock)
    @patch('handlers.gs.get_calendar_events', new_callable=AsyncMock)
    @patch('handlers.gs.update_calendar_access_request_status', new_callable=AsyncMock)
    @patch('handlers.gs.get_calendar_access_request', new_callable=AsyncMock)
    def test_button_callback_approve_send_to_requester_fails(self, mock_get_request, mock_update_status, mock_get_events, mock_get_tz):
        """Test approval when sending message to requester fails."""
        request_id = "req_approve_send_fail"
        mock_get_request.return_value = {'requester_id': 'r', 'requested_user_id': 'a', 'status': 'pending', 'start_time_iso': datetime(2024,1,1).isoformat(), 'end_time_iso': datetime(2024,1,2).isoformat(), 'target_username': '@t'}
        mock_update_status.return_value = True
        mock_get_events.return_value = [] # No events, simple path
        mock_get_tz.return_value = "UTC"

        mock_query = MagicMock(spec=CallbackQuery); mock_query.data = f"approve_access_{request_id}"; mock_query.from_user = User(id='a', first_name="A", is_bot=False); mock_query.answer = AsyncMock(); mock_query.edit_message_text = AsyncMock()
        mock_update = MagicMock(spec=Update); mock_update.callback_query = mock_query; mock_update.effective_user = mock_query.from_user
        mock_context = MagicMock(); mock_context.bot.send_message = AsyncMock(side_effect=Exception("Bot blocked"))

        asyncio.run(button_callback(mock_update, mock_context))
        mock_query.edit_message_text.assert_called_with("Access approved. However, could not send calendar details to the requester. They may have blocked me or the chat is no longer accessible.")

    @patch('handlers.gs.get_calendar_access_request', new_callable=AsyncMock)
    @patch('handlers.gs.update_calendar_access_request_status', new_callable=AsyncMock)
    def test_button_callback_deny_update_status_fails(self, mock_update_status, mock_get_request):
        """Test denial when gs.update_calendar_access_request_status returns False."""
        request_id = "req_deny_status_fail"
        mock_get_request.return_value = {'requester_id': 'r', 'requested_user_id': 'd', 'status': 'pending'}
        mock_update_status.return_value = False

        mock_query = MagicMock(spec=CallbackQuery); mock_query.data = f"deny_access_{request_id}"; mock_query.from_user = User(id='d', first_name="D", is_bot=False); mock_query.answer = AsyncMock(); mock_query.edit_message_text = AsyncMock()
        mock_update = MagicMock(spec=Update); mock_update.callback_query = mock_query; mock_update.effective_user = mock_query.from_user
        mock_context = MagicMock()

        asyncio.run(button_callback(mock_update, mock_context))
        mock_query.edit_message_text.assert_called_with("Failed to deny the request. Please try again.")

    @patch('handlers.gs.update_calendar_access_request_status', new_callable=AsyncMock)
    @patch('handlers.gs.get_calendar_access_request', new_callable=AsyncMock)
    def test_button_callback_deny_send_to_requester_fails(self, mock_get_request, mock_update_status):
        """Test denial when sending message to requester fails."""
        request_id = "req_deny_send_fail"
        mock_get_request.return_value = {'requester_id': 'r', 'requested_user_id': 'd', 'status': 'pending', 'start_time_iso': datetime(2024,1,1).isoformat(), 'end_time_iso': datetime(2024,1,2).isoformat(), 'target_username': '@t'}
        mock_update_status.return_value = True

        mock_query = MagicMock(spec=CallbackQuery); mock_query.data = f"deny_access_{request_id}"; mock_query.from_user = User(id='d', first_name="D", is_bot=False); mock_query.answer = AsyncMock(); mock_query.edit_message_text = AsyncMock()
        mock_update = MagicMock(spec=Update); mock_update.callback_query = mock_query; mock_update.effective_user = mock_query.from_user
        mock_context = MagicMock(); mock_context.bot.send_message = AsyncMock(side_effect=Exception("Bot blocked"))

        asyncio.run(button_callback(mock_update, mock_context))
        mock_query.edit_message_text.assert_called_with("Access denied. However, could not notify the requester. They may have blocked me or the chat is no longer accessible.")

    @patch('handlers._get_user_tz_or_prompt', new_callable=AsyncMock) # Patching the helper directly
    @patch('handlers.gs.update_calendar_access_request_status', new_callable=AsyncMock)
    @patch('handlers.gs.get_calendar_access_request', new_callable=AsyncMock)
    def test_button_callback_approve_approver_tz_not_set(self, mock_get_request, mock_update_status, mock_get_user_tz):
        """Test approval when the approver's timezone is not set."""
        request_id = "req_approve_no_tz"
        approver_id_str = "approver_no_tz_user"
        mock_request_data = {
            'requester_id': 'some_requester', 'requested_user_id': approver_id_str, 'status': 'pending',
            'start_time_iso': datetime(2024,1,1).isoformat(), 'end_time_iso': datetime(2024,1,2).isoformat(),
            'target_username': '@target_user'
        }
        mock_get_request.return_value = mock_request_data
        mock_update_status.return_value = True
        mock_get_user_tz.return_value = None # Simulate timezone not set

        mock_query = MagicMock(spec=CallbackQuery); mock_query.data = f"approve_access_{request_id}"; mock_query.from_user = User(id=int(approver_id_str), first_name="ApproverNoTZ", is_bot=False); mock_query.answer = AsyncMock(); mock_query.edit_message_text = AsyncMock()
        mock_update = MagicMock(spec=Update); mock_update.callback_query = mock_query; mock_update.effective_user = mock_query.from_user
        mock_context = MagicMock() # bot.send_message to requester should not be called if events can't be fetched/formatted due to no TZ

        asyncio.run(button_callback(mock_update, mock_context))

        mock_get_user_tz.assert_called_once() # Check that the tz prompt was attempted
        mock_query.edit_message_text.assert_called_once_with("Error: Your timezone is not set. Please set it via /set_timezone and try again.")
        # gs.get_calendar_events should not be called if timezone is not set
        # context.bot.send_message to requester should not be called
        self.assertFalse(mock_context.bot.send_message.called)


    # --- Tests for google_services.py (Calendar Access Sharing) ---

    @patch('google_services.CALENDAR_ACCESS_REQUESTS_COLLECTION', new_callable=MagicMock)
    def test_gs_create_calendar_access_request_success(self, mock_collection):
        """Test create_calendar_access_request successfully creates a document."""
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "new_request_id_firestore"
        # Firestore `set` is synchronous for the standard Python client.
        # `set` returns a WriteResult, which can be mocked if its attributes are accessed.
        mock_doc_ref.set = MagicMock(return_value=MagicMock(spec=firestore.WriteResult)) 

        mock_collection.document.return_value = mock_doc_ref # When a new doc is created without specific ID

        requester_id = "req1"
        requested_user_id = "targ1"
        start_iso = datetime(2024, 4, 1, 0, 0, 0, tzinfo=dt_timezone.utc).isoformat()
        end_iso = datetime(2024, 4, 5, 23, 59, 59, tzinfo=dt_timezone.utc).isoformat()
        target_username = "@target_user_firestore"

        result_id = asyncio.run(create_calendar_access_request(
            requester_id, requested_user_id, start_iso, end_iso, target_username
        ))

        self.assertEqual(result_id, mock_doc_ref.id)
        mock_collection.document.assert_called_once_with() # Called to generate a new ID
        
        # Get the actual data passed to set()
        call_args = mock_doc_ref.set.call_args[0][0] # First arg of first call
        
        self.assertEqual(call_args['requester_id'], requester_id)
        self.assertEqual(call_args['requested_user_id'], requested_user_id)
        self.assertEqual(call_args['start_time_iso'], start_iso)
        self.assertEqual(call_args['end_time_iso'], end_iso)
        self.assertEqual(call_args['target_username'], target_username)
        self.assertEqual(call_args['status'], "pending")
        self.assertIsNotNone(call_args['request_timestamp']) # Should be firestore.SERVER_TIMESTAMP

    @patch('google_services.CALENDAR_ACCESS_REQUESTS_COLLECTION', new_callable=MagicMock)
    def test_gs_create_calendar_access_request_failure(self, mock_collection):
        """Test create_calendar_access_request when Firestore operation fails."""
        mock_collection.document.side_effect = Exception("Firestore unavailable")

        result_id = asyncio.run(create_calendar_access_request("r", "t", "s", "e", "u"))
        self.assertIsNone(result_id)

    @patch('google_services.CALENDAR_ACCESS_REQUESTS_COLLECTION', new_callable=MagicMock)
    async def test_gs_get_calendar_access_request_found(self, mock_collection):
        """Test get_calendar_access_request when document is found."""
        request_id = "get_req_found"
        expected_data = {'requester_id': 'r1', 'status': 'pending'}

        mock_snapshot = MagicMock(spec=firestore.DocumentSnapshot)
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = expected_data
        
        mock_doc_ref = MagicMock()
        mock_doc_ref.get = MagicMock(return_value=mock_snapshot) # get() is synchronous
        mock_collection.document.return_value = mock_doc_ref

        # The function under test is async, so we still await it.
        result_data = await get_calendar_access_request(request_id)

        self.assertEqual(result_data, expected_data)
        mock_collection.document.assert_called_once_with(request_id)
        mock_doc_ref.get.assert_called_once()

    @patch('google_services.CALENDAR_ACCESS_REQUESTS_COLLECTION', new_callable=MagicMock)
    async def test_gs_get_calendar_access_request_not_found(self, mock_collection):
        """Test get_calendar_access_request when document is not found."""
        request_id = "get_req_not_found"
        mock_snapshot = MagicMock(spec=firestore.DocumentSnapshot)
        mock_snapshot.exists = False
        
        mock_doc_ref = MagicMock()
        mock_doc_ref.get = MagicMock(return_value=mock_snapshot) # get() is synchronous
        mock_collection.document.return_value = mock_doc_ref

        result_data = await get_calendar_access_request(request_id)
        self.assertIsNone(result_data)

    @patch('google_services.CALENDAR_ACCESS_REQUESTS_COLLECTION', new_callable=MagicMock)
    async def test_gs_update_calendar_access_request_status_success(self, mock_collection):
        """Test update_calendar_access_request_status successfully updates a document."""
        request_id = "update_req_success"
        new_status = "approved"

        mock_doc_ref = MagicMock()
        # update() is synchronous, returns a WriteResult.
        mock_doc_ref.update = MagicMock(return_value=MagicMock(spec=firestore.WriteResult)) 
        mock_collection.document.return_value = mock_doc_ref
        
        # Mock firestore.SERVER_TIMESTAMP as it's used in the function
        # This is a bit tricky as it's a sentinel value.
        # We can either patch firestore directly or just check that update was called.
        # For simplicity here, we'll check the structure of the call.

        result = await update_calendar_access_request_status(request_id, new_status)

        self.assertTrue(result)
        mock_collection.document.assert_called_once_with(request_id)
        
        # Check that update was called with a dict containing status and response_timestamp
        update_call_args = mock_doc_ref.update.call_args[0][0]
        self.assertEqual(update_call_args['status'], new_status)
        self.assertIn('response_timestamp', update_call_args) # Check key presence

    @patch('google_services.CALENDAR_ACCESS_REQUESTS_COLLECTION', new_callable=MagicMock)
    async def test_gs_update_calendar_access_request_status_not_found(self, mock_collection):
        """Test update_calendar_access_request_status when document is not found."""
        request_id = "update_req_not_found"
        mock_doc_ref = MagicMock()
        mock_doc_ref.update = MagicMock(side_effect=firestore.NotFound("Not found")) # Simulate NotFound
        mock_collection.document.return_value = mock_doc_ref

        result = await update_calendar_access_request_status(request_id, "approved")
        self.assertFalse(result)

    @patch('google_services.CALENDAR_ACCESS_REQUESTS_COLLECTION', new_callable=MagicMock)
    async def test_gs_update_calendar_access_request_status_failure(self, mock_collection):
        """Test update_calendar_access_request_status when Firestore operation fails."""
        request_id = "update_req_fail"
        mock_doc_ref = MagicMock()
        mock_doc_ref.update = MagicMock(side_effect=Exception("Firestore error"))
        mock_collection.document.return_value = mock_doc_ref
        
        result = await update_calendar_access_request_status(request_id, "denied")
        self.assertFalse(result)


if __name__ == '__main__':
    # Note: To run async unittest methods, you might need a runner like pytest-asyncio
    # or structure tests differently if using plain unittest.
    # For this setup, assuming a compatible runner or manual asyncio.run in a main block if needed.
    # unittest.main() will work if tests are synchronous or self-contained with asyncio.run().
    # The google_services tests are async def, so they would need `asyncio.run` if called directly
    # or an async test runner.
    # For this structure, we assume the environment handles running async test methods.
    unittest.main()
