# tests/test_utils.py
import pytest
from datetime import datetime

from time_util import format_to_nice_date


# Assuming your utility function is in a file named 'date_utils.py'
# or 'utils.py' at the root of your project.
# Adjust the import path as necessary.
# If it's in your_project_root/utils.py:
# If it's in your_project_root/your_module/date_utils.py:
# from your_module.date_utils import format_to_nice_date


# Test cases with different valid ISO date strings
@pytest.mark.parametrize(
    "iso_input, expected_output",
    [
        # Test case from your example (with timezone offset)
        ("2025-05-18T12:33:00+02:00", "Sunday, 18 May 2025 · 12:33"),
        # Test case with UTC (Z suffix)
        ("2024-12-25T09:00:00Z", "Wednesday, 25 December 2024 · 09:00"),
        # Test case with different timezone offset
        ("2023-07-04T17:45:30-07:00", "Tuesday, 4 July 2023 · 17:45"),
        # Test case with no timezone offset (naive datetime, will be treated as local by strftime)
        # Note: datetime.fromisoformat() creates a naive datetime if no offset is present.
        # The output of strftime will depend on the system's locale settings for month/day names
        # if no locale is explicitly set. For consistency, it's often better for ISO strings
        # to have timezone info.
        ("2022-01-01T00:00:00", "Saturday, 1 January 2022 · 00:00"),
        # Test with single digit day and month (checking '%-d')
        ("2024-03-05T08:05:00+01:00", "Tuesday, 5 March 2024 · 08:05"),
        # Test with different hour/minute
        ("2025-11-20T23:59:59+00:00", "Thursday, 20 November 2025 · 23:59"),
    ],
)
def test_format_to_nice_date_valid_inputs(iso_input, expected_output):
    """
    Tests format_to_nice_date with various valid ISO 8601 date strings.
    """
    assert format_to_nice_date(iso_input) == expected_output


# Test cases for invalid inputs
def test_format_to_nice_date_invalid_format():
    """
    Tests that format_to_nice_date raises ValueError for incorrectly formatted strings.
    """
    with pytest.raises(ValueError, match="Invalid isoformat string"):
        format_to_nice_date("2025/05/18 12:33:00")  # Incorrect format

    with pytest.raises(ValueError, match="Invalid isoformat string"):
        format_to_nice_date("Not a date")

    with pytest.raises(ValueError, match="Invalid isoformat string"):
        format_to_nice_date("2025-05-18T12:33:00X02:00") # Invalid timezone format


def test_format_to_nice_date_invalid_date_parts():
    """
    Tests that format_to_nice_date raises ValueError for invalid date/time components.
    """
    with pytest.raises(ValueError, match="month must be in 1..12"):
        format_to_nice_date("2025-13-18T12:33:00+02:00")  # Invalid month

    with pytest.raises(ValueError, match="day is out of range for month"):
        format_to_nice_date("2025-02-30T12:33:00+02:00")  # Invalid day for February

    with pytest.raises(ValueError, match="hour must be in 0..23"):
        format_to_nice_date("2025-05-18T25:33:00+02:00")  # Invalid hour


# Note on zoneinfo:
# Your current function `format_to_nice_date` uses `datetime.fromisoformat()`.
# If the input ISO string has timezone offset information (e.g., +02:00 or Z),
# `datetime.fromisoformat()` will create a timezone-aware datetime object.
# The `strftime` method on a timezone-aware object will format the time
# *according to that object's stored timezone*.
# The `zoneinfo` import in your original snippet isn't actually used by this function.
# If you intended to convert the datetime to a *specific* target timezone
# before formatting, you would need to use `dt.astimezone(ZoneInfo("Your/TargetZone"))`.
# The current tests reflect the behavior of your provided function.

from utils import escape_markdown_v2

class TestEscapeMarkdownV2:
    def test_no_special_chars(self):
        assert escape_markdown_v2("Hello world") == "Hello world"

    def test_all_special_chars(self):
        # _ * [ ] ( ) ~ ` > # + - = | { } . !
        original = "_*[]()~`>#+-=|{}.!"
        expected = "\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!"
        assert escape_markdown_v2(original) == expected

    def test_mixed_content(self):
        original = "This is a (test). It should *work*! #important"
        expected = "This is a \(test\)\. It should \*work\*\! \#important"
        assert escape_markdown_v2(original) == expected

    def test_empty_string(self):
        assert escape_markdown_v2("") == ""

    def test_already_escaped_chars(self):
        # Assuming \ is NOT a character that escape_markdown_v2 itself escapes.
        # So, "Hello \(world\)" becomes "Hello \\\(world\\\)"
        # because '(' and ')' are escaped.
        original = "Hello \(world\)"
        expected = "Hello \\\(world\\\)"
        assert escape_markdown_v2(original) == expected

    def test_only_special_chars_short(self):
        original = ".-_"
        expected = "\.\-\_"
        assert escape_markdown_v2(original) == expected
    
    def test_numbers_and_special_chars(self):
        original = "1. Item (first)"
        expected = "1\. Item \(first\)"
        assert escape_markdown_v2(original) == expected
