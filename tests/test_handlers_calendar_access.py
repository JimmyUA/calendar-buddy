import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, User, Message, Chat, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import html

# Import the handlers module
import handlers
import google_services as gs # For mocking gs functions directly
# from llm import llm_service # For mocking llm_service (already mocked in tests)
import pytz

# Constants for testing
TEST_REQUESTER_ID = 100
TEST_REQUESTER_USERNAME = "requester_user"
TEST_REQUESTER_FIRST_NAME = "Requester"
TEST_TARGET_ID_STR = "200"
TEST_TARGET_USERNAME = "target_user"
TEST_TARGET_FIRST_NAME = "TargetUser"
TEST_REQUEST_ID = "test_req_123"
TEST_TIMEZONE_STR = "America/New_York"
TEST_TARGET_TIMEZONE_STR = "Europe/London"

# Pytest mark for async functions
pytestmark = pytest.mark.asyncio

# --- Fixtures ---
@pytest.fixture
def mock_update_message():
    update = MagicMock(spec=Update)
    update.effective_user = User(id=TEST_REQUESTER_ID, first_name=TEST_REQUESTER_FIRST_NAME, is_bot=False, username=TEST_REQUESTER_USERNAME)
    update.message = AsyncMock(spec=Message) # AsyncMock for reply_text etc.
    update.message.from_user = update.effective_user
    update.message.chat = MagicMock(spec=Chat)
    update.message.chat.id = TEST_REQUESTER_ID
    update.message.text = ""
    update.callback_query = None
    return update

@pytest.fixture
def mock_context_args():
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []
    context.bot = AsyncMock()
    return context

@pytest.fixture
def mock_update_callback():
    update = MagicMock(spec=Update)
    update.callback_query = AsyncMock() # For answer, edit_message_text
    # User clicking the button is the TARGET user by default in these tests
    update.callback_query.from_user = User(id=int(TEST_TARGET_ID_STR), first_name=TEST_TARGET_FIRST_NAME, is_bot=False, username=TEST_TARGET_USERNAME)
    update.callback_query.data = ""
    update.callback_query.message = AsyncMock(spec=Message)
    update.callback_query.message.chat_id = int(TEST_TARGET_ID_STR) # Message is in target's chat with bot
    update.effective_user = update.callback_query.from_user # User who pressed button
    update.message = None # Callback updates don't have a new message
    return update


# --- Tests for request_calendar_access_command ---

@patch('handlers.gs.is_user_connected')
@patch('handlers.gs.get_user_id_by_username')
@patch('handlers._get_user_tz_or_prompt') # Patched at handlers level
@patch('handlers.llm_service.parse_date_range_llm')
@patch('handlers.gs.add_calendar_access_request')
@patch('handlers.gs.get_user_timezone_str') # For target user's timezone
async def test_request_calendar_access_success(
    mock_get_target_tz, mock_add_req, mock_parse_range, mock_get_req_tz_prompt,
    mock_get_target_id, mock_is_connected, mock_update_message, mock_context_args
):
    args = [f"@{TEST_TARGET_USERNAME}", "tomorrow", "10am", "to", "2pm"]
    mock_update_message.message.text = f"/request_access {' '.join(args)}"
    mock_context_args.args = args

    mock_is_connected.return_value = True
    mock_get_target_id.return_value = TEST_TARGET_ID_STR
    mock_get_req_tz_prompt.return_value = pytz.timezone(TEST_TIMEZONE_STR)
    mock_parse_range.return_value = {"start_iso": "2024-08-01T10:00:00Z", "end_iso": "2024-08-01T14:00:00Z"}
    mock_add_req.return_value = TEST_REQUEST_ID
    mock_get_target_tz.return_value = TEST_TARGET_TIMEZONE_STR # Target's TZ for notification formatting

    await handlers.request_calendar_access_command(mock_update_message, mock_context_args)

    # Requester's confirmation
    mock_update_message.message.reply_text.assert_any_call(
        f"✅ Your request to access @{TEST_TARGET_USERNAME}'s calendar for the period "
        f"'{html.escape('tomorrow 10am to 2pm')}' has been sent.\n"
        f"Request ID: `{TEST_REQUEST_ID}`. You will be notified when they respond."
    )

    # Notification to target
    mock_context_args.bot.send_message.assert_called_once()
    call_kwargs = mock_context_args.bot.send_message.call_args.kwargs
    assert call_kwargs['chat_id'] == TEST_TARGET_ID_STR
    assert f"User <b>{TEST_REQUESTER_FIRST_NAME}</b> (Telegram: @{TEST_REQUESTER_USERNAME})" in call_kwargs['text']
    # Check formatted times for target (10:00Z is 11:00 AM BST, 14:00Z is 3:00 PM BST)
    assert "<b>From:</b> 2024-08-01 11:00 AM BST" in call_kwargs['text'] 
    assert "<b>To:</b>   2024-08-01 03:00 PM BST" in call_kwargs['text'] 
    assert isinstance(call_kwargs['reply_markup'], InlineKeyboardMarkup)
    buttons = call_kwargs['reply_markup'].inline_keyboard[0]
    assert buttons[0].text == "✅ Approve Access"
    assert buttons[0].callback_data == f"approve_access_{TEST_REQUEST_ID}"
    assert buttons[1].text == "❌ Deny Access"
    assert buttons[1].callback_data == f"deny_access_{TEST_REQUEST_ID}"

    mock_add_req.assert_called_once_with(
        requester_id=str(TEST_REQUESTER_ID),
        requester_name=TEST_REQUESTER_FIRST_NAME,
        target_user_id=TEST_TARGET_ID_STR,
        start_time_iso="2024-08-01T10:00:00Z",
        end_time_iso="2024-08-01T14:00:00Z"
    )

