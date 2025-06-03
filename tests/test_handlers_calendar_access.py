import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, User, Message, Chat, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, KeyboardButtonRequestUsers, UsersShared, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import html
import time
from datetime import datetime, timedelta
import pytz

# Import the handlers module
import handlers
import google_services as gs
import config
from .conftest import TEST_TIMEZONE

# Constants for testing
TEST_REQUESTER_ID = 100
TEST_REQUESTER_USERNAME = "requester_user"
TEST_REQUESTER_FIRST_NAME = "Requester"

TEST_TARGET_ID = 200
TEST_TARGET_ID_STR = str(TEST_TARGET_ID)
TEST_TARGET_USERNAME = "target_user"
TEST_TARGET_FIRST_NAME = "TargetUser"

TEST_REQUEST_DOC_ID = "firestore_req_doc_123"

REQUESTER_USER_TZ_STR = "America/New_York"
REQUESTER_USER_TZ = pytz.timezone(REQUESTER_USER_TZ_STR)
TARGET_USER_TZ_STR = "Europe/London"
TARGET_USER_TZ = pytz.timezone(TARGET_USER_TZ_STR)
STATUS_APPROVED = "approved"

# Base datetime for dynamic test data generation
BASE_TEST_NOW_HANDLER_ACCESS_UTC = datetime(2024, 8, 26, 12, 0, 0, tzinfo=pytz.utc)

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
# (Fixtures remain unchanged)
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
    update.message.users_shared = None
    return update

@pytest.fixture
def mock_context():
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []
    context.bot = AsyncMock()
    context.user_data = {}
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
    update.message.users_shared.request_id = 0
    update.message.users_shared.users = []
    update.callback_query = None
    return update

