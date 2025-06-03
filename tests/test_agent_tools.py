# tests/test_agent_tools.py
from datetime import datetime, timedelta # Added timedelta
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
import pytz

import config  # To check pending state changes
# Import tools AFTER fixtures might patch dependencies
from llm.tools.create_calendar import CreateCalendarEventTool
from llm.tools.delete_calendar import DeleteCalendarEventTool
from llm.tools.get_current_time_tool import GetCurrentTimeTool
from llm.tools.read_calendar import ReadCalendarEventsTool
from llm.tools.search_calendar import SearchCalendarEventsTool # Added
from .conftest import TEST_USER_ID, TEST_TIMEZONE_STR, TEST_EVENT_ID, TEST_TIMEZONE

pytestmark = pytest.mark.asyncio

# --- Dynamic Date/Time Setup ---
# Use a fixed "now" for predictable test results across runs
BASE_TEST_NOW_UTC = datetime(2024, 8, 19, 17, 0, 0, tzinfo=pytz.utc) # Example: 10 AM in TEST_TIMEZONE (PDT is UTC-7)
BASE_TEST_NOW_USER_TZ = BASE_TEST_NOW_UTC.astimezone(TEST_TIMEZONE)

# --- Create Tool ---
@pytest.fixture
def create_tool():
    return CreateCalendarEventTool(user_id=TEST_USER_ID, user_timezone_str=TEST_TIMEZONE_STR)

async def test_create_tool_arun_success(create_tool, mock_llm_service, mocker):
    event_description = "Meeting with Bob tomorrow 3pm about project X"

    # Dynamic dates based on BASE_TEST_NOW_USER_TZ
    mock_current_time_iso = BASE_TEST_NOW_USER_TZ.isoformat()

    event_start_dt = BASE_TEST_NOW_USER_TZ.replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=1)
    event_end_dt = event_start_dt + timedelta(hours=1)

    extracted_event_data = {
        "summary": "Meeting with Bob",
        "start": {"dateTime": event_start_dt.isoformat(), "timeZone": TEST_TIMEZONE_STR},
        "end": {"dateTime": event_end_dt.isoformat(), "timeZone": TEST_TIMEZONE_STR},
        "description": "project X discussion",
        "location": None
    }
    # Mock the specific LLM function called by the tool
    mock_extract = mocker.patch('llm.tools.create_calendar.llm_service.extract_create_args_llm',
                                return_value=extracted_event_data)

    # Patch datetime.now used within the tool to return our fixed "now"
    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.create_calendar.datetime', now=mock_datetime_now_fixed)
    
    # Mock gs.add_pending_event as it's now async and called by the tool
    mock_add_pending = mocker.patch('llm.tools.create_calendar.gs.add_pending_event', new_callable=AsyncMock, return_value=True)

    result_string = await create_tool._arun(event_description=event_description)

    # Assert LLM extraction was called correctly
    mock_extract.assert_called_once_with(event_description, mock_current_time_iso, TEST_TIMEZONE_STR)
    
    # Assert gs.add_pending_event was called
    mock_add_pending.assert_awaited_once_with(TEST_USER_ID, extracted_event_data)

    # Assert the result is the confirmation string
    # Expected formatted start time: e.g., "Tue, Aug 20, 2024 at 03:00 PM PDT"
    # This needs to be dynamically generated based on event_start_dt
    expected_start_formatted = event_start_dt.strftime("%a, %b %d, %Y at %I:%M %p %Z")


    assert "Should I add this to your calendar?" in result_string
    assert "Summary: Meeting with Bob" in result_string
    assert f"Start: {expected_start_formatted}" in result_string


async def test_create_tool_arun_llm_fail(create_tool, mock_llm_service, mocker):
    event_description = "invalid stuff"
    # Mock the LLM function to return None (failure)
    mock_extract = mocker.patch('llm.tools.create_calendar.llm_service.extract_create_args_llm', return_value=None)
    mocker.patch('llm.tools.create_calendar.datetime') # Mock datetime just in case
    mock_add_pending = mocker.patch('llm.tools.create_calendar.gs.add_pending_event', new_callable=AsyncMock)


    result_string = await create_tool._arun(event_description=event_description)

    assert "Error: Could not extract valid event details" in result_string
    mock_add_pending.assert_not_awaited() # No pending event should be stored