async def test_request_calendar_access_not_enough_args(mock_update_message, mock_context_args):
    args = [f"@{TEST_TARGET_USERNAME}"] # Missing time period
    mock_update_message.message.text = f"/request_access {' '.join(args)}" # Set message text for handler
    mock_context_args.args = args
    await handlers.request_calendar_access_command(mock_update_message, mock_context_args)
    mock_update_message.message.reply_text.assert_called_once_with(
        "Usage: /request_access @target_username <time period>\n"
        "Example: /request_access @bob_the_user tomorrow 10am to 2pm"
    )

@patch('handlers.gs.is_user_connected', return_value=False)
async def test_request_calendar_access_requester_not_connected(mock_is_connected, mock_update_message, mock_context_args):
    args = [f"@{TEST_TARGET_USERNAME}", "tomorrow"]
    mock_context_args.args = args
    await handlers.request_calendar_access_command(mock_update_message, mock_context_args)
    mock_update_message.message.reply_text.assert_called_once_with(
        "You need to connect your Google Calendar first. Use /connect_calendar."
    )

@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers.gs.get_user_id_by_username', return_value=None)
async def test_request_calendar_access_target_not_found(mock_get_target_id, mock_is_connected, mock_update_message, mock_context_args):
    args = ["@unknownuser", "tomorrow"]
    mock_context_args.args = args
    await handlers.request_calendar_access_command(mock_update_message, mock_context_args)
    mock_update_message.message.reply_text.assert_called_once_with(
        f"Could not find user '{html.escape('@unknownuser')}'. "
        "They might not have used this bot or set their username."
    )

@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers.gs.get_user_id_by_username', return_value=str(TEST_REQUESTER_ID)) # Target is requester
async def test_request_calendar_access_target_is_requester(mock_get_target_id, mock_is_connected, mock_update_message, mock_context_args):
    args = [f"@{TEST_REQUESTER_USERNAME}", "tomorrow"]
    mock_context_args.args = args
    await handlers.request_calendar_access_command(mock_update_message, mock_context_args)
    mock_update_message.message.reply_text.assert_called_once_with(
        "You cannot request calendar access from yourself."
    )

@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers.gs.get_user_id_by_username', return_value=TEST_TARGET_ID_STR)
@patch('handlers._get_user_tz_or_prompt')
@patch('handlers.llm_service.parse_date_range_llm', return_value=None) # Time parsing fails
async def test_request_calendar_access_time_parse_fail(
    mock_parse_range, mock_get_req_tz, mock_get_target_id, mock_is_connected, mock_update_message, mock_context_args
):
    time_period_str = "gibberish time"
    args = [f"@{TEST_TARGET_USERNAME}", time_period_str]
    mock_context_args.args = args
    mock_get_req_tz.return_value = pytz.timezone(TEST_TIMEZONE_STR)
    await handlers.request_calendar_access_command(mock_update_message, mock_context_args)
    mock_update_message.message.reply_text.assert_called_once_with(
        f"Sorry, I couldn't understand the time period: '{html.escape(time_period_str)}'. "
        "Please try being more specific, e.g., 'tomorrow from 10am to 2pm' or 'next Monday'."
    )

