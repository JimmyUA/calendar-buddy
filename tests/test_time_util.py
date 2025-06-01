import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, time
import pytz
import sys
import os

# Add the parent directory to the Python path to allow importing from 'time_util'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from time_util import get_next_day_range_iso, get_next_week_range_iso, format_to_nice_date

class TestTimeUtil(unittest.TestCase):

    @patch('time_util.datetime')
    def test_get_next_day_range_iso_new_york(self, mock_datetime_module):
        # Setup mock_now to return a fixed time (this time is treated as already in user_tz by the function)
        # The key is that datetime.now(user_tz) inside the function will use this.
        tz_str = 'America/New_York'
        user_tz = pytz.timezone(tz_str)

        # Let's say current time in New York is Oct 26, 2023, 10:00 AM
        fixed_now_in_new_york = user_tz.localize(datetime(2023, 10, 26, 10, 0, 0))
        mock_datetime_module.now.return_value = fixed_now_in_new_york

        # Expected: Next day (Oct 27) in New York
        expected_start_dt = user_tz.localize(datetime(2023, 10, 27, 0, 0, 0))
        expected_end_dt = user_tz.localize(datetime(2023, 10, 27, 23, 59, 59, 999999))

        start_iso, end_iso = get_next_day_range_iso(tz_str)

        self.assertEqual(start_iso, expected_start_dt.isoformat())
        self.assertEqual(end_iso, expected_end_dt.isoformat())

    @patch('time_util.datetime')
    def test_get_next_week_range_iso_sunday_before_8pm(self, mock_datetime_module):
        tz_str = 'America/Los_Angeles'
        user_tz = pytz.timezone(tz_str)

        # Sunday, October 22, 2023, 18:00:00 in LA
        fixed_now_in_la = user_tz.localize(datetime(2023, 10, 22, 18, 0, 0)) # Sunday
        mock_datetime_module.now.return_value = fixed_now_in_la

        # Expected: Starts Monday, Oct 23, 2023, ends Sunday, Oct 29, 2023
        expected_start_dt = user_tz.localize(datetime(2023, 10, 23, 0, 0, 0))
        expected_end_dt = user_tz.localize(datetime(2023, 10, 29, 23, 59, 59, 999999))

        start_iso, end_iso = get_next_week_range_iso(tz_str)

        self.assertEqual(start_iso, expected_start_dt.isoformat())
        self.assertEqual(end_iso, expected_end_dt.isoformat())

    @patch('time_util.datetime')
    def test_get_next_week_range_iso_sunday_after_8pm(self, mock_datetime_module):
        tz_str = 'Europe/London'
        user_tz = pytz.timezone(tz_str)

        # Sunday, October 22, 2023, 21:00:00 in London (BST - UTC+1)
        fixed_now_in_london = user_tz.localize(datetime(2023, 10, 22, 21, 0, 0)) # Sunday
        mock_datetime_module.now.return_value = fixed_now_in_london

        # Expected: Starts Monday, Oct 30, 2023, ends Sunday, Nov 5, 2023
        expected_start_dt = user_tz.localize(datetime(2023, 10, 30, 0, 0, 0))
        expected_end_dt = user_tz.localize(datetime(2023, 11, 5, 23, 59, 59, 999999))

        start_iso, end_iso = get_next_week_range_iso(tz_str)

        self.assertEqual(start_iso, expected_start_dt.isoformat())
        self.assertEqual(end_iso, expected_end_dt.isoformat())

    @patch('time_util.datetime')
    def test_get_next_week_range_iso_monday(self, mock_datetime_module):
        tz_str = 'Asia/Tokyo'
        user_tz = pytz.timezone(tz_str)

        # Monday, October 23, 2023, 10:00:00 in Tokyo
        fixed_now_in_tokyo = user_tz.localize(datetime(2023, 10, 23, 10, 0, 0)) # Monday
        mock_datetime_module.now.return_value = fixed_now_in_tokyo

        # Expected: Starts Monday, Oct 23, 2023, ends Sunday, Oct 29, 2023
        # (because it's Monday, so "next week" includes current day as start)
        # Correction: The logic calculates starting from the *next* Monday if it's not already past the trigger time on Sunday.
        # If it's Monday, it should give the *following* week.
        # No, if it's Monday, days_until_monday will be (0 - 0 + 7)%7 = 0. So it will be the current week.
        # The logic for `days_until_monday = (0 - now_in_timezone.weekday() + 7) % 7`
        # if today is Monday (weekday=0), days_until_monday is 0.
        # if today is Tuesday (weekday=1), days_until_monday is 6.
        # The logic is to find the *upcoming* Monday. If today *is* Monday, that's the start.

        expected_start_dt = user_tz.localize(datetime(2023, 10, 23, 0, 0, 0))
        expected_end_dt = user_tz.localize(datetime(2023, 10, 29, 23, 59, 59, 999999))

        start_iso, end_iso = get_next_week_range_iso(tz_str)

        self.assertEqual(start_iso, expected_start_dt.isoformat())
        self.assertEqual(end_iso, expected_end_dt.isoformat())

    def test_format_to_nice_date_utc(self):
        iso_utc = "2023-12-25T10:30:00Z"
        # Expected for UTC display: Mon, Dec 25, 2023, 10:30 AM (UTC)
        self.assertEqual(format_to_nice_date(iso_utc, "UTC"), "Mon, Dec 25, 2023, 10:30 AM (UTC)")

    def test_format_to_nice_date_timezone_aware_input(self):
        iso_ny = "2023-12-25T10:30:00-05:00" # New York time (EST)
        # Display in same timezone
        self.assertEqual(format_to_nice_date(iso_ny, "America/New_York"), "Mon, Dec 25, 2023, 10:30 AM (EST)")
        # Display in different timezone (e.g. LA, PST is UTC-8, EST is UTC-5, so LA is 3 hours behind)
        # 10:30 AM EST should be 7:30 AM PST
        self.assertEqual(format_to_nice_date(iso_ny, "America/Los_Angeles"), "Mon, Dec 25, 2023, 07:30 AM (PST)")

    def test_format_to_nice_date_dict_input(self):
        event_time_dict = {'dateTime': '2024-01-15T14:00:00+02:00', 'timeZone': 'Europe/Bucharest'}
        # Display in Bucharest time
        self.assertEqual(format_to_nice_date(event_time_dict, "Europe/Bucharest"), "Mon, Jan 15, 2024, 02:00 PM (EET)")
        # Display in UTC
        # 14:00 EET (UTC+2) is 12:00 UTC
        self.assertEqual(format_to_nice_date(event_time_dict, "UTC"), "Mon, Jan 15, 2024, 12:00 PM (UTC)")

    def test_format_to_nice_date_all_day_event(self):
        all_day_event_dict = {'date': '2024-03-10'} # This implies it's midnight in the event's original timezone (often assumed UTC by APIs if not specified)
        # Display in US/Eastern - March 10 2024 is when DST starts in US
        # If the date '2024-03-10' is treated as UTC midnight start
        # For 'America/New_York', 2024-03-10T00:00:00Z is 2024-03-09T19:00:00-05:00 (EST) before DST switch
        # However, the function logic for all-day converts to user's TZ then checks if time is midnight.
        # Let's test with a non-DST-tricky date first for simplicity.
        all_day_event_dict_simple = {'date': '2024-03-01'}
        self.assertEqual(format_to_nice_date(all_day_event_dict_simple, "America/New_York"), "Fri, Mar 01, 2024 (All-day)")
        self.assertEqual(format_to_nice_date(all_day_event_dict_simple, "UTC"), "Fri, Mar 01, 2024 (All-day)")

        # Test with a specific time that would be midnight in target TZ for an all-day event
        # If event is {'date': '2024-03-01'}, it means from 2024-03-01T00:00:00 to 2024-03-01T23:59:59 in its original unspecified TZ.
        # Our function converts to user_tz and checks for midnight.
        # So, if the input is {'date': '2024-07-04'}, it should show as all-day in any US timezone.
        july_4_dict = {'date': '2024-07-04'}
        self.assertEqual(format_to_nice_date(july_4_dict, "America/New_York"), "Thu, Jul 04, 2024 (All-day)")
        self.assertEqual(format_to_nice_date(july_4_dict, "America/Los_Angeles"), "Thu, Jul 04, 2024 (All-day)")


    def test_format_to_nice_date_invalid_timezone_str(self):
        iso_utc = "2023-12-25T10:30:00Z"
        # If user_timezone_str is invalid, it should default to UTC.
        # Expected for UTC display: Mon, Dec 25, 2023, 10:30 AM (UTC)
        self.assertEqual(format_to_nice_date(iso_utc, "Invalid/Timezone"), "Mon, Dec 25, 2023, 10:30 AM (UTC)")

    def test_format_to_nice_date_empty_input(self):
        self.assertEqual(format_to_nice_date(None, "America/New_York"), "N/A")
        self.assertEqual(format_to_nice_date("", "America/New_York"), "N/A")

    def test_format_to_nice_date_invalid_date_string(self):
        self.assertEqual(format_to_nice_date("not-a-date", "UTC"), "Invalid date (not-a-date)")
        dict_invalid_date = {'dateTime': 'invalid'}
        self.assertEqual(format_to_nice_date(dict_invalid_date, "UTC"), "Invalid date ({'dateTime': 'invalid'})")


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)

# Example to run this test:
# python -m unittest tests/test_time_util.py
