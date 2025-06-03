# tests/test_utils.py
import pytest
from datetime import datetime, date, timedelta
import pytz # For creating timezone objects for testing _format_event_time

from utils import _format_event_time, escape_markdown_v2

# === Tests for _format_event_time ===

USER_TZ_AMS = pytz.timezone("Europe/Amsterdam")
USER_TZ_LA = pytz.timezone("America/Los_Angeles")
USER_TZ_UTC = pytz.utc

@pytest.mark.parametrize(
    "event_data, user_tz, expected_output",
    [
        # Timed event, same day
        ({"start": {"dateTime": "2024-07-15T10:00:00+02:00"}, "end": {"dateTime": "2024-07-15T11:00:00+02:00"}}, USER_TZ_AMS, "Mon, Jul 15, 2024 at 10:00 AM CEST - 11:00 AM CEST"),
        # Timed event, spanning days
        ({"start": {"dateTime": "2024-07-15T22:00:00+02:00"}, "end": {"dateTime": "2024-07-16T01:00:00+02:00"}}, USER_TZ_AMS, "Mon, Jul 15, 2024 at 10:00 PM CEST - Jul 16, 2024 01:00 AM CEST"),
        # All-day event, single day
        ({"start": {"date": "2024-07-15"}, "end": {"date": "2024-07-16"}}, USER_TZ_AMS, "Mon, Jul 15 (All day)"),
        # All-day event, multi-day (e.g., 15th to 16th, so 2 days)
        ({"start": {"date": "2024-07-15"}, "end": {"date": "2024-07-17"}}, USER_TZ_AMS, "Mon, Jul 15 - Tue, Jul 16 (All day)"),
        # Timed event, different timezone (PDT to Amsterdam)
        ({"start": {"dateTime": "2024-07-15T10:00:00-07:00"}, "end": {"dateTime": "2024-07-15T11:00:00-07:00"}}, USER_TZ_AMS, "Mon, Jul 15, 2024 at 07:00 PM CEST - 08:00 PM CEST"),
        # Timed event, UTC to Amsterdam
        ({"start": {"dateTime": "2024-07-15T10:00:00Z"}, "end": {"dateTime": "2024-07-15T11:00:00Z"}}, USER_TZ_AMS, "Mon, Jul 15, 2024 at 12:00 PM CEST - 01:00 PM CEST"),
        # Edge case: Event ends at midnight
        ({"start": {"dateTime": "2024-07-15T22:00:00+02:00"}, "end": {"dateTime": "2024-07-16T00:00:00+02:00"}}, USER_TZ_AMS, "Mon, Jul 15, 2024 at 10:00 PM CEST - Jul 16, 2024 12:00 AM CEST"),
        # Edge case: Event starts at midnight
        ({"start": {"dateTime": "2024-07-15T00:00:00+02:00"}, "end": {"dateTime": "2024-07-15T02:00:00+02:00"}}, USER_TZ_AMS, "Mon, Jul 15, 2024 at 12:00 AM CEST - 02:00 AM CEST"),
    ]
)
def test_format_event_time_valid_cases(event_data, user_tz, expected_output):
    assert _format_event_time(event_data, user_tz) == expected_output

def test_format_event_time_missing_start_info():
    event = {"id": "test_event_1", "end": {"dateTime": "2024-07-15T11:00:00Z"}}
    assert _format_event_time(event, USER_TZ_UTC) == "[Unknown Start Time]"

def test_format_event_time_missing_end_datetime_for_timed_event():
    # If 'end' is missing 'dateTime' for a timed event, it should fallback to start_str
    # (current implementation does this: if not end_str: end_str = start_str)
    # This means start and end time will be the same.
    event = {"id": "test_event_2", "start": {"dateTime": "2024-07-15T10:00:00Z"}, "end": {}} # No end.dateTime or end.date
    # Expected: "Mon, Jul 15, 2024 at 10:00 AM UTC - 10:00 AM UTC" (or similar if format changes)
    # The format for same start/end might be just the start time, depending on preferences.
    # Current _format_event_time: "Mon, Jul 15, 2024 at 10:00 AM UTC - 10:00 AM UTC"
    assert _format_event_time(event, USER_TZ_UTC) == "Mon, Jul 15, 2024 at 10:00 AM UTC - 10:00 AM UTC"

def test_format_event_time_invalid_date_string(caplog):
    event = {"id": "test_event_3", "start": {"dateTime": "INVALID_STRING"}, "end": {"dateTime": "2024-07-15T11:00:00Z"}}
    result = _format_event_time(event, USER_TZ_UTC)
    assert "[Error Formatting]" in result
    assert "Error parsing/formatting event time" in caplog.text

def test_format_event_time_user_tz_none(caplog):
    event = {"id": "test_event_4", "start": {"dateTime": "2024-07-15T10:00:00Z"}, "end": {"dateTime": "2024-07-15T11:00:00Z"}}
    # The function signature requires pytz.BaseTzInfo, but testing defense if None is passed.
    # Current implementation would raise AttributeError. A more robust function would check.
    # For now, let's assert it raises AttributeError or test the intended behavior if it's handled.
    # Assuming the function is not changed to handle user_tz=None and relies on correct type.
    with pytest.raises(AttributeError): # Or TypeError, depending on how it's used
        _format_event_time(event, None)
    # If the function were changed to handle user_tz=None and default to UTC:
    # result = _format_event_time(event, None)
    # assert "10:00 AM UTC" in result # Or similar, depending on default logic
    # assert "user_tz was None, defaulted to UTC" in caplog.text


# === Tests for escape_markdown_v2 ===
class TestEscapeMarkdownV2:
    def test_no_special_chars(self):
        assert escape_markdown_v2("Hello world") == "Hello world"

    def test_all_special_chars(self):
        # _ * [ ] ( ) ~ ` > # + - = | { } . !
        original = "_*[]()~`>#+-=|{}.!"
        expected = r"\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!"  # Changed to raw string
        assert escape_markdown_v2(original) == expected

    def test_mixed_content(self):
        original = "This is a (test). It should *work*! #important"
        expected = r"This is a \(test\)\. It should \*work\*\! \#important"  # Changed to raw string
        assert escape_markdown_v2(original) == expected

    def test_empty_string(self):
        assert escape_markdown_v2("") == ""

    def test_already_escaped_chars(self):
        # Assuming \ is NOT a character that escape_markdown_v2 itself escapes.
        # So, "Hello \(world\)" becomes "Hello \\\(world\\\)"
        # because '(' and ')' are escaped.
        original = r"Hello \(world\)" # Changed to raw string
        expected = r"Hello \\\(world\\\)" # Expected output also needs to be raw or double-escaped
        assert escape_markdown_v2(original) == expected

    def test_only_special_chars_short(self):
        original = ".-_"
        expected = r"\.\-\_" # Changed to raw string
        assert escape_markdown_v2(original) == expected

    def test_numbers_and_special_chars(self):
        original = "1. Item (first)"
        expected = r"1\. Item \(first\)" # Changed to raw string
        assert escape_markdown_v2(original) == expected
