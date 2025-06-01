import unittest
import html
import sys
import os

# Add the parent directory to the Python path to allow importing from 'handler' and 'time_util'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from handler.message_formatter import format_daily_summary, format_weekly_summary
# We need to import time_util as it's used by the formatter, but we won't directly mock it here
# unless specific time formatting outputs under test are highly variable.
# The tests for time_util.format_to_nice_date cover its correctness.

class TestMessageFormatter(unittest.TestCase):

    def test_format_daily_summary_no_events(self):
        self.assertEqual(format_daily_summary([], "UTC"), "Looks like there are no events scheduled for tomorrow!")

    def test_format_daily_summary_with_events(self):
        events = [
            {
                "summary": "Team Meeting <Important>",
                "start": {"dateTime": "2023-10-27T09:00:00Z"},
                "end": {"dateTime": "2023-10-27T10:00:00Z"},
                "location": "Conference Room 1",
                "description": "Discuss project updates. This is a long description that should be truncated."
            },
            {
                "summary": "Lunch with Client",
                "start": {"date": "2023-10-27"}, # All-day event
                "end": {"date": "2023-10-27"},
                # No location, no description
            }
        ]
        user_timezone_str = "America/New_York" # UTC-4 for these dates (EDT)
        # Expected times in New York:
        # Event 1: 5:00 AM - 6:00 AM EDT
        # Event 2: All-day

        expected_output_parts = [
            "📅 <b>Events for Tomorrow</b> 📅",
            f"✨ <b>{html.escape('Team Meeting <Important>')}</b>",
            # time_util.format_to_nice_date will convert 2023-10-27T09:00:00Z
            # to something like "Fri, Oct 27, 2023, 05:00 AM (EDT)"
            # We rely on test_time_util for the exact format of the date.
            "<i>Start:</i> Fri, Oct 27, 2023, 05:00 AM (EDT)", # Assuming format_to_nice_date works as tested
            "<i>End:</i>   Fri, Oct 27, 2023, 06:00 AM (EDT)",
            f"<i>Where:</i> {html.escape('Conference Room 1')}",
            f"<i>About:</i> {html.escape('Discuss project updates. This is a long descripti')}...",
            f"✨ <b>{html.escape('Lunch with Client')}</b>",
            "<i>Start:</i> Fri, Oct 27, 2023 (All-day)",
            "<i>End:</i>   Fri, Oct 27, 2023 (All-day)", # End date for all-day is also formatted
        ]

        actual_output = format_daily_summary(events, user_timezone_str)
        # print("\nActual Daily Summary Output:\n", actual_output) # For debugging

        for part in expected_output_parts:
            self.assertIn(part, actual_output)

        # Check that description for the second event is not present
        self.assertNotIn("<i>About:</i>", actual_output.split(f"✨ <b>{html.escape('Lunch with Client')}</b>")[1])


    def test_format_weekly_summary_no_events(self):
        self.assertEqual(format_weekly_summary([], "UTC"), "Looks like there are no events scheduled for next week!")

    def test_format_weekly_summary_with_events(self):
        events = [
            {
                "summary": "Weekly Review & Planning",
                "start": {"dateTime": "2023-10-30T14:00:00Z"}, # Monday
                "end": {"dateTime": "2023-10-30T15:30:00Z"},
                "description": "Plan for the upcoming week."
            }
        ]
        user_timezone_str = "Europe/Berlin" # UTC+2 for this date (CEST)
        # Expected time in Berlin: 16:00 - 17:30 CEST

        expected_output_parts = [
            "🗓️ <b>Upcoming Events Next Week</b> 🗓️",
            f"✨ <b>{html.escape('Weekly Review & Planning')}</b>",
            # Expected: "Mon, Oct 30, 2023, 04:00 PM (CEST)"
            "<i>Start:</i> Mon, Oct 30, 2023, 04:00 PM (CEST)",
            "<i>End:</i>   Mon, Oct 30, 2023, 05:30 PM (CEST)",
            f"<i>About:</i> {html.escape('Plan for the upcoming week.')}"
        ]

        actual_output = format_weekly_summary(events, user_timezone_str)
        # print("\nActual Weekly Summary Output:\n", actual_output) # For debugging

        for part in expected_output_parts:
            self.assertIn(part, actual_output)

        # Check that location for the event is not present
        self.assertNotIn("<i>Where:</i>", actual_output)

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)

# Example to run this test:
# python -m unittest tests/test_message_formatter.py