@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers.gs.get_user_id_by_username', return_value=TEST_TARGET_ID_STR)
@patch('handlers._get_user_tz_or_prompt')
@patch('handlers.llm_service.parse_date_range_llm')
@patch('handlers.gs.add_calendar_access_request', return_value=None) # Add request fails
async def test_request_calendar_access_add_request_fails(
    mock_add_req, mock_parse_range, mock_get_req_tz, mock_get_target_id, mock_is_connected, mock_update_message, mock_context_args
):
    args = [f"@{TEST_TARGET_USERNAME}", "tomorrow"]
    mock_context_args.args = args
    mock_get_req_tz.return_value = pytz.timezone(TEST_TIMEZONE_STR)
    mock_parse_range.return_value = {"start_iso": "s", "end_iso": "e"}
    await handlers.request_calendar_access_command(mock_update_message, mock_context_args)
    mock_update_message.message.reply_text.assert_called_once_with(
        "Sorry, there was an internal error trying to store your access request. Please try again later."
    )

@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers.gs.get_user_id_by_username', return_value=TEST_TARGET_ID_STR)
@patch('handlers._get_user_tz_or_prompt')
@patch('handlers.llm_service.parse_date_range_llm')
@patch('handlers.gs.add_calendar_access_request', return_value=TEST_REQUEST_ID)
@patch('handlers.gs.get_user_timezone_str')
@patch('handlers.gs.update_calendar_access_request_status') 
async def test_request_calendar_access_notify_target_fails(
    mock_update_status, mock_get_target_tz, mock_add_req, mock_parse_range,
    mock_get_req_tz, mock_get_target_id, mock_is_connected, mock_update_message, mock_context_args
):
    args = [f"@{TEST_TARGET_USERNAME}", "tomorrow"]
    mock_context_args.args = args
    mock_get_req_tz.return_value = pytz.timezone(TEST_TIMEZONE_STR)
    mock_parse_range.return_value = {"start_iso": "s", "end_iso": "e"}
    mock_get_target_tz.return_value = None # Target TZ doesn't matter for this failure path
    mock_context_args.bot.send_message.side_effect = Exception("Telegram API error")

    await handlers.request_calendar_access_command(mock_update_message, mock_context_args)
    
    # Initial success message to requester
    mock_update_message.message.reply_text.assert_any_call(
        f"✅ Your request to access @{TEST_TARGET_USERNAME}'s calendar for the period "
        f"'{html.escape('tomorrow')}' has been sent.\n"
        f"Request ID: `{TEST_REQUEST_ID}`. You will be notified when they respond."
    )
    # Second message to requester about notification failure
    mock_update_message.message.reply_text.assert_any_call(
        "Your request was stored, but I encountered an issue notifying the target user. "
        "They may not receive the request if they have blocked the bot or if there's a Telegram issue."
    )
    mock_update_status.assert_called_once_with(TEST_REQUEST_ID, "error_notifying_target")

# --- Tests for button_callback (Approve Flow) ---

REQUEST_DATA_PENDING = {
    "requester_id": str(TEST_REQUESTER_ID), "requester_name": TEST_REQUESTER_FIRST_NAME,
    "target_user_id": TEST_TARGET_ID_STR, "start_time_iso": "2024-08-01T10:00:00Z",
    "end_time_iso": "2024-08-01T14:00:00Z", "status": "pending"
}
REQUEST_DATA_ERROR_NOTIFYING = {
    **REQUEST_DATA_PENDING, "status": "error_notifying_target"
}
EVENTS_LIST_EXAMPLE = [
    {"summary": "Event 1", "start": {"dateTime": "2024-08-01T11:00:00Z"}, "end": {"dateTime": "2024-08-01T12:00:00Z"}}, # Corrected to Z for UTC
    {"summary": "Event 2", "start": {"date": "2024-08-01"}, "end": {"date": "2024-08-01"}}
]

