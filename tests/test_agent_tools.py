# tests/test_agent_tools.py
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
import pytz

import config  # To check pending state changes
# Import tools AFTER fixtures might patch dependencies
from llm.tools.create_calendar import CreateCalendarEventTool
from llm.tools.delete_calendar import DeleteCalendarEventTool
from llm.tools.get_current_time_tool import GetCurrentTimeTool
from llm.tools.read_calendar import ReadCalendarEventsTool
from .conftest import TEST_USER_ID, TEST_TIMEZONE_STR, TEST_EVENT_ID

pytestmark = pytest.mark.asyncio

# --- Create Tool ---
@pytest.fixture
def create_tool():
    return CreateCalendarEventTool(user_id=TEST_USER_ID, user_timezone_str=TEST_TIMEZONE_STR)

async def test_create_tool_arun_success(create_tool, mock_llm_service, mocker):
    event_description = "Meeting with Bob tomorrow 3pm about project X"
    extracted_event_data = {
        "summary": "Meeting with Bob",
        "start": {"dateTime": "2024-08-20T15:00:00-07:00", "timeZone": TEST_TIMEZONE_STR},
        "end": {"dateTime": "2024-08-20T16:00:00-07:00", "timeZone": TEST_TIMEZONE_STR},
        "description": "project X discussion",
        "location": None
    }
    # Mock the specific LLM function called by the tool
    mock_extract = mocker.patch('llm.tools.create_calendar.llm_service.extract_create_args_llm',
                                return_value=extracted_event_data)

    # Patch datetime.now used within the tool
    mock_now = MagicMock()
    mock_now.isoformat.return_value = "2024-08-19T10:00:00-07:00" # Example ISO time
    # Patch datetime inside the tool's module
    mocker.patch('llm.tools.create_calendar.datetime', now=lambda tz: mock_now)

    # Patch config directly where state is stored
    with patch.dict(config.pending_events, {}), patch.dict(config.pending_deletions, {}):
        result_string = await create_tool._arun(event_description=event_description)

        # Assert LLM extraction was called correctly
        mock_extract.assert_called_once_with(event_description, mock_now.isoformat(), TEST_TIMEZONE_STR)

        # Assert the result is the confirmation string
        assert "Should I add this to your calendar?" in result_string
        assert "Summary: Meeting with Bob" in result_string
        assert "Start: Tue, Aug 20, 2024 at 03:00 PM PDT" in result_string # Check formatted time

        # Assert pending state was stored
        assert config.pending_events.get(TEST_USER_ID) == extracted_event_data
        assert TEST_USER_ID not in config.pending_deletions # Ensure delete state was cleared if existed

async def test_create_tool_arun_llm_fail(create_tool, mock_llm_service, mocker):
    event_description = "invalid stuff"
    # Mock the LLM function to return None (failure)
    mock_extract = mocker.patch('llm.tools.create_calendar.llm_service.extract_create_args_llm', return_value=None)
    mocker.patch('llm.tools.create_calendar.datetime') # Mock datetime just in case

    with patch.dict(config.pending_events, {}):
        result_string = await create_tool._arun(event_description=event_description)

        assert "Error: Could not extract valid event details" in result_string
        assert not config.pending_events # No pending event stored

# --- Delete Tool ---
@pytest.fixture
def delete_tool():
    return DeleteCalendarEventTool(user_id=TEST_USER_ID, user_timezone_str=TEST_TIMEZONE_STR)

async def test_delete_tool_arun_success(delete_tool, mocker):
    event_id_to_delete = TEST_EVENT_ID
    mock_event_details = {
        'id': event_id_to_delete,
        'summary': 'Event To Delete',
        'start': {'dateTime': '2024-08-21T09:00:00-07:00'},
        'end': {'dateTime': '2024-08-21T10:00:00-07:00'}
    }
    # Mock the google_services function called by the tool
    mock_get_event = mocker.patch('llm.tools.delete_calendar.gs.get_calendar_event_by_id',
                                  return_value=mock_event_details)
    # Mock the utility function for time formatting
    mocker.patch('llm.tools.delete_calendar._format_event_time', return_value="Wed, Aug 21, 09:00 AM PDT")

    with patch.dict(config.pending_deletions, {}), patch.dict(config.pending_events, {}):
        result_string = await delete_tool._arun(event_id=event_id_to_delete)

        # Assert gs function was called
        mock_get_event.assert_called_once_with(TEST_USER_ID, event_id_to_delete)

        # Assert confirmation string
        assert "Should I delete this event?" in result_string
        assert "Found event: 'Event To Delete'" in result_string
        assert "(Wed, Aug 21, 09:00 AM PDT)" in result_string

        # Assert pending state
        assert config.pending_deletions.get(TEST_USER_ID) == {'event_id': event_id_to_delete, 'summary': 'Event To Delete'}
        assert TEST_USER_ID not in config.pending_events # Ensure create state cleared

