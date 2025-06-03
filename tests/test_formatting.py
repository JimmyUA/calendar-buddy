import html

import pytest
import pytz
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock # For mocking event_data if needed in complex scenarios

# Adjust the import path based on your project structure
# Assuming formatting.py is in your_project_root/llm/tools/formatting.py
from llm.tools.formatting import parse_and_format_event_time, format_event_list_for_agent

# --- Constants for Tests ---
USER_TZ_STR_AMS = "Europe/Amsterdam" # CEST/CET
USER_TZ_AMS = pytz.timezone(USER_TZ_STR_AMS)

USER_TZ_STR_LA = "America/Los_Angeles" # PDT/PST
USER_TZ_LA = pytz.timezone(USER_TZ_STR_LA)
USER_TZ_UTC = pytz.utc

# Base datetime for dynamic test data generation (e.g., a specific Monday)
# Let's choose a Monday for easier weekday calculations.
# Example: 2024-08-19 is a Monday.
BASE_TEST_DATE = datetime(2024, 8, 19, tzinfo=USER_TZ_UTC)

# === Tests for parse_and_format_event_time ===

def _create_event_data(start_iso=None, end_iso=None, start_date_str=None, end_date_str=None, summary="Test Event"):
    event = {"summary": summary}
    if start_date_str:
        event["start"] = {"date": start_date_str}
    elif start_iso:
        event["start"] = {"dateTime": start_iso}

    if end_date_str:
        event["end"] = {"date": end_date_str}
    elif end_iso:
        event["end"] = {"dateTime": end_iso}
    return event

# Test cases for parse_and_format_event_time
# Each tuple: (event_data_params_tuple, user_tz, expected_time_str, expected_duration_str, expected_is_all_day)
# event_data_params_tuple: (start_datetime_obj, end_datetime_obj, is_all_day_event) OR (start_date_obj, end_date_obj, is_all_day_event)
parse_format_test_cases = [
    # 1. Timed Event - Same Day
    (
        (BASE_TEST_DATE.replace(hour=9, minute=0, second=0).astimezone(USER_TZ_AMS),
         BASE_TEST_DATE.replace(hour=17, minute=0, second=0).astimezone(USER_TZ_AMS),
         False), # start_dt, end_dt, is_all_day
        USER_TZ_AMS, "09:00 AM - 05:00 PM CEST", "(8h)", False
    ),
    # 2. Timed Event - Spanning Days
    (
        (BASE_TEST_DATE.replace(hour=22, minute=0, second=0).astimezone(USER_TZ_AMS), # Mon 10 PM
         (BASE_TEST_DATE + timedelta(days=1)).replace(hour=2, minute=0, second=0).astimezone(USER_TZ_AMS), # Tue 2 AM
         False),
        USER_TZ_AMS, f"{BASE_TEST_DATE.astimezone(USER_TZ_AMS).strftime('%a, %b %d, %I:%M %p %Z')} - {(BASE_TEST_DATE + timedelta(days=1)).astimezone(USER_TZ_AMS).strftime('%a, %b %d, %I:%M %p %Z')}", "(4h)", False
    ),
    # 3. All-Day Event - Single Day (e.g., July 4th, if BASE_TEST_DATE was July 1st, this would be July 4th)
    (
        ((BASE_TEST_DATE + timedelta(days=3)).date(), # A specific date object
         (BASE_TEST_DATE + timedelta(days=4)).date(), # End date for Google Calendar (exclusive)
         True),
        USER_TZ_LA, f"{(BASE_TEST_DATE + timedelta(days=3)).astimezone(USER_TZ_LA).strftime('%A, %d %B %Y')} (All Day)", "", True
    ),
    # 4. All-Day Event - Multi-Day (e.g., Dec 24-26, if base was Dec 1)
    (
        ((BASE_TEST_DATE.replace(month=12, day=24)).date(),
         (BASE_TEST_DATE.replace(month=12, day=27)).date(),
         True),
        USER_TZ_AMS,
        f"{(BASE_TEST_DATE.replace(month=12, day=24)).astimezone(USER_TZ_AMS).strftime('%A, %d %B %Y')} - {(BASE_TEST_DATE.replace(month=12, day=26)).astimezone(USER_TZ_AMS).strftime('%A, %d %B %Y')} (All Day)",
        "", True
    ),
    # 5. Timed Event - Short Duration (minutes)
    (
        (BASE_TEST_DATE.replace(hour=10, minute=15, second=0).astimezone(USER_TZ_AMS),
         BASE_TEST_DATE.replace(hour=10, minute=45, second=0).astimezone(USER_TZ_AMS),
         False),
        USER_TZ_AMS, "10:15 AM - 10:45 AM CEST", "(30min)", False
    ),
    # 6. Timed Event - Crossing into next year
    (
        (datetime(2024, 12, 30, 10, 0, 0, tzinfo=USER_TZ_AMS), # Explicitly create for clarity
         datetime(2025, 1, 2, 12, 0, 0, tzinfo=USER_TZ_AMS),
         False),
        USER_TZ_AMS, "Mon, Dec 30, 10:00 AM CET - Thu, Jan 02, 12:00 PM CET", "(3d, 2h)", False # CET for Dec, CEST for Jan if applicable
    ),
    # 7. Timed Event - Zero duration
    (
        (BASE_TEST_DATE.replace(hour=14, minute=0, second=0).astimezone(USER_TZ_AMS),
         BASE_TEST_DATE.replace(hour=14, minute=0, second=0).astimezone(USER_TZ_AMS),
         False),
        USER_TZ_AMS, "02:00 PM - 02:00 PM CEST", "", False
    ),
    # 8. Event crossing different timezones in ISO string (PDT to Amsterdam display)
    (
        (datetime(2024, 8, 15, 10, 0, 0, tzinfo=USER_TZ_LA), # 10 AM PDT
         datetime(2024, 8, 15, 13, 0, 0, tzinfo=USER_TZ_LA), # 1 PM PDT
         False),
        USER_TZ_AMS, "07:00 PM - 10:00 PM CEST", "(3h)", False # User in AMS, event is PDT
    ),
]