async def test_create_tool_arun_add_pending_event_fails(create_tool, mock_llm_service, mocker):
    event_description = "Meeting with Bob tomorrow 3pm about project X"

    event_start_dt = BASE_TEST_NOW_USER_TZ.replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=1)
    event_end_dt = event_start_dt + timedelta(hours=1)
    extracted_event_data = { # Assume LLM extraction is successful
        "summary": "Meeting with Bob",
        "start": {"dateTime": event_start_dt.isoformat(), "timeZone": TEST_TIMEZONE_STR},
        "end": {"dateTime": event_end_dt.isoformat(), "timeZone": TEST_TIMEZONE_STR},
    }
    mocker.patch('llm.tools.create_calendar.llm_service.extract_create_args_llm', return_value=extracted_event_data)

    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.create_calendar.datetime', now=mock_datetime_now_fixed)
    # Mock gs.add_pending_event to return False
    mocker.patch('llm.tools.create_calendar.gs.add_pending_event', new_callable=AsyncMock, return_value=False)

    result_string = await create_tool._arun(event_description=event_description)

    assert "Error: Failed to store pending event details. Please try again." in result_string

async def test_create_tool_arun_missing_summary_from_llm(create_tool, mock_llm_service, mocker):
    event_description = "A meeting tomorrow 2pm"

    event_start_dt = BASE_TEST_NOW_USER_TZ.replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=1)
    event_end_dt = event_start_dt + timedelta(hours=1)
    # LLM returns data but essential 'summary' is missing
    extracted_event_data = {
        "start": {"dateTime": event_start_dt.isoformat(), "timeZone": TEST_TIMEZONE_STR},
        "end": {"dateTime": event_end_dt.isoformat(), "timeZone": TEST_TIMEZONE_STR},
    }
    mocker.patch('llm.tools.create_calendar.llm_service.extract_create_args_llm', return_value=extracted_event_data)

    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.create_calendar.datetime', now=mock_datetime_now_fixed)
    mock_add_pending = mocker.patch('llm.tools.create_calendar.gs.add_pending_event', new_callable=AsyncMock)

    result_string = await create_tool._arun(event_description=event_description)

    assert "Error: Missing essential event details (summary or start time) from LLM." in result_string
    mock_add_pending.assert_not_awaited()

async def test_create_tool_arun_empty_event_description(create_tool, mock_llm_service, mocker):
    event_description = "" # Empty input
    mock_extract = mocker.patch('llm.tools.create_calendar.llm_service.extract_create_args_llm')

    result_string = await create_tool._arun(event_description=event_description)

    assert "Error: Event description cannot be empty." in result_string
    mock_extract.assert_not_called()

# --- Delete Tool ---
@pytest.fixture
def delete_tool():
    return DeleteCalendarEventTool(user_id=TEST_USER_ID, user_timezone_str=TEST_TIMEZONE_STR)

async def test_delete_tool_arun_success(delete_tool, mocker):
    event_id_to_delete = TEST_EVENT_ID

    event_start_dt = BASE_TEST_NOW_USER_TZ.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=2) # e.g., Aug 21st if base is Aug 19th
    event_end_dt = event_start_dt + timedelta(hours=1)

    mock_event_details = {
        'id': event_id_to_delete,
        'summary': 'Event To Delete',
        'start': {'dateTime': event_start_dt.isoformat(), 'timeZone': TEST_TIMEZONE_STR},
        'end': {'dateTime': event_end_dt.isoformat(), 'timeZone': TEST_TIMEZONE_STR}
    }
    mock_get_event = mocker.patch('llm.tools.delete_calendar.gs.get_calendar_event_by_id', new_callable=AsyncMock, return_value=mock_event_details)
    mock_add_pending_deletion = mocker.patch('llm.tools.delete_calendar.gs.add_pending_deletion', new_callable=AsyncMock, return_value=True)

    expected_formatted_time = event_start_dt.strftime("%a, %b %d, %I:%M %p %Z") # Format for assertion
    mocker.patch('llm.tools.delete_calendar._format_event_time', return_value=expected_formatted_time)

    result_string = await delete_tool._arun(event_id=event_id_to_delete)

    mock_get_event.assert_awaited_once_with(TEST_USER_ID, event_id_to_delete)
    mock_add_pending_deletion.assert_awaited_once_with(TEST_USER_ID, {'event_id': event_id_to_delete, 'summary': 'Event To Delete'})

    assert "Should I delete this event?" in result_string
    assert "Found event: 'Event To Delete'" in result_string
    assert f"({expected_formatted_time})" in result_string


