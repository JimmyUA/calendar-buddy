import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, User, Message, Chat, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, KeyboardButtonRequestUsers, UsersShared, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import html
import time
from datetime import datetime, timedelta # Added datetime, timedelta
import pytz

# Import the handlers module
import handlers
import google_services as gs
import config # For pytz from config if needed, or directly import pytz
from .conftest import TEST_TIMEZONE # Using TEST_TIMEZONE from conftest for consistency

# Constants for testing
TEST_REQUESTER_ID = 100 # Keep as is, or use TEST_USER_ID from conftest if appropriate
TEST_REQUESTER_USERNAME = "requester_user"
TEST_REQUESTER_FIRST_NAME = "Requester"

TEST_TARGET_ID = 200
TEST_TARGET_ID_STR = str(TEST_TARGET_ID)
TEST_TARGET_USERNAME = "target_user"
TEST_TARGET_FIRST_NAME = "TargetUser"

TEST_REQUEST_DOC_ID = "firestore_req_doc_123"
# Use TEST_TIMEZONE_STR from conftest for requester if it matches intent
# For this file, let's assume requester is in New York, target in London for distinct testing.
REQUESTER_USER_TZ_STR = "America/New_York"
REQUESTER_USER_TZ = pytz.timezone(REQUESTER_USER_TZ_STR)
TARGET_USER_TZ_STR = "Europe/London"
TARGET_USER_TZ = pytz.timezone(TARGET_USER_TZ_STR)


# Base datetime for dynamic test data generation
BASE_TEST_NOW_HANDLER_ACCESS_UTC = datetime(2024, 8, 26, 12, 0, 0, tzinfo=pytz.utc) # A Monday 12:00 PM UTC

# Pytest mark for async functions
pytestmark = pytest.mark.asyncio

# --- Helper functions for dynamic test data ---
def _get_dynamic_request_data(status="pending", base_time_utc=None):
    if base_time_utc is None:
        base_time_utc = BASE_TEST_NOW_HANDLER_ACCESS_UTC

    start_iso = base_time_utc.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
    end_iso = base_time_utc.replace(hour=14, minute=0, second=0, microsecond=0).isoformat()
    return {
        "requester_id": str(TEST_REQUESTER_ID),
        "requester_name": TEST_REQUESTER_FIRST_NAME,
        "target_user_id": TEST_TARGET_ID_STR,
        "start_time_iso": start_iso,
        "end_time_iso": end_iso,
        "status": status
    }

def _get_dynamic_events_list(base_time_utc=None):
    if base_time_utc is None:
        base_time_utc = BASE_TEST_NOW_HANDLER_ACCESS_UTC

    event1_start = (base_time_utc + timedelta(hours=1)).replace(minute=0).isoformat()
    event1_end = (base_time_utc + timedelta(hours=2)).replace(minute=0).isoformat()
    event2_date = base_time_utc.date().isoformat()
    event2_date_end = (base_time_utc.date() + timedelta(days=1)).isoformat()
    return [
        {"id": "dyn_event_1", "summary": "Event 1 Dynamic CB", "start": {"dateTime": event1_start}, "end": {"dateTime": event1_end}},
        {"id": "dyn_event_2", "summary": "Event 2 Dynamic AllDay CB", "start": {"date": event2_date}, "end": {"date": event2_date_end}}
    ]

# --- Fixtures ---
@pytest.fixture
def mock_update_message():
    update = MagicMock(spec=Update)
    update.effective_user = User(id=TEST_REQUESTER_ID, first_name=TEST_REQUESTER_FIRST_NAME, is_bot=False, username=TEST_REQUESTER_USERNAME)
    update.message = AsyncMock(spec=Message)
    update.message.from_user = update.effective_user
    update.message.chat = MagicMock(spec=Chat)
    update.message.chat.id = TEST_REQUESTER_ID
    update.message.text = ""
    update.callback_query = None
    update.message.users_shared = None # Ensure it's None for command updates
    return update

@pytest.fixture
def mock_context(): # Renamed from mock_context_args for general use
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []
    context.bot = AsyncMock()
    context.user_data = {} # Initialize user_data
    return context

