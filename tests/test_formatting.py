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

# === Tests for parse_and_format_event_time ===

@pytest.mark.parametrize(
    "event_data, user_tz, expected_time_str, expected_duration_str, expected_is_all_day",
    [
        # 1. Timed Event - Same Day
        (
            {
                "start": {"dateTime": "2025-05-19T09:00:00+02:00"}, # 9 AM CEST
                "end": {"dateTime": "2025-05-19T17:00:00+02:00"}    # 5 PM CEST
            },
            USER_TZ_AMS,
            "09:00 AM - 05:00 PM CEST", # Assuming %Z gives CEST for this date/tz
            "(8h)",
            False
        ),
        # 2. Timed Event - Spanning Days
        (
            {
                "start": {"dateTime": "2025-05-19T22:00:00+02:00"}, # 10 PM CEST Mon
                "end": {"dateTime": "2025-05-20T02:00:00+02:00"}    # 2 AM CEST Tue
            },
            USER_TZ_AMS,
            "Mon, May 19, 10:00 PM CEST - Tue, May 20, 02:00 AM CEST",
            "(4h)",
            False
        ),
        # 3. All-Day Event - Single Day
        (
            {
                "summary": "Public Holiday",
                "start": {"date": "2025-07-04"},
                "end": {"date": "2025-07-05"} # Google Calendar end date for all-day is exclusive
            },
            USER_TZ_LA, # Timezone still matters for how '%A' etc. are interpreted
            "Friday, 04 July 2025 (All Day)",
            "", # Or "(All day)" if you prefer that from the function
            True
        ),
        # 4. All-Day Event - Multi-Day
        (
            {
                "start": {"date": "2025-12-24"},
                "end": {"date": "2025-12-27"} # Events on 24th, 25th, 26th
            },
            USER_TZ_AMS,
            "Wednesday, 24 December 2025 - Friday, 26 December 2025 (All Day)",
            "",
            True
        ),
        # 5. Timed Event - Short Duration (minutes)
        (
            {
                "start": {"dateTime": "2025-05-19T10:15:00+02:00"},
                "end": {"dateTime": "2025-05-19T10:45:00+02:00"}
            },
            USER_TZ_AMS,
            "10:15 AM - 10:45 AM CEST",
            "(30min)",
            False
        ),
        # 6. Timed Event - Crossing into next year (for duration parts)
        (
            {
                "start": {"dateTime": "2024-12-30T10:00:00+01:00"}, # CET
                "end": {"dateTime": "2025-01-02T12:00:00+01:00"}    # CET
            },
            USER_TZ_AMS, # Amsterdam
            "Mon, Dec 30, 10:00 AM CET - Thu, Jan 02, 12:00 PM CET", # Check this formatting for multi-day
            "(3d, 2h)", # 3 full days and 2 hours
            False
        ),
        # 7. No end dateTime provided (should default to 1 hour duration)
        # Your function uses end_val directly, if it's missing, it might error.
        # The code actually uses end_val = end_info.get('dateTime', end_info.get('date'))
        # If both are missing from end_info, end_val will be None.
        # Let's assume Google API always provides at least 'date' or 'dateTime' in 'end' if 'start' has it.
        # For testing a missing end_val specifically for a timed event:
        (
             {
                "start": {"dateTime": "2025-05-19T14:00:00+02:00"},
                "end": {"dateTime": "2025-05-19T14:00:00+02:00"} # Test 0 duration explicitly
             },
             USER_TZ_AMS,
             "02:00 PM - 02:00 PM CEST",
             "", # 0 duration
             False
        ),
        # 8. Event crossing different timezones in ISO string (should be normalized by astimezone)
        (
            {
                "start": {"dateTime": "2025-08-15T10:00:00-07:00"}, # 10 AM PDT
                "end": {"dateTime": "2025-08-15T13:00:00-07:00"}    # 1 PM PDT
            },
            USER_TZ_AMS, # User is in Amsterdam, wants to see time in CEST
            "07:00 PM - 10:00 PM CEST", # 10 AM PDT is 7 PM CEST
            "(3h)",
            False
        ),
    ]
)
def test_parse_and_format_event_time(event_data, user_tz, expected_time_str, expected_duration_str, expected_is_all_day):
    result = parse_and_format_event_time(event_data, user_tz)
    assert result is not None
    assert result['time_display_str'] == expected_time_str
    assert result['duration_display_str'] == expected_duration_str
    assert result['is_all_day'] == expected_is_all_day
    assert isinstance(result['start_dt_for_grouping'], datetime)
    assert result['start_dt_for_grouping'].tzinfo is not None # Should be aware