async def test_delete_tool_arun_invalid_id(delete_tool, mocker):
    mock_add_pending_deletion = mocker.patch('llm.tools.delete_calendar.gs.add_pending_deletion', new_callable=AsyncMock)
    result_string = await delete_tool._arun(event_id="") # Empty ID
    assert "Error: A valid event ID is required" in result_string
    mock_add_pending_deletion.assert_not_awaited()

async def test_delete_tool_arun_event_not_found(delete_tool, mocker):
    event_id_not_found = "bad_id"
    mock_get_event = mocker.patch('llm.tools.delete_calendar.gs.get_calendar_event_by_id', new_callable=AsyncMock, return_value=None)
    mock_add_pending_deletion = mocker.patch('llm.tools.delete_calendar.gs.add_pending_deletion', new_callable=AsyncMock)

    result_string = await delete_tool._arun(event_id=event_id_not_found)

    assert f"Error: Could not find event with ID '{event_id_not_found}'" in result_string
    mock_add_pending_deletion.assert_not_awaited()

async def test_delete_tool_arun_get_event_exception(delete_tool, mocker):
    event_id_to_delete = TEST_EVENT_ID
    # Mock gs.get_calendar_event_by_id to raise an exception
    mocker.patch('llm.tools.delete_calendar.gs.get_calendar_event_by_id', new_callable=AsyncMock, side_effect=Exception("API Error"))
    mock_add_pending_deletion = mocker.patch('llm.tools.delete_calendar.gs.add_pending_deletion', new_callable=AsyncMock)

    result_string = await delete_tool._arun(event_id=event_id_to_delete)

    assert f"Error retrieving event details for ID '{event_id_to_delete}'." in result_string
    mock_add_pending_deletion.assert_not_awaited()

async def test_delete_tool_arun_add_pending_deletion_fails(delete_tool, mocker):
    event_id_to_delete = TEST_EVENT_ID

    event_start_dt = BASE_TEST_NOW_USER_TZ.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=2)
    mock_event_details = { # Assume gs.get_calendar_event_by_id is successful
        'id': event_id_to_delete,
        'summary': 'Event To Delete',
        'start': {'dateTime': event_start_dt.isoformat(), 'timeZone': TEST_TIMEZONE_STR},
    }
    mocker.patch('llm.tools.delete_calendar.gs.get_calendar_event_by_id', new_callable=AsyncMock, return_value=mock_event_details)

    expected_formatted_time = event_start_dt.strftime("%a, %b %d, %I:%M %p %Z")
    mocker.patch('llm.tools.delete_calendar._format_event_time', return_value=expected_formatted_time)
    # Mock gs.add_pending_deletion to return False
    mocker.patch('llm.tools.delete_calendar.gs.add_pending_deletion', new_callable=AsyncMock, return_value=False)

    result_string = await delete_tool._arun(event_id=event_id_to_delete)

    assert "Error: Failed to store pending event deletion. Please try again." in result_string

# --- Read Tool ---
@pytest.fixture
def read_tool():
    return ReadCalendarEventsTool(user_id=TEST_USER_ID, user_timezone_str=TEST_TIMEZONE_STR)