@pytest.fixture
def mock_update_callback():
    update = MagicMock(spec=Update)
    update.callback_query = AsyncMock()
    update.callback_query.from_user = User(id=TEST_TARGET_ID, first_name=TEST_TARGET_FIRST_NAME, is_bot=False, username=TEST_TARGET_USERNAME)
    update.callback_query.data = ""
    update.callback_query.message = AsyncMock(spec=Message)
    update.callback_query.message.chat_id = TEST_TARGET_ID
    update.effective_user = update.callback_query.from_user
    update.message = None
    return update

@pytest.fixture
def mock_update_users_shared():
    update = MagicMock(spec=Update)
    update.effective_user = User(id=TEST_REQUESTER_ID, first_name=TEST_REQUESTER_FIRST_NAME, is_bot=False, username=TEST_REQUESTER_USERNAME)
    update.message = AsyncMock(spec=Message)
    update.message.from_user = update.effective_user
    update.message.chat = MagicMock(spec=Chat)
    update.message.chat.id = TEST_REQUESTER_ID

    update.message.users_shared = MagicMock(spec=UsersShared)
    update.message.users_shared.request_id = 0 # Will be set in tests
    update.message.users_shared.users = [] # Will be set in tests
    update.callback_query = None
    return update


# --- Tests for request_calendar_access_command (Step 1) ---