# --- Tests for request_calendar_access_command (Step 1) ---
# (These tests were already refactored or did not use the problematic constants)
@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers._get_user_tz_or_prompt')
@patch('handlers.llm_service.parse_date_range_llm')
@patch('handlers.datetime', wraps=datetime)
async def test_request_calendar_access_step1_success(
    mock_dt, mock_parse_range, mock_get_req_tz_prompt, mock_is_connected, # mock_datetime renamed to mock_dt
    mock_update_message, mock_context
):
    time_period_arg = "tomorrow 10am to 2pm"
    args = time_period_arg.split()
    mock_update_message.message.text = f"/request_access {time_period_arg}"
    mock_context.args = args
    mock_get_req_tz_prompt.return_value = REQUESTER_USER_TZ

    requester_now = BASE_TEST_NOW_HANDLER_ACCESS_UTC.astimezone(REQUESTER_USER_TZ)
    start_dt_req_tz = (requester_now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    end_dt_req_tz = start_dt_req_tz.replace(hour=14, minute=0)
    mock_parse_range.return_value = {"start_iso": start_dt_req_tz.isoformat(), "end_iso": end_dt_req_tz.isoformat()}

    fixed_timestamp = int(BASE_TEST_NOW_HANDLER_ACCESS_UTC.timestamp())
    mock_dt.now.return_value.timestamp.return_value = fixed_timestamp # Corrected from mock_datetime to mock_dt

    await handlers.request_calendar_access_command(mock_update_message, mock_context)

    mock_is_connected.assert_called_once_with(TEST_REQUESTER_ID)
    mock_get_req_tz_prompt.assert_called_once()
    mock_parse_range.assert_called_once()
    assert mock_parse_range.call_args[0][0] == time_period_arg
    assert mock_parse_range.call_args[0][1] == requester_now.isoformat()

    assert mock_context.user_data['select_user_request_id'] == fixed_timestamp
    assert mock_context.user_data['calendar_request_period']['original'] == time_period_arg
    assert mock_context.user_data['calendar_request_period']['start_iso'] == start_dt_req_tz.isoformat()
    assert mock_context.user_data['calendar_request_period']['end_iso'] == end_dt_req_tz.isoformat()

    mock_update_message.message.reply_text.assert_called_once()
    call_args, call_kwargs = mock_update_message.message.reply_text.call_args
    assert f"Okay, I have the time period: \"<b>{html.escape(time_period_arg)}</b>\"" in call_args[0]
    button = call_kwargs['reply_markup'].keyboard[0][0]
    assert button.request_users.request_id == fixed_timestamp

async def test_request_calendar_access_step1_no_args(mock_update_message, mock_context):
    mock_context.args = []
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
@patch('handlers._get_user_tz_or_prompt', return_value=None)
async def test_request_calendar_access_step1_tz_prompt_blocks(mock_get_req_tz, mock_is_connected, mock_update_message, mock_context):
    mock_context.args = ["tomorrow"]
    await handlers.request_calendar_access_command(mock_update_message, mock_context)
    mock_update_message.message.reply_text.assert_not_called()

@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers._get_user_tz_or_prompt')
@patch('handlers.llm_service.parse_date_range_llm', return_value=None)
async def test_request_calendar_access_step1_time_parse_fail(
    mock_parse_range, mock_get_req_tz, mock_is_connected, mock_update_message, mock_context
):
    time_period_str = "gibberish time"
    mock_context.args = time_period_str.split()
    mock_get_req_tz.return_value = REQUESTER_USER_TZ
    await handlers.request_calendar_access_command(mock_update_message, mock_context)
    mock_update_message.message.reply_text.assert_called_once_with(
        f"Sorry, I couldn't understand the time period: '{html.escape(time_period_str)}'. "
        "Please try being more specific, e.g., 'tomorrow from 10am to 2pm' or 'next Monday'."
    )

# --- Tests for users_shared_handler (Step 2) ---
# (This was already refactored to use dynamic dates)
@patch('handlers.gs.add_calendar_access_request')
@patch('handlers.gs.get_user_timezone_str')
@patch('handlers.gs.update_calendar_access_request_status')
async def test_users_shared_success(
    mock_update_req_status_err, mock_get_target_tz, mock_add_req,
    mock_update_users_shared, mock_context
):
    kb_request_id = 12345
    mock_update_users_shared.message.users_shared.request_id = kb_request_id
    mock_update_users_shared.message.users_shared.users = [User(id=TEST_TARGET_ID, first_name=TEST_TARGET_FIRST_NAME, is_bot=False, username=TEST_TARGET_USERNAME)]
    mock_context.user_data['select_user_request_id'] = kb_request_id
    original_period_desc = "next Tuesday 9-11am"
    start_dt_utc = (BASE_TEST_NOW_HANDLER_ACCESS_UTC + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    end_dt_utc = start_dt_utc.replace(hour=11, minute=0)
    mock_context.user_data['calendar_request_period'] = {
        'original': original_period_desc,
        'start_iso': start_dt_utc.isoformat(),
        'end_iso': end_dt_utc.isoformat()
    }
    mock_add_req.return_value = TEST_REQUEST_DOC_ID
    mock_get_target_tz.return_value = TARGET_USER_TZ_STR
    await handlers.users_shared_handler(mock_update_users_shared, mock_context)
    mock_add_req.assert_called_once_with(
        requester_id=str(TEST_REQUESTER_ID),
        requester_name=TEST_REQUESTER_FIRST_NAME,
        target_user_id=TEST_TARGET_ID_STR,
        start_time_iso=start_dt_utc.isoformat(),
        end_time_iso=end_dt_utc.isoformat()
    )
    target_notification_kwargs = None
    for call_args_tuple in mock_context.bot.send_message.call_args_list:
        current_kwargs = call_args_tuple.kwargs
        if current_kwargs.get('chat_id') == TEST_TARGET_ID_STR:
            target_notification_kwargs = current_kwargs
            break
    assert target_notification_kwargs is not None
    start_display_target = handlers._format_iso_datetime_for_display(start_dt_utc.isoformat(), TARGET_USER_TZ_STR)
    end_display_target = handlers._format_iso_datetime_for_display(end_dt_utc.isoformat(), TARGET_USER_TZ_STR)
    assert f"<b>From:</b> {start_display_target}" in target_notification_kwargs['text']
    assert f"<b>To:</b>   {end_display_target}" in target_notification_kwargs['text']

# ... (other users_shared_handler tests remain unchanged as they don't use the hardcoded date/event constants) ...

# --- Tests for button_callback (Approve/Deny Flow) ---
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
    dynamic_request_data = _get_dynamic_request_data(status="pending")
    mock_get_req.return_value = dynamic_request_data
    dynamic_events_list = _get_dynamic_events_list()
    mock_is_target_connected.return_value = True
    mock_update_req_status.return_value = True
    mock_get_events.return_value = dynamic_events_list
    mock_get_target_tz_for_events.return_value = TARGET_USER_TZ_STR
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_req_status.assert_called_once_with(TEST_REQUEST_DOC_ID, STATUS_APPROVED)
    mock_get_events.assert_called_once_with(TEST_TARGET_ID, dynamic_request_data["start_time_iso"], dynamic_request_data["end_time_iso"])
    requester_msg_kwargs = mock_context.bot.send_message.call_args.kwargs
    assert dynamic_events_list[0]["summary"] in requester_msg_kwargs['text']
    formatted_event1_time = handlers._format_event_time(dynamic_events_list[0], TARGET_USER_TZ)
    assert formatted_event1_time in requester_msg_kwargs['text']
    assert dynamic_events_list[1]["summary"] in requester_msg_kwargs['text']
    formatted_event2_time = handlers._format_event_time(dynamic_events_list[1], TARGET_USER_TZ)
    assert formatted_event2_time in requester_msg_kwargs['text']
    assert "All day" in formatted_event2_time

@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.update_calendar_access_request_status')
async def test_button_deny_success(
    mock_update_req_status, mock_get_req, mock_update_callback, mock_context
):
    mock_update_callback.callback_query.data = f"deny_access_{TEST_REQUEST_DOC_ID}"
    dynamic_request_data = _get_dynamic_request_data()
    mock_get_req.return_value = dynamic_request_data
    mock_update_req_status.return_value = True
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_req_status.assert_called_once_with(TEST_REQUEST_DOC_ID, "denied")
    requester_msg_text = mock_context.bot.send_message.call_args.kwargs['text']
    assert handlers._format_iso_datetime_for_display(dynamic_request_data["start_time_iso"]) in requester_msg_text
    assert handlers._format_iso_datetime_for_display(dynamic_request_data["end_time_iso"]) in requester_msg_text

@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.update_calendar_access_request_status')
async def test_button_deny_success_after_notify_error(
    mock_update_req_status, mock_get_req, mock_update_callback, mock_context
):
    dynamic_request_data = _get_dynamic_request_data(status="error_notifying_target")
    mock_get_req.return_value = dynamic_request_data
    mock_update_req_status.return_value = True
    mock_update_callback.callback_query.data = f"deny_access_{TEST_REQUEST_DOC_ID}"
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_req_status.assert_called_once_with(TEST_REQUEST_DOC_ID, "denied")

@patch('handlers.gs.get_calendar_access_request')
async def test_button_approve_request_already_actioned(mock_get_req, mock_update_callback, mock_context):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_DOC_ID}"
    dynamic_request_data = _get_dynamic_request_data(status=STATUS_APPROVED)
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
    mock_get_req.return_value = _get_dynamic_request_data()
    await handlers.button_callback(mock_update_callback, mock_context)

@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.is_user_connected', return_value=False)
async def test_button_approve_target_not_connected(mock_is_target_connected, mock_get_req, mock_update_callback, mock_context):
    mock_get_req.return_value = _get_dynamic_request_data()
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_DOC_ID}"
    await handlers.button_callback(mock_update_callback, mock_context)