@pytest.mark.parametrize(
    "event_params, user_tz, expected_time_str, expected_duration_str, expected_is_all_day",
    parse_format_test_cases
)
def test_parse_and_format_event_time(event_params, user_tz, expected_time_str, expected_duration_str, expected_is_all_day):
    start_obj, end_obj, is_all_day_event = event_params

    if is_all_day_event:
        event_data = _create_event_data(start_date_str=start_obj.isoformat(), end_date_str=end_obj.isoformat())
    else:
        event_data = _create_event_data(start_iso=start_obj.isoformat(), end_iso=end_obj.isoformat())

    result = parse_and_format_event_time(event_data, user_tz)
    assert result is not None

    # Adjust expected time string for CEST/CET based on actual date for cases 1,2,5,7,8
    # This is tricky because %Z is not always reliable across systems for pytz.
    # A better way is to use tzname() if possible or hardcode the expected one for specific dates.
    # For simplicity, I'll assume the current expected strings are okay if the date falls into DST for CEST.
    # The _format_event_time in utils.py uses %Z, which is what we test here.
    # Case 6 (CET/CEST transition) is also sensitive.

    # For case 2, dynamically construct expected string:
    if event_params == parse_format_test_cases[1][0]: # Timed event spanning days
         start_dt_local = start_obj.astimezone(user_tz)
         end_dt_local = end_obj.astimezone(user_tz)
         expected_time_str = f"{start_dt_local.strftime('%a, %b %d, %I:%M %p %Z')} - {end_dt_local.strftime('%a, %b %d, %I:%M %p %Z')}"

    # For case 6, need to be careful with CET/CEST if dates are dynamic.
    # The hardcoded "Mon, Dec 30, 10:00 AM CET - Thu, Jan 02, 12:00 PM CET" might be specific.
    # Let's assume datetime(2024,12,30,tzinfo=USER_TZ_AMS).strftime('%Z') gives CET.
    # and datetime(2025,1,2,tzinfo=USER_TZ_AMS).strftime('%Z') gives CET (as DST not active).
    # This makes the hardcoded expected string for case 6 okay.
    if event_params == parse_format_test_cases[5][0]: # Timed Event - Crossing into next year
        start_dt_local = start_obj.astimezone(user_tz) # datetime(2024, 12, 30, 10, 0, 0, tzinfo=USER_TZ_AMS)
        end_dt_local = end_obj.astimezone(user_tz) # datetime(2025, 1, 2, 12, 0, 0, tzinfo=USER_TZ_AMS)
        # This assumes the function _correctly_ handles the different %Z for start and end if they differ.
        # The current implementation of parse_and_format_event_time uses %Z only on the end time for multi-day.
        # So, the expected string needs to reflect that: Start uses start's %Z, end uses end's %Z.
        # The function's format string is: f"{start_dt_aware.strftime('%a, %b %d, %I:%M %p %Z')} - {end_dt_aware.strftime('%a, %b %d, %I:%M %p %Z')}"
        # This is correct.
        pass


    assert result['time_display_str'] == expected_time_str
    assert result['duration_display_str'] == expected_duration_str
    assert result['is_all_day'] == expected_is_all_day
    assert isinstance(result['start_dt_for_grouping'], datetime)
    assert result['start_dt_for_grouping'].tzinfo is not None # Should be aware