@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers._get_user_tz_or_prompt')
@patch('handlers.llm_service.parse_date_range_llm')
@patch('handlers.datetime', wraps=datetime) # To mock datetime.now().timestamp()
async def test_request_calendar_access_step1_success(
    mock_datetime, mock_parse_range, mock_get_req_tz_prompt, mock_is_connected,
    mock_update_message, mock_context
):
    time_period_arg = "tomorrow 10am to 2pm"
    args = time_period_arg.split()
    mock_update_message.message.text = f"/request_access {time_period_arg}"
    mock_context.args = args

    mock_get_req_tz_prompt.return_value = REQUESTER_USER_TZ

    # Dynamic dates for mock_parse_range return value
    # e.g., "tomorrow 10am to 2pm" relative to BASE_TEST_NOW_HANDLER_ACCESS_UTC in REQUESTER_USER_TZ
    requester_now = BASE_TEST_NOW_HANDLER_ACCESS_UTC.astimezone(REQUESTER_USER_TZ)
    start_dt_req_tz = (requester_now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    end_dt_req_tz = start_dt_req_tz.replace(hour=14, minute=0)

    mock_parse_range.return_value = {
        "start_iso": start_dt_req_tz.isoformat(),
        "end_iso": end_dt_req_tz.isoformat()
    }

    # Mock datetime.now().timestamp() for predictable keyboard_request_id
    fixed_timestamp = int(BASE_TEST_NOW_HANDLER_ACCESS_UTC.timestamp())
    mock_datetime.now.return_value.timestamp.return_value = fixed_timestamp

    await handlers.request_calendar_access_command(mock_update_message, mock_context)

    mock_is_connected.assert_called_once_with(TEST_REQUESTER_ID)
    mock_get_req_tz_prompt.assert_called_once()
    # Check that parse_date_range_llm was called with the requester's current time in ISO format
    mock_parse_range.assert_called_once()
    assert mock_parse_range.call_args[0][0] == time_period_arg
    assert mock_parse_range.call_args[0][1] == requester_now.isoformat()


    # Verify user_data population
    assert mock_context.user_data['select_user_request_id'] == fixed_timestamp
    assert mock_context.user_data['calendar_request_period']['original'] == time_period_arg
    assert mock_context.user_data['calendar_request_period']['start_iso'] == start_dt_req_tz.isoformat()
    assert mock_context.user_data['calendar_request_period']['end_iso'] == end_dt_req_tz.isoformat()

    # Verify reply_text call for user selection
    mock_update_message.message.reply_text.assert_called_once()
    call_args, call_kwargs = mock_update_message.message.reply_text.call_args
    assert f"Okay, I have the time period: \"<b>{html.escape(time_period_arg)}</b>\"" in call_args[0]
    assert "Now, please select the user" in call_args[0]

    reply_markup = call_kwargs['reply_markup']
    assert isinstance(reply_markup, ReplyKeyboardMarkup)
    assert len(reply_markup.keyboard) == 1
    button = reply_markup.keyboard[0][0]
    assert isinstance(button, KeyboardButton)
    assert button.text == "Select User To Request Access From"
    assert isinstance(button.request_users, KeyboardButtonRequestUsers)
    assert button.request_users.request_id == mock_timestamp
    assert button.request_users.user_is_bot == False
    assert button.request_users.max_quantity == 1


async def test_request_calendar_access_step1_no_args(mock_update_message, mock_context):
    mock_context.args = [] # No time period
    await handlers.request_calendar_access_command(mock_update_message, mock_context)
    mock_update_message.message.reply_text.assert_called_once_with(
        "Usage: /request_access <time period description>\n"
        "Example: /request_access tomorrow 10am to 2pm"
    )

@patch('handlers.gs.is_user_connected', return_value=False)
async def test_request_calendar_access_step1_requester_not_connected(mock_is_connected, mock_update_message, mock_context):
    mock_context.args = ["tomorrow"]
    await handlers.request_calendar_access_command(mock_update_message, mock_context)
    mock_update_message.message.reply_text.assert_called_once_with(
        "You need to connect your Google Calendar first. Use /connect_calendar."
    )

@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers._get_user_tz_or_prompt', return_value=None) # Timezone prompt returns None
async def test_request_calendar_access_step1_tz_prompt_blocks(mock_get_req_tz, mock_is_connected, mock_update_message, mock_context):
    mock_context.args = ["tomorrow"]
    await handlers.request_calendar_access_command(mock_update_message, mock_context)
    # _get_user_tz_or_prompt already sends a message, so no new reply_text expected here
    mock_update_message.message.reply_text.assert_not_called() # Because _get_user_tz_or_prompt handles it

@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers._get_user_tz_or_prompt')
@patch('handlers.llm_service.parse_date_range_llm', return_value=None) # Time parsing fails
async def test_request_calendar_access_step1_time_parse_fail(
    mock_parse_range, mock_get_req_tz, mock_is_connected, mock_update_message, mock_context
):
    time_period_str = "gibberish time"
    mock_context.args = time_period_str.split()
    mock_get_req_tz.return_value = pytz.timezone(TEST_TIMEZONE_STR)
    await handlers.request_calendar_access_command(mock_update_message, mock_context)
    mock_update_message.message.reply_text.assert_called_once_with(
        f"Sorry, I couldn't understand the time period: '{html.escape(time_period_str)}'. "
        "Please try being more specific, e.g., 'tomorrow from 10am to 2pm' or 'next Monday'."
    )

# --- Tests for users_shared_handler (Step 2) ---

@patch('handlers.gs.add_calendar_access_request')
@patch('handlers.gs.get_user_timezone_str') # For target's TZ
@patch('handlers.gs.update_calendar_access_request_status') # For error case
async def test_users_shared_success(
    mock_update_req_status_err, mock_get_target_tz, mock_add_req,
    mock_update_users_shared, mock_context
):
    kb_request_id = 12345
    mock_update_users_shared.message.users_shared.request_id = kb_request_id
    mock_update_users_shared.message.users_shared.users = [User(id=TEST_TARGET_ID, first_name=TEST_TARGET_FIRST_NAME, is_bot=False, username=TEST_TARGET_USERNAME)]

    mock_context.user_data['select_user_request_id'] = kb_request_id

    # Dynamic dates for calendar_request_period
    original_period_desc = "next Tuesday 9-11am" # This is fine as a descriptor
    # Let's assume "next Tuesday" relative to BASE_TEST_NOW_HANDLER_ACCESS_UTC
    # BASE_TEST_NOW_HANDLER_ACCESS_UTC is a Monday. So next Tuesday is tomorrow.
    start_dt_utc = (BASE_TEST_NOW_HANDLER_ACCESS_UTC + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    end_dt_utc = start_dt_utc.replace(hour=11, minute=0)

    mock_context.user_data['calendar_request_period'] = {
        'original': original_period_desc,
        'start_iso': start_dt_utc.isoformat(),
        'end_iso': end_dt_utc.isoformat()
    }
    mock_add_req.return_value = TEST_REQUEST_DOC_ID
    mock_get_target_tz.return_value = TARGET_USER_TZ_STR # Target is in London

    await handlers.users_shared_handler(mock_update_users_shared, mock_context)

    # Check ack message and keyboard removal
    mock_update_users_shared.message.reply_text.assert_called_once_with("Processing your selection...", reply_markup=ReplyKeyboardRemove())

    # Check gs.add_calendar_access_request call
    mock_add_req.assert_called_once_with(
        requester_id=str(TEST_REQUESTER_ID),
        requester_name=TEST_REQUESTER_FIRST_NAME,
        target_user_id=TEST_TARGET_ID_STR,
        start_time_iso=start_dt_utc.isoformat(), # Dynamic
        end_time_iso=end_dt_utc.isoformat()     # Dynamic
    )
    # Check confirmation to requester
    mock_context.bot.send_message.assert_any_call(
        chat_id=str(TEST_REQUESTER_ID),
        text=f"Great! Your calendar access request for '<b>{html.escape(original_period_desc)}</b>' "
             f"has been sent to <b>{html.escape(TEST_TARGET_FIRST_NAME)}</b>."
             f" (Request ID: `{TEST_REQUEST_DOC_ID}`)",
        parse_mode=ParseMode.HTML
    )
    # Check notification to target
    target_notification_kwargs = None
    for call_args_tuple in mock_context.bot.send_message.call_args_list:
        # call_args_tuple is a unittest.mock.call object, which is like a tuple (args, kwargs)
        # We need to access its kwargs attribute.
        current_kwargs = call_args_tuple.kwargs
        if current_kwargs.get('chat_id') == TEST_TARGET_ID_STR:
            target_notification_kwargs = current_kwargs
            break

    assert target_notification_kwargs is not None
    assert f"User <b>{TEST_REQUESTER_FIRST_NAME}</b> (Telegram: @{TEST_REQUESTER_USERNAME})" in target_notification_kwargs['text']

    # Dynamic assertion for formatted times in target's timezone
    start_display_target = handlers._format_iso_datetime_for_display(start_dt_utc.isoformat(), TARGET_USER_TZ_STR)
    end_display_target = handlers._format_iso_datetime_for_display(end_dt_utc.isoformat(), TARGET_USER_TZ_STR)

    assert f"<b>From:</b> {start_display_target}" in target_notification_kwargs['text']
    assert f"<b>To:</b>   {end_display_target}" in target_notification_kwargs['text']

    assert isinstance(target_notification_kwargs['reply_markup'], InlineKeyboardMarkup)
    buttons = target_notification_kwargs['reply_markup'].inline_keyboard[0]
    assert buttons[0].callback_data == f"approve_access_{TEST_REQUEST_DOC_ID}"
    assert buttons[1].callback_data == f"deny_access_{TEST_REQUEST_DOC_ID}"

    # Check user_data cleanup
    assert 'select_user_request_id' not in mock_context.user_data
    assert 'calendar_request_period' not in mock_context.user_data
    mock_update_req_status_err.assert_not_called()


async def test_users_shared_mismatched_request_id(mock_update_users_shared, mock_context):
    mock_update_users_shared.message.users_shared.request_id = 56789
    mock_context.user_data['select_user_request_id'] = 12345 # Different ID

    await handlers.users_shared_handler(mock_update_users_shared, mock_context)
    mock_context.bot.send_message.assert_called_once_with(
        chat_id=str(TEST_REQUESTER_ID),
        text="This user selection is unexpected or has expired. Please try the /request_access command again."
    )
    mock_update_users_shared.message.reply_text.assert_called_once_with("Processing your selection...", reply_markup=ReplyKeyboardRemove())


async def test_users_shared_no_users_selected(mock_update_users_shared, mock_context):
    kb_request_id = 12345
    mock_update_users_shared.message.users_shared.request_id = kb_request_id
    mock_update_users_shared.message.users_shared.users = [] # No users shared
    mock_context.user_data['select_user_request_id'] = kb_request_id

    await handlers.users_shared_handler(mock_update_users_shared, mock_context)
    mock_context.bot.send_message.assert_called_once_with(
        chat_id=str(TEST_REQUESTER_ID),
        text="No user was selected. Please try again if you want to request access."
    )
    assert 'select_user_request_id' not in mock_context.user_data
    assert 'calendar_request_period' not in mock_context.user_data


async def test_users_shared_missing_period_data(mock_update_users_shared, mock_context):
    kb_request_id = 12345
    mock_update_users_shared.message.users_shared.request_id = kb_request_id
    mock_update_users_shared.message.users_shared.users = [User(id=TEST_TARGET_ID, first_name=TEST_TARGET_FIRST_NAME, is_bot=False)]
    mock_context.user_data['select_user_request_id'] = kb_request_id
    # 'calendar_request_period' is missing from user_data

    await handlers.users_shared_handler(mock_update_users_shared, mock_context)
    mock_context.bot.send_message.assert_called_once_with(
        chat_id=str(TEST_REQUESTER_ID),
        text="Something went wrong, I don't have the time period for your request. Please start over with /request_access."
    )

async def test_users_shared_target_is_requester(mock_update_users_shared, mock_context):
    kb_request_id = 12345
    mock_update_users_shared.message.users_shared.request_id = kb_request_id
    # Target user is the same as requester
    mock_update_users_shared.message.users_shared.users = [User(id=TEST_REQUESTER_ID, first_name=TEST_REQUESTER_FIRST_NAME, is_bot=False)]
    mock_context.user_data['select_user_request_id'] = kb_request_id
    mock_context.user_data['calendar_request_period'] = {'original': 't', 'start_iso': 's', 'end_iso': 'e'}

    await handlers.users_shared_handler(mock_update_users_shared, mock_context)
    mock_context.bot.send_message.assert_called_once_with(
        chat_id=str(TEST_REQUESTER_ID),
        text="You cannot request calendar access from yourself. Please try again with a different user."
    )

@patch('handlers.gs.add_calendar_access_request', return_value=None) # Simulate Firestore add failure
async def test_users_shared_add_request_fails(mock_add_req, mock_update_users_shared, mock_context):
    kb_request_id = 12345
    mock_update_users_shared.message.users_shared.request_id = kb_request_id
    mock_update_users_shared.message.users_shared.users = [User(id=TEST_TARGET_ID, first_name=TEST_TARGET_FIRST_NAME, is_bot=False)]
    mock_context.user_data['select_user_request_id'] = kb_request_id
    mock_context.user_data['calendar_request_period'] = {'original': 't', 'start_iso': 's', 'end_iso': 'e'}

    await handlers.users_shared_handler(mock_update_users_shared, mock_context)
    mock_context.bot.send_message.assert_called_once_with(
        chat_id=str(TEST_REQUESTER_ID),
        text="Sorry, there was an internal error trying to store your access request. Please try again later."
    )

@patch('handlers.gs.add_calendar_access_request', return_value=TEST_REQUEST_DOC_ID)
@patch('handlers.gs.get_user_timezone_str', return_value=None) # Target TZ not set
@patch('handlers.gs.update_calendar_access_request_status')
async def test_users_shared_notify_target_fails(
    mock_update_status, mock_get_target_tz, mock_add_req,
    mock_update_users_shared, mock_context
):
    kb_request_id = 12345
    mock_update_users_shared.message.users_shared.request_id = kb_request_id
    mock_update_users_shared.message.users_shared.users = [User(id=TEST_TARGET_ID, first_name=TEST_TARGET_FIRST_NAME, is_bot=False, username=TEST_TARGET_USERNAME)]
    mock_context.user_data['select_user_request_id'] = kb_request_id
    mock_context.user_data['calendar_request_period'] = {'original': 't', 'start_iso': 's', 'end_iso': 'e'}

    # Simulate failure when sending message to target
    mock_context.bot.send_message.side_effect = [
        AsyncMock(), # First call (to requester, informing of success)
        Exception("Cannot send to target") # Second call (to target)
    ]

    await handlers.users_shared_handler(mock_update_users_shared, mock_context)

    # Check that the second send_message (to requester about failure) happened
    assert mock_context.bot.send_message.call_count == 2
    last_call_args_list = mock_context.bot.send_message.call_args_list

    # First call (success to requester)
    assert last_call_args_list[0].kwargs['chat_id'] == str(TEST_REQUESTER_ID)
    assert "Great! Your calendar access request" in last_call_args_list[0].kwargs['text']

    # Second call (failure info to requester)
    assert last_call_args_list[1].kwargs['chat_id'] == str(TEST_REQUESTER_ID)
    assert "I've stored your request" in last_call_args_list[1].kwargs['text']
    assert "but I couldn't send them a direct notification" in last_call_args_list[1].kwargs['text']

    mock_update_status.assert_called_once_with(TEST_REQUEST_DOC_ID, "error_notifying_target")


# --- Tests for button_callback (Approve/Deny Flow) ---

# Helper to create dynamic request data for button callback tests
def _get_dynamic_request_data(status="pending", base_time_utc=None):
    if base_time_utc is None:
        base_time_utc = BASE_TEST_NOW_HANDLER_ACCESS_UTC

    start_iso = base_time_utc.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
    end_iso = base_time_utc.replace(hour=14, minute=0, second=0, microsecond=0).isoformat()
    return {
        "requester_id": str(TEST_REQUESTER_ID),
        "requester_name": TEST_REQUESTER_FIRST_NAME,
        "target_user_id": TEST_TARGET_ID_STR,
        "start_time_iso": start_iso,
        "end_time_iso": end_iso,
        "status": status
    }

# Helper to create dynamic events list for button callback tests
def _get_dynamic_events_list(base_time_utc=None):
    if base_time_utc is None:
        base_time_utc = BASE_TEST_NOW_HANDLER_ACCESS_UTC

    event1_start = (base_time_utc + timedelta(hours=1)).replace(minute=0).isoformat()
    event1_end = (base_time_utc + timedelta(hours=2)).replace(minute=0).isoformat()
    event2_date = base_time_utc.date().isoformat()
    event2_date_end = (base_time_utc.date() + timedelta(days=1)).isoformat()
    return [
        {"id": "dyn_event_1", "summary": "Event 1 Dynamic CB", "start": {"dateTime": event1_start}, "end": {"dateTime": event1_end}},
        {"id": "dyn_event_2", "summary": "Event 2 Dynamic AllDay CB", "start": {"date": event2_date}, "end": {"date": event2_date_end}}
    ]

# Note: The old global constants REQUEST_DATA_PENDING, REQUEST_DATA_ERROR_NOTIFYING,
# and EVENTS_LIST_EXAMPLE are confirmed to be removed from the file.

@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.is_user_connected')
@patch('handlers.gs.update_calendar_access_request_status')
@patch('handlers.gs.get_calendar_events')
@patch('handlers.gs.get_user_timezone_str')
async def test_button_approve_success(
    mock_get_target_tz_for_events, mock_get_events, mock_update_req_status, mock_is_target_connected,
    mock_get_req, mock_update_callback, mock_context
):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_DOC_ID}"
    
    # Use helper functions to get dynamic data
    dynamic_request_data = _get_dynamic_request_data(status="pending")
    mock_get_req.return_value = dynamic_request_data

    dynamic_events_list = _get_dynamic_events_list() # Using helper

    mock_is_target_connected.return_value = True
    mock_update_req_status.return_value = True
    mock_get_events.return_value = dynamic_events_list
    mock_get_target_tz_for_events.return_value = TARGET_USER_TZ_STR

    await handlers.button_callback(mock_update_callback, mock_context)

    # Assertions
    mock_update_callback.callback_query.answer.assert_called_once()
    mock_get_req.assert_called_once_with(TEST_REQUEST_DOC_ID)
    mock_is_target_connected.assert_called_once_with(TEST_TARGET_ID)
    mock_update_req_status.assert_called_once_with(TEST_REQUEST_DOC_ID, STATUS_APPROVED)
    mock_get_events.assert_called_once_with(TEST_TARGET_ID, dynamic_request_data["start_time_iso"], dynamic_request_data["end_time_iso"])

    mock_context.bot.send_message.assert_called_once()
    requester_msg_kwargs = mock_context.bot.send_message.call_args.kwargs
    assert requester_msg_kwargs['chat_id'] == str(TEST_REQUESTER_ID)
    assert "was APPROVED" in requester_msg_kwargs['text']

    # Check for dynamic event summaries
    assert dynamic_events_list[0]["summary"] in requester_msg_kwargs['text']
    formatted_event1_time = handlers._format_event_time(dynamic_events_list[0], TARGET_USER_TZ)
    assert formatted_event1_time in requester_msg_kwargs['text']

    assert dynamic_events_list[1]["summary"] in requester_msg_kwargs['text']
    formatted_event2_time = handlers._format_event_time(dynamic_events_list[1], TARGET_USER_TZ)
    assert formatted_event2_time in requester_msg_kwargs['text']
    assert "All day" in formatted_event2_time

    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        text="Access request APPROVED. The requester has been notified with the events."
    )