def test_parse_and_format_event_time_no_start_val():
    assert parse_and_format_event_time({"start": {}, "end": {}}, USER_TZ_AMS) is None

def test_parse_and_format_event_time_invalid_iso_string(caplog):
    event_data = {"start": {"dateTime": "INVALID_ISO_STRING"}, "end": {"dateTime": "INVALID_ISO_STRING"}}
    result = parse_and_format_event_time(event_data, USER_TZ_AMS)
    assert result['time_display_str'] == '[Time Error]'
    assert "Error in parse_and_format_event_time" in caplog.text # Check error was logged

# === Tests for format_event_list_for_agent ===

@pytest.fixture
def sample_events():
    # Times are in UTC for consistency, will be converted by the formatter
    return [
        { # Event 1: All day
            "id": "event1", "summary": "Team Offsite",
            "start": {"date": "2025-06-10"},
            "end": {"date": "2025-06-11"},
            "location": "Mountain Retreat"
        },
        { # Event 2: Timed, same day
            "id": "event2", "summary": "Project Alpha Sync",
            "start": {"dateTime": "2025-06-10T14:00:00Z"}, # 2 PM UTC
            "end": {"dateTime": "2025-06-10T15:30:00Z"},   # 3:30 PM UTC
            "description": "Discuss milestones"
        },
        { # Event 3: Timed, another day
            "id": "event3", "summary": "Client Demo",
            "start": {"dateTime": "2025-06-12T09:00:00Z"}, # 9 AM UTC
            "end": {"dateTime": "2025-06-12T10:00:00Z"},   # 10 AM UTC
            "location": "Client HQ, Big City"
        },
        { # Event 4: Spans multiple days (timed)
            "id": "event4", "summary": "Workshop Series",
            "start": {"dateTime": "2025-06-12T16:00:00Z"}, # Day 1: 4 PM UTC
            "end": {"dateTime": "2025-06-13T18:00:00Z"}    # Day 2: 6 PM UTC
        },
    ]

def test_format_event_list_for_agent_no_events():
    formatted_str = format_event_list_for_agent([], "this week", USER_TZ_STR_AMS)
    assert "<i>No events scheduled for this week.</i>" == formatted_str