def test_parse_and_format_event_time_no_start_val():
    assert parse_and_format_event_time({"start": {}, "end": {}}, USER_TZ_AMS) is None

def test_parse_and_format_event_time_none_user_tz(caplog):
    # Test when user_tz object itself is None.
    # The function expects a pytz.BaseTzInfo object.
    # If None is passed, it should handle it gracefully or log an error.
    # Current implementation uses user_tz.zone, which would cause AttributeError.
    event_data = {"start": {"dateTime": "2025-05-19T09:00:00+02:00"}, "end": {"dateTime": "2025-05-19T17:00:00+02:00"}}
    result = parse_and_format_event_time(event_data, None) # Pass None for user_tz
    # Expecting it to default to UTC or handle the error
    assert result is not None # Should still return a result structure
    assert result['time_display_str'] == '[Time Error - Missing Timezone]' # Updated assertion
    assert "user_tz cannot be None" in caplog.text # Check for specific log message

def test_parse_and_format_event_time_invalid_iso_string(caplog):
    event_data = {"start": {"dateTime": "INVALID_ISO_STRING"}, "end": {"dateTime": "INVALID_ISO_STRING"}}
    result = parse_and_format_event_time(event_data, USER_TZ_AMS)
    assert result['time_display_str'] == '[Time Error]'
    assert "Error in parse_and_format_event_time" in caplog.text # Check error was logged

# === Tests for format_event_list_for_agent ===

@pytest.fixture
def sample_events_dynamic():
    # Use BASE_TEST_DATE (Mon, Aug 19, 2024 UTC) to generate event dates
    # Event dates will be relative to this Monday.

    # Event 1: All day on Mon, Aug 19
    event1_start_date = BASE_TEST_DATE.date()
    event1_end_date = (BASE_TEST_DATE + timedelta(days=1)).date()

    # Event 2: Timed on Mon, Aug 19, 14:00-15:30 UTC
    event2_start_dt = BASE_TEST_DATE.replace(hour=14, minute=0, second=0)
    event2_end_dt = BASE_TEST_DATE.replace(hour=15, minute=30, second=0)

    # Event 3: Timed on Wed, Aug 21, 09:00-10:00 UTC
    event3_start_dt = (BASE_TEST_DATE + timedelta(days=2)).replace(hour=9, minute=0, second=0)
    event3_end_dt = (BASE_TEST_DATE + timedelta(days=2)).replace(hour=10, minute=0, second=0)

    # Event 4: Timed spanning Wed, Aug 21 16:00 UTC to Thu, Aug 22 18:00 UTC
    event4_start_dt = (BASE_TEST_DATE + timedelta(days=2)).replace(hour=16, minute=0, second=0)
    event4_end_dt = (BASE_TEST_DATE + timedelta(days=3)).replace(hour=18, minute=0, second=0)

    return [
        {
            "id": "event1_dyn", "summary": "Team Offsite (Dynamic)",
            "start": {"date": event1_start_date.isoformat()},
            "end": {"date": event1_end_date.isoformat()},
            "location": "Dynamic Mountain Retreat"
        },
        {
            "id": "event2_dyn", "summary": "Project Alpha Sync (Dynamic)",
            "start": {"dateTime": event2_start_dt.isoformat()},
            "end": {"dateTime": event2_end_dt.isoformat()},
            "description": "Discuss dynamic milestones"
        },
        {
            "id": "event3_dyn", "summary": "Client Demo (Dynamic)",
            "start": {"dateTime": event3_start_dt.isoformat()},
            "end": {"dateTime": event3_end_dt.isoformat()},
            "location": "Dynamic Client HQ"
        },
        {
            "id": "event4_dyn", "summary": "Workshop Series (Dynamic)",
            "start": {"dateTime": event4_start_dt.isoformat()},
            "end": {"dateTime": event4_end_dt.isoformat()}
        },
    ]