@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.update_calendar_access_request_status')
async def test_button_deny_success(
    mock_update_req_status, mock_get_req, mock_update_callback, mock_context
):
    mock_update_callback.callback_query.data = f"deny_access_{TEST_REQUEST_DOC_ID}"
    dynamic_request_data = _get_dynamic_request_data() # Using helper
    mock_get_req.return_value = dynamic_request_data
    mock_update_req_status.return_value = True

    await handlers.button_callback(mock_update_callback, mock_context)

    mock_update_req_status.assert_called_once_with(TEST_REQUEST_DOC_ID, "denied") # STATUS_DENIED if you have one
    mock_context.bot.send_message.assert_called_once()
    requester_msg_text = mock_context.bot.send_message.call_args.kwargs['text']
    assert "was DENIED" in requester_msg_text
    assert handlers._format_iso_datetime_for_display(dynamic_request_data["start_time_iso"]) in requester_msg_text
    assert handlers._format_iso_datetime_for_display(dynamic_request_data["end_time_iso"]) in requester_msg_text

    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        text="Access request DENIED. The requester has been notified."
    )

@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.update_calendar_access_request_status')
async def test_button_deny_success_after_notify_error(
    mock_update_req_status, mock_get_req, mock_update_callback, mock_context
):
    dynamic_request_data = _get_dynamic_request_data(status="error_notifying_target") # Using helper
    mock_get_req.return_value = dynamic_request_data
    mock_update_req_status.return_value = True
    mock_update_callback.callback_query.data = f"deny_access_{TEST_REQUEST_DOC_ID}"
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_req_status.assert_called_once_with(TEST_REQUEST_DOC_ID, "denied") # STATUS_DENIED
    mock_context.bot.send_message.assert_called_once()
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        text="Access request DENIED. The requester has been notified."
    )