def test_format_event_list_for_agent_with_events(sample_events):
    # User in Amsterdam (UTC+2 during DST for June)
    # Event 1 (All day): Tue, Jun 10, 2025 (All Day)
    # Event 2 (Timed): 04:00 PM - 05:30 PM CEST (1h, 30min) on Tue, Jun 10
    # Event 3 (Timed): 11:00 AM - 12:00 PM CEST (1h) on Thu, Jun 12
    # Event 4 (Timed Spanning): Thu, Jun 12, 06:00 PM CEST - Fri, Jun 13, 08:00 PM CEST (1d, 2h)

    formatted_str = format_event_list_for_agent(sample_events, "next week", USER_TZ_STR_AMS, include_ids=True)
    print(f"\n---Formatted Output for Amsterdam---\n{formatted_str}\n---------------------------------") # For manual inspection

    # General Header
    assert "🗓️ <b>Your Schedule: next week</b>" in formatted_str
    assert f"<i>(Times in {USER_TZ_STR_AMS})</i>" in formatted_str

    # Day Separators (check presence and basic format)
    assert "🗓️ <b>Tue, June 10, 2025</b>" in formatted_str
    assert "🗓️ <b>Thu, June 12, 2025</b>" in formatted_str
    assert "━━━━━━━━━━━━━━━━━━━━━━" in formatted_str

    # Event 1: Team Offsite (All day)
    assert "✨ <b>Team Offsite</b>" in formatted_str
    assert "<i>Tuesday, 10 June 2025 (All Day)</i>" in formatted_str # Check all-day format
    assert '<a href="https://www.google.com/maps/search/?api=1&query=Mountain+Retreat">Mountain Retreat</a>' in formatted_str
    assert "<code>event1</code>" in formatted_str

    # Event 2: Project Alpha Sync
    assert "✨ <b>Project Alpha Sync</b>" in formatted_str
    assert "<i>04:00 PM - 05:30 PM CEST (1h, 30min)</i>" in formatted_str # Verify time and duration
    # Description is not shown in this format by default, only location

    # Event 3: Client Demo
    assert "✨ <b>Client Demo</b>" in formatted_str
    assert "<i>11:00 AM - 12:00 PM CEST (1h)</i>" in formatted_str
    assert "Client HQ, Big City" in formatted_str # Check location link rendering
    assert "<code>event3</code>" in formatted_str

    # Event 4: Workshop Series (Spanning days)
    assert "✨ <b>Workshop Series</b>" in formatted_str
    assert "<i>Thu, Jun 12, 06:00 PM CEST - Fri, Jun 13, 08:00 PM CEST (1d, 2h)</i>" in formatted_str
    assert "<code>event4</code>" in formatted_str

    # Check for spacing (blank lines between events on same day)
    # This is harder to assert precisely without parsing HTML, but check general structure.
    # Count occurrences of the "✨ <b>" to ensure all events are present
    assert formatted_str.count("✨ <b>") == len(sample_events)

def test_format_event_list_for_agent_different_timezone(sample_events):
    # User in Los Angeles (UTC-7 during DST for June)
    # Event 1 (All day): Tue, Jun 10, 2025 (All Day) (Day name might change due to TZ)
    # Event 2 (Timed): 07:00 AM - 08:30 AM PDT (1h, 30min) on Tue, Jun 10
    # Event 3 (Timed): 02:00 AM - 03:00 AM PDT (1h) on Thu, Jun 12

    formatted_str = format_event_list_for_agent(sample_events, "upcoming", USER_TZ_STR_LA, include_ids=False)
    print(f"\n---Formatted Output for Los Angeles---\n{formatted_str}\n---------------------------------")

    assert "🗓️ <b>Your Schedule: upcoming</b>" in formatted_str
    assert f"<i>(Times in {USER_TZ_STR_LA})</i>" in formatted_str

    assert "🗓️ <b>Tue, June 10, 2025</b>" in formatted_str # Day grouping based on LA time
    assert "✨ <b>Team Offsite</b>" in formatted_str
    assert "<i>Tuesday, 10 June 2025 (All Day)</i>" in formatted_str
    assert "✨ <b>Project Alpha Sync</b>" in formatted_str
    assert "<i>07:00 AM - 08:30 AM PDT (1h, 30min)</i>" in formatted_str

    assert "🗓️ <b>Thu, June 12, 2025</b>" in formatted_str # Event 3
    assert "<i>02:00 AM - 03:00 AM PDT (1h)</i>" in formatted_str # For Event 3

def test_format_event_list_invalid_user_timezone(sample_events, caplog):
    formatted_str = format_event_list_for_agent(sample_events, "this week", "Invalid/Zone")
    assert "<i>(Times in UTC)</i>" in formatted_str # Should default to UTC
    assert "Invalid user timezone 'Invalid/Zone', defaulting to UTC." in caplog.text

def test_format_event_list_time_period_sanitization():
    raw_period = "for 'June 2025'"
    expected_display_period = "June 2025"
    formatted_str = format_event_list_for_agent([], raw_period, USER_TZ_STR_AMS)
    print(f"\n---Formatted Output for Los Angeles---\n{formatted_str}\n---------------------------------")
    assert f"<i>No events scheduled for for &#x27;{html.escape(expected_display_period)}&#x27;.</i>" in formatted_str