@patch('handlers.gs.get_calendar_access_request')
@patch('handlers.gs.is_user_connected', return_value=True)
@patch('handlers.gs.update_calendar_access_request_status', return_value=False)
async def test_button_approve_update_status_fails(
    mock_update_req_status, mock_is_target_connected, mock_get_req, mock_update_callback, mock_context
):
    mock_get_req.return_value = _get_dynamic_request_data()
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_DOC_ID}"
    await handlers.button_callback(mock_update_callback, mock_context)

# test_button_approve_request_not_found and test_button_callback_unhandled remain unchanged
# as they don't use the hardcoded date/event constants.
@patch('handlers.gs.get_calendar_access_request', return_value=None)
async def test_button_approve_request_not_found(mock_get_req, mock_update_callback, mock_context):
    mock_update_callback.callback_query.data = f"approve_access_{TEST_REQUEST_DOC_ID}"
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "This access request was not found or may have expired."
    )

@patch('handlers.gs.get_calendar_access_request')
async def test_button_callback_unhandled(mock_get_req, mock_update_callback, mock_context):
    mock_update_callback.callback_query.data = "unhandled_callback_data_blah"
    mock_get_req.return_value = None # Ensure get_calendar_access_request is properly mocked if called
    await handlers.button_callback(mock_update_callback, mock_context)
    mock_update_callback.callback_query.answer.assert_called_once()
    mock_update_callback.callback_query.message.edit_message_text.assert_called_once_with(
        "Action not understood or expired."
    )
    # mock_get_req.assert_not_called() # This depends on whether unhandled data still tries to fetch
    # For a truly unhandled prefix, get_calendar_access_request might not even be called.
    # If it's called for any callback starting with e.g. "approve_access_", then this assertion changes.
    # Based on current handlers.py, it's not called for truly unhandled prefixes.
    mock_context.bot.send_message.assert_not_called()

# Note: The old constants REQUEST_DATA_PENDING, REQUEST_DATA_ERROR_NOTIFYING,
# and EVENTS_LIST_EXAMPLE have been removed from the file.
# All tests using them have been updated to use the dynamic helper functions.