@patch('handlers.gs.get_calendar_access_request', return_value=None)
async def test_button_approve_request_not_found(mock_get_req, mock_update_callback, mock_context):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_DOC_ID}"
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "This access request was not found or may have expired."
    )

@patch('handlers.gs.get_calendar_access_request')
async def test_button_approve_request_already_actioned(mock_get_req, mock_update_callback, mock_context):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_DOC_ID}"
    dynamic_request_data = _get_dynamic_request_data(status=STATUS_APPROVED) # Using helper and constant
    mock_get_req.return_value = dynamic_request_data
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        f"This request has already been actioned (status: {STATUS_APPROVED})."
    )

@patch('handlers.gs.get_calendar_access_request')
async def test_button_approve_wrong_user_clicks(mock_get_req, mock_update_callback, mock_context):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_DOC_ID}"
    mock_update_callback.callback_query.from_user = User(id=999, first_name="Wrong", is_bot=False, username="wrong_user")
    mock_update_callback.effective_user = mock_update_callback.callback_query.from_user

    dynamic_request_data = _get_dynamic_request_data() # Using helper
    mock_get_req.return_value = dynamic_request_data
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
         "Error: This request is not for you."
    )

@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.is_user_connected', return_value=False)
async def test_button_approve_target_not_connected(mock_is_target_connected, mock_get_req, mock_update_callback, mock_context):
    mock_get_req.return_value = _get_dynamic_request_data() # Using helper
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_DOC_ID}"
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "You (target user) need to connect your Google Calendar first via /connect_calendar before approving requests."
    )

@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers.gs.update_calendar_access_request_status', return_value=False)
async def test_button_approve_update_status_fails(
    mock_update_req_status, mock_is_target_connected, mock_get_req, mock_update_callback, mock_context
):
    mock_get_req.return_value = _get_dynamic_request_data() # Using helper
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_DOC_ID}"
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "Failed to update request status. Please try again."
    )

@patch('handlers.gs.get_calendar_access_request')
async def test_button_callback_unhandled(mock_get_req, mock_update_callback, mock_context):
    mock_update_callback.callback_query.data = "unhandled_callback_data_blah"
    mock_get_req.return_value = None
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_callback.callback_query.answer.assert_called_once()
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "Action not understood or expired."
    )
    mock_get_req.assert_not_called()
    mock_context.bot.send_message.assert_not_called()