def test_format_event_list_for_agent_no_events():
    formatted_str = format_event_list_for_agent([], "this week", USER_TZ_STR_AMS)
    assert "<i>No events scheduled for this week.</i>" == formatted_str

def test_format_event_list_for_agent_with_events(sample_events_dynamic):
    # User in Amsterdam (USER_TZ_AMS)
    # BASE_TEST_DATE is Mon, Aug 19, 2024 UTC.
    # Event 1 (All day): Mon, Aug 19, 2024 (All Day) -> User TZ: Mon, Aug 19
    # Event 2 (Timed): Mon, Aug 19, 14:00-15:30 UTC -> User TZ: 04:00 PM - 05:30 PM CEST
    # Event 3 (Timed): Wed, Aug 21, 09:00-10:00 UTC -> User TZ: 11:00 AM - 12:00 PM CEST
    # Event 4 (Timed Spanning): Wed, Aug 21, 16:00 UTC - Thu, Aug 22, 18:00 UTC -> User TZ: Wed, Aug 21, 06:00 PM CEST - Thu, Aug 22, 08:00 PM CEST

    formatted_str = format_event_list_for_agent(sample_events_dynamic, "this dynamic period", USER_TZ_STR_AMS, include_ids=True)
    print(f"\n---Formatted Output for Amsterdam (Dynamic)---\n{formatted_str}\n---------------------------------")

    assert "🗓️ <b>Your Schedule: this dynamic period</b>" in formatted_str
    assert f"<i>(Times in {USER_TZ_STR_AMS})</i>" in formatted_str

    # Day Separators - dynamically check based on BASE_TEST_DATE and USER_TZ_AMS
    day1_ams = BASE_TEST_DATE.astimezone(USER_TZ_AMS) # Monday
    day3_ams = (BASE_TEST_DATE + timedelta(days=2)).astimezone(USER_TZ_AMS) # Wednesday

    assert f"🗓️ <b>{day1_ams.strftime('%a, %B %d, %Y')}</b>" in formatted_str # Mon, August 19, 2024
    assert f"🗓️ <b>{day3_ams.strftime('%a, %B %d, %Y')}</b>" in formatted_str # Wed, August 21, 2024
    assert "━━━━━━━━━━━━━━━━━━━━━━" in formatted_str

    # Event 1: Team Offsite (All day)
    assert "✨ <b>Team Offsite (Dynamic)</b>" in formatted_str
    assert f"<i>{day1_ams.strftime('%A, %d %B %Y')} (All Day)</i>" in formatted_str
    assert '<a href="https://www.google.com/maps/search/?api=1&query=Dynamic+Mountain+Retreat">Dynamic Mountain Retreat</a>' in formatted_str
    assert "<code>event1_dyn</code>" in formatted_str

    # Event 2: Project Alpha Sync
    assert "✨ <b>Project Alpha Sync (Dynamic)</b>" in formatted_str
    assert "<i>04:00 PM - 05:30 PM CEST (1h, 30min)</i>" in formatted_str

    # Event 3: Client Demo
    assert "✨ <b>Client Demo (Dynamic)</b>" in formatted_str
    assert "<i>11:00 AM - 12:00 PM CEST (1h)</i>" in formatted_str
    assert "Dynamic Client HQ" in formatted_str
    assert "<code>event3_dyn</code>" in formatted_str

    # Event 4: Workshop Series (Spanning days)
    assert "✨ <b>Workshop Series (Dynamic)</b>" in formatted_str
    # Wed, Aug 21, 06:00 PM CEST - Thu, Aug 22, 08:00 PM CEST (1d, 2h)
    start_e4_local = (BASE_TEST_DATE + timedelta(days=2)).replace(hour=16, minute=0).astimezone(USER_TZ_AMS)
    end_e4_local = (BASE_TEST_DATE + timedelta(days=3)).replace(hour=18, minute=0).astimezone(USER_TZ_AMS)
    expected_e4_str = f"{start_e4_local.strftime('%a, %b %d, %I:%M %p %Z')} - {end_e4_local.strftime('%a, %b %d, %I:%M %p %Z')} (1d, 2h)"
    assert f"<i>{expected_e4_str}</i>" in formatted_str
    assert "<code>event4_dyn</code>" in formatted_str

    assert formatted_str.count("✨ <b>") == len(sample_events_dynamic)