@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.is_user_connected') # Target user connection status
@patch('handlers.gs.update_calendar_access_request_status')
@patch('handlers.gs.get_calendar_events')
@patch('handlers.gs.get_user_timezone_str') # Target user's TZ for event formatting
async def test_button_approve_success(
    mock_get_target_tz_for_events, mock_get_events, mock_update_req_status, mock_is_target_connected,
    mock_get_req, mock_update_callback, mock_context_args # Use mock_context_args for bot mock
):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_ID}"
    
    mock_get_req.return_value = REQUEST_DATA_PENDING
    mock_is_target_connected.return_value = True
    mock_update_req_status.return_value = True
    mock_get_events.return_value = EVENTS_LIST_EXAMPLE
    mock_get_target_tz_for_events.return_value = TEST_TARGET_TIMEZONE_STR # Target's TZ is London/BST

    await handlers.button_callback(mock_update_callback, mock_context_args)

    mock_update_callback.callback_query.answer.assert_called_once()
    mock_get_req.assert_called_once_with(TEST_REQUEST_ID)
    mock_is_target_connected.assert_called_once_with(int(TEST_TARGET_ID_STR))
    mock_update_req_status.assert_called_once_with(TEST_REQUEST_ID, "approved")
    mock_get_events.assert_called_once_with(int(TEST_TARGET_ID_STR), "2024-08-01T10:00:00Z", "2024-08-01T14:00:00Z")

    mock_context_args.bot.send_message.assert_called_once()
    requester_msg_kwargs = mock_context_args.bot.send_message.call_args.kwargs
    assert requester_msg_kwargs['chat_id'] == str(TEST_REQUESTER_ID)
    assert "was APPROVED" in requester_msg_kwargs['text']
    assert "Event 1" in requester_msg_kwargs['text']
    assert "12:00 PM BST" in requester_msg_kwargs['text'] # 11:00Z is 12:00 PM BST (London time)
    assert "All day" in requester_msg_kwargs['text']

    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        text="Access request APPROVED. The requester has been notified with the events."
    )

@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers.gs.update_calendar_access_request_status', return_value=True)
@patch('handlers.gs.get_calendar_events', return_value=[]) # No events
@patch('handlers.gs.get_user_timezone_str', return_value=TEST_TARGET_TIMEZONE_STR)
async def test_button_approve_success_no_events(
    mock_get_target_tz, mock_get_events, mock_update_req_status, mock_is_target_connected,
    mock_get_req, mock_update_callback, mock_context_args
):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_ID}"
    mock_get_req.return_value = REQUEST_DATA_PENDING

    await handlers.button_callback(mock_update_callback, mock_context_args)
    
    requester_msg_kwargs = mock_context_args.bot.send_message.call_args.kwargs
    assert "No events found in this period." in requester_msg_kwargs['text']
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        text="Access request APPROVED. The requester has been notified with the events."
    )


@patch('handlers.gs.get_calendar_access_request', return_value=None)
async def test_button_approve_request_not_found(mock_get_req, mock_update_callback, mock_context_args):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_ID}"
    await handlers.button_callback(mock_update_callback, mock_context_args)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "This access request was not found or may have expired."
    )

@patch('handlers.gs.get_calendar_access_request')
async def test_button_approve_request_already_actioned(mock_get_req, mock_update_callback, mock_context_args):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_ID}"
    mock_get_req.return_value = {**REQUEST_DATA_PENDING, "status": "approved"}
    await handlers.button_callback(mock_update_callback, mock_context_args)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        f"This request has already been actioned (status: approved)."
    )

@patch('handlers.gs.get_calendar_access_request')
async def test_button_approve_wrong_user_clicks(mock_get_req, mock_update_callback, mock_context_args):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_ID}"
    # Change the user clicking the button
    mock_update_callback.callback_query.from_user = User(id=999, first_name="Wrong", is_bot=False, username="wrong_user")
    mock_update_callback.effective_user = mock_update_callback.callback_query.from_user

    mock_get_req.return_value = REQUEST_DATA_PENDING # Request is for TEST_TARGET_ID_STR
    await handlers.button_callback(mock_update_callback, mock_context_args)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
         "Error: This request is not for you."
    )

@patch('handlers.gs.get_calendar_access_request', return_value=REQUEST_DATA_PENDING)
@patch('handlers.gs.is_user_connected', return_value=False) # Target not connected
async def test_button_approve_target_not_connected(mock_is_target_connected, mock_get_req, mock_update_callback, mock_context_args):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_ID}"
    await handlers.button_callback(mock_update_callback, mock_context_args)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "You (target user) need to connect your Google Calendar first via /connect_calendar before approving requests."
    )

@patch('handlers.gs.get_calendar_access_request', return_value=REQUEST_DATA_PENDING)
@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers.gs.update_calendar_access_request_status', return_value=False) # Update fails
async def test_button_approve_update_status_fails(
    mock_update_req_status, mock_is_target_connected, mock_get_req, mock_update_callback, mock_context_args
):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_ID}"
    await handlers.button_callback(mock_update_callback, mock_context_args)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "Failed to update request status. Please try again."
    )