async def test_delete_tool_arun_invalid_id(delete_tool, mocker):
     with patch.dict(config.pending_deletions, {}):
        result_string = await delete_tool._arun(event_id="") # Empty ID
        assert "Error: A valid event ID is required" in result_string
        assert not config.pending_deletions

async def test_delete_tool_arun_event_not_found(delete_tool, mocker):
    event_id_not_found = "bad_id"
    # Mock gs function to return None
    mock_get_event = mocker.patch('llm.tools.delete_calendar.gs.get_calendar_event_by_id', return_value=None)

    with patch.dict(config.pending_deletions, {}):
        result_string = await delete_tool._arun(event_id=event_id_not_found)

        assert f"Error: Could not find event with ID '{event_id_not_found}'" in result_string
        assert not config.pending_deletions

# --- Read Tool ---
@pytest.fixture
def read_tool():
    return ReadCalendarEventsTool(user_id=TEST_USER_ID, user_timezone_str=TEST_TIMEZONE_STR)

async def test_read_tool_arun_success(read_tool, mocker):
    time_period = "tomorrow"
    mock_llm_args = {'start_iso': '2024-08-20T00:00:00-07:00', 'end_iso': '2024-08-20T23:59:59-07:00'}
    mock_events = [{'id':'1', 'summary':'Morning Standup'}, {'id':'2', 'summary':'Lunch'}]
    mock_formatted_output = "Formatted events for tomorrow..."

    # Mock dependencies
    mocker.patch('llm.tools.read_calendar.datetime') # Mock datetime.now used for LLM context
    mock_extract = mocker.patch('llm.tools.read_calendar.llm_service.extract_read_args_llm', return_value=mock_llm_args)
    mock_get_events = mocker.patch('llm.tools.read_calendar.gs.get_calendar_events', return_value=mock_events)
    mock_format = mocker.patch('llm.tools.read_calendar.format_event_list_for_agent', return_value=mock_formatted_output)

    result = await read_tool._arun(time_period=time_period)

    assert result == mock_formatted_output
    mock_extract.assert_called_once() # Check LLM call happened
    mock_get_events.assert_called_once_with(TEST_USER_ID, time_min_iso=mock_llm_args['start_iso'], time_max_iso=mock_llm_args['end_iso'])
    mock_format.assert_called_once_with(mock_events, f"for '{time_period}'", TEST_TIMEZONE_STR, include_ids=False)


# --- Search Tool ---
# Add tests similar to read_tool for SearchCalendarEventsTool, mocking extract_search_args_llm and gs.search_calendar_events

# --- Get Current Time Tool ---
@pytest.fixture
def time_tool():
    return GetCurrentTimeTool(user_id=TEST_USER_ID, user_timezone_str=TEST_TIMEZONE_STR)

async def test_get_current_time_tool_arun(time_tool, mocker):
    # Mock datetime.now to return a fixed time
    fixed_dt = datetime(2024, 8, 19, 11, 30, 15, tzinfo=pytz.timezone(TEST_TIMEZONE_STR))
    mock_dt = MagicMock()
    mock_dt.now.return_value = fixed_dt
    mocker.patch('llm.tools.get_current_time_tool.datetime', mock_dt)

    result = await time_tool._arun()

    assert f"Current date and time is: 2024-08-19 11:30:15 {fixed_dt.tzname()}" in result
    assert f"(ISO: {fixed_dt.isoformat()})" in result
    mock_dt.now.assert_called_once_with(pytz.timezone(TEST_TIMEZONE_STR))