import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from llm.tools.update_calendar import UpdateCalendarEventTool
import config # To access config.pending_updates if needed for assertions

# Sample data for mocking
USER_ID = 123
USER_TIMEZONE_STR = "America/New_York"
NOW_ISO_STR = "2024-01-15T10:00:00-05:00" # Example fixed time for tests

# Mock original event found by search/get_by_id
MOCK_ORIGINAL_EVENT = {
    "id": "event_original_id",
    "summary": "Original Meeting",
    "start": {"dateTime": "2024-01-16T15:00:00-05:00", "timeZone": USER_TIMEZONE_STR}, # 3 PM
    "end": {"dateTime": "2024-01-16T16:00:00-05:00", "timeZone": USER_TIMEZONE_STR},
    "description": "Old description",
    "location": "Old location"
}

MOCK_POTENTIAL_EVENTS_SINGLE = [
    {"id": "event_original_id", "summary": "Original Meeting", "start": {"dateTime": "2024-01-16T15:00:00-05:00"}}
]

MOCK_POTENTIAL_EVENTS_MULTIPLE = [
    {"id": "event_id_1", "summary": "Team Sync", "start": {"dateTime": "2024-01-17T10:00:00-05:00"}},
    {"id": "event_id_2", "summary": "Project Update", "start": {"dateTime": "2024-01-17T14:00:00-05:00"}}
]


@pytest.fixture
def update_tool():
    # Ensure config.pending_updates is clean before each test that uses it
    # Also ensure other pending states are clear to avoid test interference
    if hasattr(config, 'pending_updates'):
        config.pending_updates = {}
    if hasattr(config, 'pending_events'):
        config.pending_events = {}
    if hasattr(config, 'pending_deletions'):
        config.pending_deletions = {}
        
    return UpdateCalendarEventTool(user_id=USER_ID, user_timezone_str=USER_TIMEZONE_STR)

@pytest.mark.asyncio
@patch('llm.tools.update_calendar.datetime') # Mock datetime to control 'now'
@patch('llm.tools.update_calendar.llm_service') # Mock the entire llm_service module used by the tool
@patch('llm.tools.update_calendar.search_calendar_events', new_callable=AsyncMock)
@patch('llm.tools.update_calendar.get_calendar_event_by_id', new_callable=AsyncMock)
async def test_update_event_success_path(
    mock_get_by_id, mock_search, mock_llm, mock_datetime, update_tool
):
    # --- MOCK CONFIGURATION ---
    # Mock datetime.now(tz) to return a specific datetime object whose isoformat() can be controlled
    mock_now_dt_object = MagicMock()
    mock_now_dt_object.isoformat.return_value = NOW_ISO_STR
    mock_datetime.now.return_value = mock_now_dt_object
    
    # Mock for the .replace().isoformat() chain used for default search window
    mock_replaced_dt_object = MagicMock()
    mock_replaced_dt_object.isoformat.return_value = "2024-01-15T00:00:00-05:00" # Start of day
    mock_now_dt_object.replace.return_value = mock_replaced_dt_object


    # 1. Mock LLM: extract_update_search_and_changes
    mock_llm.extract_update_search_and_changes = AsyncMock(return_value={
        "search_query": "Original Meeting tomorrow 3pm",
        "changes_description": "Change summary to 'Updated Meeting' and move to 4pm",
        "search_start_iso": "2024-01-16T00:00:00-05:00",
        "search_end_iso": "2024-01-16T23:59:59-05:00"
    })

    # 2. Mock search_calendar_events
    mock_search.return_value = MOCK_POTENTIAL_EVENTS_SINGLE

    # 3. Mock get_calendar_event_by_id (called after search finds one)
    mock_get_by_id.return_value = MOCK_ORIGINAL_EVENT

    # 4. Mock LLM: extract_calendar_update_details_llm
    mock_llm.extract_calendar_update_details_llm = AsyncMock(return_value={
        "summary": "Updated Meeting",
        "start": {"dateTime": "2024-01-16T16:00:00-05:00", "timeZone": USER_TIMEZONE_STR}, # 4 PM
        "end": {"dateTime": "2024-01-16T17:00:00-05:00", "timeZone": USER_TIMEZONE_STR} # Assumes 1hr duration if not specified
    })

    # --- EXECUTE TOOL ---
    user_request = "Reschedule my Original Meeting tomorrow 3pm to 4pm and call it 'Updated Meeting'"
    result = await update_tool._arun(user_request)

    # --- ASSERTIONS ---
    mock_llm.extract_update_search_and_changes.assert_called_once_with(user_request, NOW_ISO_STR)
    mock_search.assert_called_once_with(
        USER_ID,
        query="Original Meeting tomorrow 3pm",
        time_min_iso="2024-01-16T00:00:00-05:00",
        time_max_iso="2024-01-16T23:59:59-05:00",
        max_results=10
    )
    mock_get_by_id.assert_called_once_with(USER_ID, MOCK_ORIGINAL_EVENT["id"])
    mock_llm.extract_calendar_update_details_llm.assert_called_once_with(
        natural_language_changes="Change summary to 'Updated Meeting' and move to 4pm",
        original_event_details=MOCK_ORIGINAL_EVENT,
        current_time_iso=NOW_ISO_STR,
        user_timezone_str=USER_TIMEZONE_STR
    )

    assert "Okay, I can update this event:" in result
    assert "<b>Original Event:</b> Original Meeting" in result # Check original summary
    assert "Starts: Tue, Jan 16, 2024 at 03:00 PM EST" in result # Check original start time
    assert "<b>Proposed Changes:</b>" in result
    assert "  - Summary: Updated Meeting" in result # Note: Added leading spaces for list format
    assert "  - Start: Tue, Jan 16, 2024 at 04:00 PM EST" in result # Check new start time, added leading spaces

    assert USER_ID in config.pending_updates
    pending_data = config.pending_updates[USER_ID]
    assert pending_data["event_id"] == MOCK_ORIGINAL_EVENT["id"]
    assert pending_data["update_data"]["summary"] == "Updated Meeting"
    assert pending_data["update_data"]["start"]["dateTime"] == "2024-01-16T16:00:00-05:00"