# --- Tests for button_callback (Deny Flow) ---
@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.update_calendar_access_request_status')
async def test_button_deny_success(
    mock_update_req_status, mock_get_req, mock_update_callback, mock_context_args
):
    mock_update_callback.callback_query.data = f"deny_access_{TEST_REQUEST_ID}"
    mock_get_req.return_value = REQUEST_DATA_PENDING
    mock_update_req_status.return_value = True

    await handlers.button_callback(mock_update_callback, mock_context_args)

    mock_update_req_status.assert_called_once_with(TEST_REQUEST_ID, "denied")
    mock_context_args.bot.send_message.assert_called_once()
    requester_msg_kwargs = mock_context_args.bot.send_message.call_args.kwargs
    assert requester_msg_kwargs['chat_id'] == str(TEST_REQUESTER_ID)
    assert "was DENIED" in requester_msg_kwargs['text']
    # Check format of displayed time (uses _format_iso_datetime_for_display without target_tz)
    assert "2024-08-01 10:00 AM UTC" in requester_msg_kwargs['text'] # 10:00Z is UTC
    assert "2024-08-01 02:00 PM UTC" in requester_msg_kwargs['text'] # 14:00Z is UTC

    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        text="Access request DENIED. The requester has been notified."
    )

@patch('handlers.gs.get_calendar_access_request', return_value=REQUEST_DATA_ERROR_NOTIFYING)
@patch('handlers.gs.update_calendar_access_request_status', return_value=True)
async def test_button_deny_success_after_notify_error(
    mock_update_req_status, mock_get_req, mock_update_callback, mock_context_args
):
    mock_update_callback.callback_query.data = f"deny_access_{TEST_REQUEST_ID}"
    # Test when the status was 'error_notifying_target'
    await handlers.button_callback(mock_update_callback, mock_context_args)
    mock_update_req_status.assert_called_once_with(TEST_REQUEST_ID, "denied")
    # Other assertions similar to test_button_deny_success would follow


@patch('handlers.gs.get_calendar_access_request', return_value=None)
async def test_button_deny_request_not_found(mock_get_req, mock_update_callback, mock_context_args):
    mock_update_callback.callback_query.data = f"deny_access_{TEST_REQUEST_ID}"
    await handlers.button_callback(mock_update_callback, mock_context_args)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "This access request was not found or may have expired."
    )

@patch('handlers.gs.get_calendar_access_request')
async def test_button_deny_request_already_actioned(mock_get_req, mock_update_callback, mock_context_args):
    mock_update_callback.callback_query.data = f"deny_access_{TEST_REQUEST_ID}"
    mock_get_req.return_value = {**REQUEST_DATA_PENDING, "status": "denied"}
    await handlers.button_callback(mock_update_callback, mock_context_args)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        f"This request has already been actioned (status: denied)."
    )

@patch('handlers.gs.get_calendar_access_request')
async def test_button_deny_wrong_user_clicks(mock_get_req, mock_update_callback, mock_context_args):
    mock_update_callback.callback_query.data = f"deny_access_{TEST_REQUEST_ID}"
    mock_update_callback.callback_query.from_user = User(id=999, first_name="Wrong", is_bot=False)
    mock_update_callback.effective_user = mock_update_callback.callback_query.from_user
    mock_get_req.return_value = REQUEST_DATA_PENDING
    await handlers.button_callback(mock_update_callback, mock_context_args)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
         "Error: This request is not for you."
    )

@patch('handlers.gs.get_calendar_access_request', return_value=REQUEST_DATA_PENDING)
@patch('handlers.gs.update_calendar_access_request_status', return_value=False) # Update fails
async def test_button_deny_update_status_fails(
    mock_update_req_status, mock_get_req, mock_update_callback, mock_context_args
):
    mock_update_callback.callback_query.data = f"deny_access_{TEST_REQUEST_ID}"
    await handlers.button_callback(mock_update_callback, mock_context_args)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "Failed to update request status. Please try again."
    )

# --- Test for unhandled callback data ---
@patch('handlers.gs.get_calendar_access_request') # To avoid None error on unhandled
async def test_button_callback_unhandled(mock_get_req, mock_update_callback, mock_context_args):
    mock_update_callback.callback_query.data = "unhandled_callback_data_blah"
    # Mock get_req to return None or some default if it's ever called by unhandled logic
    mock_get_req.return_value = None 
    
    await handlers.button_callback(mock_update_callback, mock_context_args)
    
    mock_update_callback.callback_query.answer.assert_called_once()
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "Action not understood or expired."
    )
    # Ensure no other gs functions were called for unhandled data
    mock_get_req.assert_not_called() # Should not be called if prefix doesn't match
    mock_context_args.bot.send_message.assert_not_called()
    # Add more assertions here if specific functions should not be called.
    # For example, if update_calendar_access_request_status was patched:
    # mock_update_status.assert_not_called()