def test_format_event_list_for_agent_different_timezone(sample_events_dynamic):
    # User in Los Angeles (USER_TZ_LA)
    # BASE_TEST_DATE is Mon, Aug 19, 2024 UTC.
    # Event 1 (All day): Mon, Aug 19, 2024 (All Day) -> User TZ: Mon, Aug 19
    # Event 2 (Timed): Mon, Aug 19, 14:00-15:30 UTC -> User TZ: 07:00 AM - 08:30 AM PDT
    # Event 3 (Timed): Wed, Aug 21, 09:00-10:00 UTC -> User TZ: 02:00 AM - 03:00 AM PDT

    formatted_str = format_event_list_for_agent(sample_events_dynamic, "upcoming dynamic", USER_TZ_STR_LA, include_ids=False)
    print(f"\n---Formatted Output for Los Angeles (Dynamic)---\n{formatted_str}\n---------------------------------")

    assert "🗓️ <b>Your Schedule: upcoming dynamic</b>" in formatted_str
    assert f"<i>(Times in {USER_TZ_STR_LA})</i>" in formatted_str

    day1_la = BASE_TEST_DATE.astimezone(USER_TZ_LA) # Monday
    day3_la = (BASE_TEST_DATE + timedelta(days=2)).astimezone(USER_TZ_LA) # Wednesday

    assert f"🗓️ <b>{day1_la.strftime('%a, %B %d, %Y')}</b>" in formatted_str
    assert "✨ <b>Team Offsite (Dynamic)</b>" in formatted_str
    assert f"<i>{day1_la.strftime('%A, %d %B %Y')} (All Day)</i>" in formatted_str
    assert "✨ <b>Project Alpha Sync (Dynamic)</b>" in formatted_str
    assert "<i>07:00 AM - 08:30 AM PDT (1h, 30min)</i>" in formatted_str

    assert f"🗓️ <b>{day3_la.strftime('%a, %B %d, %Y')}</b>" in formatted_str
    assert "<i>02:00 AM - 03:00 AM PDT (1h)</i>" in formatted_str # For Event 3

def test_format_event_list_invalid_user_timezone(sample_events_dynamic, caplog):
    formatted_str = format_event_list_for_agent(sample_events, "this week", "Invalid/Zone")
    assert "<i>(Times in UTC)</i>" in formatted_str # Should default to UTC
    assert "Invalid user timezone 'Invalid/Zone', defaulting to UTC." in caplog.text

def test_format_event_list_time_period_sanitization():
    raw_period = "for 'June 2025'"
    expected_display_period = "June 2025"
    formatted_str = format_event_list_for_agent([], raw_period, USER_TZ_STR_AMS)
    print(f"\n---Formatted Output for Los Angeles---\n{formatted_str}\n---------------------------------")
    assert f"<i>No events scheduled for for &#x27;{html.escape(expected_display_period)}&#x27;.</i>" in formatted_str

def test_format_event_list_for_agent_event_with_time_error(sample_events, caplog):
    # Add an event that will cause parse_and_format_event_time to return its error state
    faulty_event = {"id": "event_error", "summary": "Faulty Event", "start": {"dateTime": "INVALID_ISO"}}
    events_with_faulty = [faulty_event] + sample_events

    formatted_str = format_event_list_for_agent(events_with_faulty, "this week", USER_TZ_STR_AMS)

    assert "✨ <b>Faulty Event</b>" in formatted_str
    assert "⏰ <i>[Time Error]</i>" in formatted_str # Check that the error string is displayed
    assert "Error in parse_and_format_event_time" in caplog.text # Ensure the error was logged by the sub-function

def test_format_event_list_for_agent_none_time_period(sample_events):
    # Test with time_period_str = None. The function should handle this gracefully.
    # Current implementation html.escapes it, so it would become "None" in the output.
    formatted_str = format_event_list_for_agent(sample_events, None, USER_TZ_STR_AMS)
    assert "<b>Your Schedule: None</b>" in formatted_str

def test_format_event_list_for_agent_none_user_timezone_str(sample_events, caplog):
    # Test with user_timezone_str = None. Should default to UTC.
    formatted_str = format_event_list_for_agent(sample_events, "this week", None)
    assert "<i>(Times in UTC)</i>" in formatted_str
    assert "Invalid user timezone 'None', defaulting to UTC." in caplog.text