@pytest.mark.asyncio
@patch('llm.tools.update_calendar.datetime')
@patch('llm.tools.update_calendar.llm_service')
@patch('llm.tools.update_calendar.search_calendar_events', new_callable=AsyncMock)
async def test_update_event_no_event_found(
    mock_search, mock_llm, mock_datetime, update_tool
):
    mock_now_dt_object = MagicMock()
    mock_now_dt_object.isoformat.return_value = NOW_ISO_STR
    mock_datetime.now.return_value = mock_now_dt_object
    mock_llm.extract_update_search_and_changes = AsyncMock(return_value={
        "search_query": "NonExistent Meeting",
        "changes_description": "Change summary",
        "search_start_iso": NOW_ISO_STR, "search_end_iso": NOW_ISO_STR # Dummy values
    })
    mock_search.return_value = [] # No events found

    result = await update_tool._arun("Update NonExistent Meeting")

    assert "Error: No events found matching your description 'NonExistent Meeting'" in result
    assert USER_ID not in config.pending_updates


@pytest.mark.asyncio
@patch('llm.tools.update_calendar.datetime')
@patch('llm.tools.update_calendar.llm_service')
@patch('llm.tools.update_calendar.search_calendar_events', new_callable=AsyncMock)
@patch('llm.tools.update_calendar.get_calendar_event_by_id', new_callable=AsyncMock)
async def test_update_event_llm_fails_to_extract_changes(
    mock_get_by_id, mock_search, mock_llm, mock_datetime, update_tool
):
    mock_now_dt_object = MagicMock()
    mock_now_dt_object.isoformat.return_value = NOW_ISO_STR
    mock_datetime.now.return_value = mock_now_dt_object
    
    mock_llm.extract_update_search_and_changes = AsyncMock(return_value={
        "search_query": "Original Meeting",
        "changes_description": "gibberish changes",
        "search_start_iso": NOW_ISO_STR, "search_end_iso": NOW_ISO_STR
    })
    mock_search.return_value = MOCK_POTENTIAL_EVENTS_SINGLE
    mock_get_by_id.return_value = MOCK_ORIGINAL_EVENT
    mock_llm.extract_calendar_update_details_llm = AsyncMock(return_value=None) # LLM fails here

    result = await update_tool._arun("Update Original Meeting with gibberish changes")

    assert "Error: Could not understand the specific changes you want to make ('gibberish changes')" in result
    assert USER_ID not in config.pending_updates

# Add more tests:
# - User provides no user_request
# - User context (user_id) missing
# - search_calendar_events returns None (API error)
# - get_calendar_event_by_id returns None after search found an ID
# - LLM fails to extract initial search_query/changes_description
# - Multiple events found and LLM disambiguation is needed (if that path is fleshed out in the tool)
# - Update data extracted by LLM is empty or invalid
# - Different timezones handling (if possible to mock easily)
# - Test for when pytz.timezone(self.user_timezone_str) raises UnknownTimeZoneError
# - Test for when original_event_details_for_confirm is None after get_calendar_event_by_id
# - Test for when update_data_dict is empty after llm_service.extract_calendar_update_details_llm
# - Test for when formatting confirmation string fails (e.g. bad date format in update_data_dict)
# - Test for multiple events found and user needs to be more specific
# - Test for when search_start_iso or search_end_iso are not provided by LLM and default window is used
# - Test for when the tool clears other pending actions (e.g. pending_events, pending_deletions)