async def test_read_tool_arun_success(read_tool, mocker):
    time_period_description = "tomorrow"

    # Dynamic dates for mock_llm_args
    start_of_tomorrow = (BASE_TEST_NOW_USER_TZ + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_tomorrow = (BASE_TEST_NOW_USER_TZ + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
    mock_llm_args = {'start_iso': start_of_tomorrow.isoformat(), 'end_iso': end_of_tomorrow.isoformat()}

    mock_events = [{'id':'event_id_1', 'summary':'Morning Standup'}, {'id':'event_id_2', 'summary':'Lunch'}]
    mock_formatted_output = f"Formatted events for {time_period_description}..."

    # Mock dependencies
    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.read_calendar.datetime', now=mock_datetime_now_fixed)
    mock_extract = mocker.patch('llm.tools.read_calendar.llm_service.extract_read_args_llm', return_value=mock_llm_args)
    mock_get_events = mocker.patch('llm.tools.read_calendar.gs.get_calendar_events', new_callable=AsyncMock, return_value=mock_events)
    mock_format = mocker.patch('llm.tools.read_calendar.format_event_list_for_agent', return_value=mock_formatted_output)

    result = await read_tool._arun(time_period=time_period_description)

    assert result == mock_formatted_output
    mock_extract.assert_called_once()
    assert mock_extract.call_args[0][0] == time_period_description # Check correct time_period_description passed
    assert mock_extract.call_args[0][1] == BASE_TEST_NOW_USER_TZ.isoformat() # Check correct now_iso passed

    mock_get_events.assert_awaited_once_with(TEST_USER_ID, time_min_iso=mock_llm_args['start_iso'], time_max_iso=mock_llm_args['end_iso'])
    mock_format.assert_called_once_with(mock_events, f"for '{time_period_description}'", TEST_TIMEZONE_STR, include_ids=False)

async def test_read_tool_arun_llm_fail(read_tool, mocker):
    time_period_description = "invalid period"
    # Mock the LLM function to return None (failure)
    mocker.patch('llm.tools.read_calendar.llm_service.extract_read_args_llm', return_value=None)
    mock_gs_get_events = mocker.patch('llm.tools.read_calendar.gs.get_calendar_events', new_callable=AsyncMock)

    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.read_calendar.datetime', now=mock_datetime_now_fixed)


    result_string = await read_tool._arun(time_period=time_period_description)

    assert "Error: Could not understand the time period you specified" in result_string
    mock_gs_get_events.assert_not_awaited()

async def test_read_tool_arun_no_events_found(read_tool, mocker):
    time_period_description = "next monday"

    start_of_next_monday = (BASE_TEST_NOW_USER_TZ + timedelta(days=(7 - BASE_TEST_NOW_USER_TZ.weekday() + 0))).replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_next_monday = start_of_next_monday.replace(hour=23, minute=59, second=59, microsecond=999999)
    mock_llm_args = {'start_iso': start_of_next_monday.isoformat(), 'end_iso': end_of_next_monday.isoformat()}

    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.read_calendar.datetime', now=mock_datetime_now_fixed)
    mocker.patch('llm.tools.read_calendar.llm_service.extract_read_args_llm', return_value=mock_llm_args)
    mock_gs_get_events = mocker.patch('llm.tools.read_calendar.gs.get_calendar_events', new_callable=AsyncMock, return_value=[]) # No events
    mock_format = mocker.patch('llm.tools.read_calendar.format_event_list_for_agent')

    result = await read_tool._arun(time_period=time_period_description)

    assert result == f"No events found for '{time_period_description}'."
    mock_gs_get_events.assert_awaited_once()
    mock_format.assert_not_called()

async def test_read_tool_arun_gs_get_events_error(read_tool, mocker):
    time_period_description = "this week"

    start_of_week = (BASE_TEST_NOW_USER_TZ - timedelta(days=BASE_TEST_NOW_USER_TZ.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_week = (start_of_week + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
    mock_llm_args = {'start_iso': start_of_week.isoformat(), 'end_iso': end_of_week.isoformat()}

    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.read_calendar.datetime', now=mock_datetime_now_fixed)
    mocker.patch('llm.tools.read_calendar.llm_service.extract_read_args_llm', return_value=mock_llm_args)
    # gs.get_calendar_events returns None on error
    mock_gs_get_events = mocker.patch('llm.tools.read_calendar.gs.get_calendar_events', new_callable=AsyncMock, return_value=None)
    mock_format = mocker.patch('llm.tools.read_calendar.format_event_list_for_agent')

    result = await read_tool._arun(time_period=time_period_description)

    assert result == "Error: Failed to retrieve calendar events due to a service error."
    mock_gs_get_events.assert_awaited_once()
    mock_format.assert_not_called()

# --- Search Tool ---
@pytest.fixture
def search_tool():
    return SearchCalendarEventsTool(user_id=TEST_USER_ID, user_timezone_str=TEST_TIMEZONE_STR)

async def test_search_tool_arun_success(search_tool, mocker):
    search_query = "team meeting next week"
    extracted_args = {
        "query": "team meeting", # Assume LLM extracts a cleaner query
        "time_period_description": "next week"
    }

    # Dynamic dates for llm_extracted_time_args
    # Assuming "next week" starts from the Monday after BASE_TEST_NOW_USER_TZ and ends on the following Sunday.
    monday_after_base = BASE_TEST_NOW_USER_TZ + timedelta(days=(7 - BASE_TEST_NOW_USER_TZ.weekday()))
    start_of_next_week = monday_after_base.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_next_week = (start_of_next_week + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)

    llm_extracted_time_args = {
        "start_iso": start_of_next_week.isoformat(),
        "end_iso": end_of_next_week.isoformat()
    }
    mock_events = [{'id':'event_id_3', 'summary':'Team Sync'}, {'id':'event_id_4', 'summary':'Project Team Meeting'}]
    mock_formatted_output = f"Formatted search results for '{extracted_args['query']}' {extracted_args['time_period_description']}..."

    # Mock dependencies
    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.search_calendar.datetime', now=mock_datetime_now_fixed)
    mock_extract_search_args = mocker.patch('llm.tools.search_calendar.llm_service.extract_search_args_llm', return_value=extracted_args)
    mock_extract_read_args = mocker.patch('llm.tools.search_calendar.llm_service.extract_read_args_llm', return_value=llm_extracted_time_args)
    mock_gs_search = mocker.patch('llm.tools.search_calendar.gs.search_calendar_events', new_callable=AsyncMock, return_value=mock_events)
    mock_format = mocker.patch('llm.tools.search_calendar.format_event_list_for_agent', return_value=mock_formatted_output)

    result = await search_tool._arun(search_query=search_query)

    assert result == mock_formatted_output
    mock_extract_search_args.assert_called_once_with(search_query, TEST_TIMEZONE_STR)
    mock_extract_read_args.assert_called_once()
    assert mock_extract_read_args.call_args[0][0] == extracted_args["time_period_description"]
    assert mock_extract_read_args.call_args[0][1] == BASE_TEST_NOW_USER_TZ.isoformat() # Check now_iso

    mock_gs_search.assert_awaited_once_with(
        TEST_USER_ID,
        query=extracted_args["query"],
        time_min_iso=llm_extracted_time_args["start_iso"],
        time_max_iso=llm_extracted_time_args["end_iso"]
    )
    mock_format.assert_called_once_with(mock_events, f"matching '{extracted_args['query']}' during '{extracted_args['time_period_description']}'", TEST_TIMEZONE_STR, include_ids=True)


async def test_search_tool_arun_llm_search_args_fail(search_tool, mocker):
    search_query = "some gibberish"
    mocker.patch('llm.tools.search_calendar.llm_service.extract_search_args_llm', return_value=None)
    mock_gs_search = mocker.patch('llm.tools.search_calendar.gs.search_calendar_events', new_callable=AsyncMock)

    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.search_calendar.datetime', now=mock_datetime_now_fixed)


    result = await search_tool._arun(search_query=search_query)

    assert "Error: Could not extract search parameters" in result
    assert "Try rephrasing your request" in result
    mock_gs_search.assert_not_awaited()


async def test_search_tool_arun_llm_time_args_fail(search_tool, mocker):
    search_query = "find meetings about project X sometime soon"
    extracted_search_args = {"query": "project X", "time_period_description": "sometime soon"}
    mocker.patch('llm.tools.search_calendar.llm_service.extract_search_args_llm', return_value=extracted_search_args)
    mocker.patch('llm.tools.search_calendar.llm_service.extract_read_args_llm', return_value=None) # Time parsing fails
    mock_gs_search = mocker.patch('llm.tools.search_calendar.gs.search_calendar_events', new_callable=AsyncMock)

    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.search_calendar.datetime', now=mock_datetime_now_fixed)


    result = await search_tool._arun(search_query=search_query)

    assert "Error: Could not understand the time period" in result
    assert extracted_search_args["time_period_description"] in result
    mock_gs_search.assert_not_awaited()

async def test_search_tool_arun_no_events_found(search_tool, mocker):
    search_query = "nonexistent event next Friday"
    extracted_args = {"query": "nonexistent event", "time_period_description": "next Friday"}

    # Dynamic dates for llm_extracted_time_args
    next_friday = BASE_TEST_NOW_USER_TZ + timedelta(days=( (4 - BASE_TEST_NOW_USER_TZ.weekday() + 7) % 7 ) )
    start_of_next_friday = next_friday.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_next_friday = next_friday.replace(hour=23, minute=59, second=59, microsecond=999999)
    llm_extracted_time_args = {"start_iso": start_of_next_friday.isoformat(), "end_iso": end_of_next_friday.isoformat()}

    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.search_calendar.datetime', now=mock_datetime_now_fixed)
    mocker.patch('llm.tools.search_calendar.llm_service.extract_search_args_llm', return_value=extracted_args)
    mocker.patch('llm.tools.search_calendar.llm_service.extract_read_args_llm', return_value=llm_extracted_time_args)
    mock_gs_search = mocker.patch('llm.tools.search_calendar.gs.search_calendar_events', new_callable=AsyncMock, return_value=[]) # No events
    mock_format = mocker.patch('llm.tools.search_calendar.format_event_list_for_agent')

    result = await search_tool._arun(search_query=search_query)

    assert result == f"No events found matching '{extracted_args['query']}' during '{extracted_args['time_period_description']}'."
    mock_gs_search.assert_awaited_once()
    mock_format.assert_not_called()

async def test_search_tool_arun_gs_search_error(search_tool, mocker):
    search_query = "any event next month"
    extracted_args = {"query": "any event", "time_period_description": "next month"}

    # Dynamic dates for llm_extracted_time_args
    first_day_of_current_month = BASE_TEST_NOW_USER_TZ.replace(day=1)
    first_day_next_month = (first_day_of_current_month + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day_next_month = (first_day_next_month + timedelta(days=32)).replace(day=1, microsecond=0) - timedelta(microseconds=1)
    llm_extracted_time_args = {"start_iso": first_day_next_month.isoformat(), "end_iso": last_day_next_month.isoformat()}

    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.search_calendar.datetime', now=mock_datetime_now_fixed)
    mocker.patch('llm.tools.search_calendar.llm_service.extract_search_args_llm', return_value=extracted_args)
    mocker.patch('llm.tools.search_calendar.llm_service.extract_read_args_llm', return_value=llm_extracted_time_args)
    mock_gs_search = mocker.patch('llm.tools.search_calendar.gs.search_calendar_events', new_callable=AsyncMock, return_value=None) # Error from gs
    mock_format = mocker.patch('llm.tools.search_calendar.format_event_list_for_agent')

    result = await search_tool._arun(search_query=search_query)

    assert result == "Error: Failed to search for calendar events due to a service error."
    mock_gs_search.assert_awaited_once()
    mock_format.assert_not_called()

async def test_search_tool_arun_empty_query_after_llm(search_tool, mocker):
    search_query = "search for stuff"
    extracted_args = {"query": "", "time_period_description": "today"} # Empty query from LLM

    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    mocker.patch('llm.tools.search_calendar.datetime', now=mock_datetime_now_fixed)
    mocker.patch('llm.tools.search_calendar.llm_service.extract_search_args_llm', return_value=extracted_args)
    mock_extract_read_args = mocker.patch('llm.tools.search_calendar.llm_service.extract_read_args_llm')
    mock_gs_search = mocker.patch('llm.tools.search_calendar.gs.search_calendar_events', new_callable=AsyncMock)

    result = await search_tool._arun(search_query=search_query)

    assert result == "Error: A non-empty search query is required. Please specify what you want to search for."
    mock_extract_read_args.assert_not_called()
    mock_gs_search.assert_not_awaited()

# --- Get Current Time Tool ---
@pytest.fixture
def time_tool():
    return GetCurrentTimeTool(user_id=TEST_USER_ID, user_timezone_str=TEST_TIMEZONE_STR)

async def test_get_current_time_tool_arun(time_tool, mocker):
    # Use BASE_TEST_NOW_USER_TZ as the fixed time for this test
    mock_datetime_now_fixed = MagicMock(return_value=BASE_TEST_NOW_USER_TZ)
    # Patch datetime.now within the tool's module
    mocker.patch('llm.tools.get_current_time_tool.datetime', now=mock_datetime_now_fixed)

    result = await time_tool._arun()

    expected_time_str = BASE_TEST_NOW_USER_TZ.strftime("%Y-%m-%d %H:%M:%S %Z")
    # For the "PDT" or similar part, strftime %Z can be tricky.
    # Using tzname() from the datetime object is more reliable.
    expected_tz_name = BASE_TEST_NOW_USER_TZ.tzname()
    expected_full_str = BASE_TEST_NOW_USER_TZ.strftime(f"%Y-%m-%d %H:%M:%S {expected_tz_name}")


    assert f"Current date and time is: {expected_full_str}" in result
    assert f"(ISO: {BASE_TEST_NOW_USER_TZ.isoformat()})" in result
    mock_datetime_now_fixed.assert_called_once_with(TEST_TIMEZONE) # TEST_TIMEZONE is the pytz object

async def test_get_current_time_tool_arun_invalid_timezone(mocker):
    invalid_tz_str = "Invalid/Timezone"
    # Create tool instance directly for this specific non-fixture case
    time_tool_invalid_tz = GetCurrentTimeTool(user_id=TEST_USER_ID, user_timezone_str=invalid_tz_str)

    # pytz.timezone will be called with invalid_tz_str and raise UnknownTimeZoneError
    # No need to mock datetime.now for this test as it should fail before that.

    result = await time_tool_invalid_tz._arun()

    assert f"Error: The timezone '{invalid_tz_str}' is invalid." in result
    assert "Please set a valid IANA timezone using /set_timezone." in result