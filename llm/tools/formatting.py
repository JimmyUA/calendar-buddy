import html
import logging
import urllib.parse
from datetime import datetime, timedelta

# Timezone libraries
import pytz
from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta  # For duration
from pytz.exceptions import UnknownTimeZoneError

logger = logging.getLogger(__name__)


def parse_and_format_event_time(event_data: dict, user_tz: pytz.BaseTzInfo) -> dict | None:
    start_info = event_data.get('start', {})
    end_info = event_data.get('end', {})
    start_val = start_info.get('dateTime', start_info.get('date'))
    end_val = end_info.get('dateTime', end_info.get('date'))

    if not start_val:
        return None

    if user_tz is None:
        logger.error("Error in parse_and_format_event_time: user_tz cannot be None.")
        # Return a default error structure that format_event_list_for_agent can handle
        return {
            'is_all_day': False,
            'start_dt_for_grouping': datetime.now(pytz.utc), # Fallback
            'time_display_str': '[Time Error - Missing Timezone]',
            'duration_display_str': ''
        }

    try:
        is_all_day = 'date' in start_info

        if is_all_day:
            start_date_obj = dateutil_parser.isoparse(start_val).date()
            # For display, the event "occurs" on this start_date_obj in the user's view
            start_dt_aware_for_display = user_tz.localize(datetime.combine(start_date_obj, datetime.min.time()))
            # For grouping, use this localized start
            start_dt_for_grouping = start_dt_aware_for_display

            duration_str = ""  # Usually no duration shown for all-day events like "(1 day)"

            if end_val:
                end_date_obj_exclusive = dateutil_parser.isoparse(end_val).date()
                # Calculate the number of days the event spans
                # For Google Calendar, an event from 2025-07-04 to 2025-07-05 is a 1-day event on July 4th.
                # An event from 2025-07-04 to 2025-07-06 is a 2-day event on July 4th and July 5th.
                num_days = (end_date_obj_exclusive - start_date_obj).days

                if num_days <= 1:  # Single all-day event
                    time_str = f"{start_dt_aware_for_display.strftime('%A, %d %B %Y')} (All Day)"
                else:  # Multi-day all-day event
                    # The actual last day of the event is one day before the exclusive end date
                    display_end_date_obj = end_date_obj_exclusive - timedelta(days=1)
                    display_end_dt_aware = user_tz.localize(datetime.combine(display_end_date_obj, datetime.min.time()))
                    time_str = f"{start_dt_aware_for_display.strftime('%A, %d %B %Y')} - {display_end_dt_aware.strftime('%A, %d %B %Y')} (All Day)"
            else:  # Should not happen if Google API is consistent, but defensive
                time_str = f"{start_dt_aware_for_display.strftime('%A, %d %B %Y')} (All Day)"

        else:  # Timed event
            start_dt_aware = dateutil_parser.isoparse(start_val).astimezone(user_tz)
            start_dt_for_grouping = start_dt_aware  # Use the actual aware time for grouping
            end_dt_aware = dateutil_parser.isoparse(end_val).astimezone(user_tz)
            # ... (rest of your existing timed event logic for time_str and duration_str) ...
            # Format for display
            if start_dt_aware.date() == end_dt_aware.date():
                time_str = f"{start_dt_aware.strftime('%I:%M %p')} - {end_dt_aware.strftime('%I:%M %p %Z')}"
            else:  # Spans multiple days
                time_str = f"{start_dt_aware.strftime('%a, %b %d, %I:%M %p %Z')} - {end_dt_aware.strftime('%a, %b %d, %I:%M %p %Z')}"

            # Calculate duration
            delta = relativedelta(end_dt_aware, start_dt_aware)
            parts = []
            if delta.years: parts.append(f"{delta.years}y")
            if delta.months: parts.append(f"{delta.months}m")
            if delta.days and (
                    delta.years or delta.months or delta.days > 0 or start_dt_aware.date() != end_dt_aware.date()):
                parts.append(f"{delta.days}d")
            if delta.hours: parts.append(f"{delta.hours}h")
            if delta.minutes: parts.append(f"{delta.minutes}min")
            duration_str = f"({', '.join(parts)})" if parts else ""

        return {
            'is_all_day': is_all_day,
            'start_dt_for_grouping': start_dt_for_grouping,
            'time_display_str': time_str.strip(),
            'duration_display_str': duration_str.strip()
        }
    except Exception as e:
        logger.error(f"Error in parse_and_format_event_time: {e}", exc_info=True)
        return {'time_display_str': '[Time Error]', 'duration_display_str': '',
                'start_dt_for_grouping': datetime.now(pytz.utc)}

# --- NEW Formatting Function ---
def format_event_list_for_agent(events: list, time_period_str: str, user_timezone_str: str,
                                include_ids: bool = False) -> str:
    if not events:
        return f"<i>No events scheduled for {html.escape(time_period_str)}.</i>"

    try:
        user_tz = pytz.timezone(user_timezone_str)
    except UnknownTimeZoneError:
        logger.warning(f"Invalid user timezone '{user_timezone_str}', defaulting to UTC.")
        user_tz = pytz.utc
        user_timezone_str = "UTC"  # Update for display

    # Sanitize time_period_str for the header (it might come from user input via LLM)
    # Example: "for 'May 19, 2025 to May 25, 2025'" -> "May 19 - May 25, 2025"
    display_period = time_period_str.replace("for '", "").replace("'", "").replace(" to ", " - ")
    if "matching" in display_period.lower():  # Handle search result context
        display_period = f"matching search: {display_period.split('matching ')[-1]}"

    output_lines = [
        f"🗓️ <b>Your Schedule: {html.escape(display_period)}</b>",
        f"<i>(Times in {html.escape(user_timezone_str)})</i>\n"  # Newline after for spacing
    ]
    current_day_str = None

    # Sort events by start time
    events.sort(key=lambda e: e.get('start', {}).get('dateTime', e.get('start', {}).get('date', '')))

    for event_data in events:
        summary = html.escape(event_data.get('summary', 'No Title'))
        location = event_data.get('location')
        event_id = event_data.get('id')

        time_info = parse_and_format_event_time(event_data, user_tz)
        if not time_info:  # Should be handled by parse_and_format_event_time returning a default
            parsed_time_str = "[Error processing time]"
            parsed_duration_str = ""
            event_start_dt = datetime.now(user_tz)  # Fallback for grouping
        else:
            parsed_time_str = time_info['time_display_str']
            parsed_duration_str = time_info['duration_display_str']
            event_start_dt = time_info['start_dt_for_grouping']

        day_str_for_grouping = event_start_dt.strftime('%a, %B %d, %Y')  # More readable day string
        # Day Separator
        if day_str_for_grouping != current_day_str:
            output_lines.append("━━━━━━━━━━━━━━━━━━━━━━")  # Or use <hr> if you test its rendering
            output_lines.append(f"🗓️ <b>{html.escape(day_str_for_grouping)}</b>")
            output_lines.append("━━━━━━━━━━━━━━━━━━━━━━")
            current_day_str = day_str_for_grouping

        # Event Item
        output_lines.append(f"  ✨ <b>{summary}</b>")  # Intend with spaces
        if parsed_time_str:
            time_line = f"⏰ <i>{html.escape(parsed_time_str)}"  # Use <pre> for indent
            if parsed_duration_str and not time_info.get('is_all_day'):
                time_line += f" {html.escape(parsed_duration_str)}"
            time_line += "</i>"
            output_lines.append(time_line)

        if location:
            encoded_location = urllib.parse.quote_plus(location)
            maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_location}"
            output_lines.append(f'📍 <a href="{maps_url}">{html.escape(location)}</a>')

        output_lines.append("")  # Add a blank line for spacing between events within the same day

    # Remove last blank line if added
    if output_lines and output_lines[-1] == "":
        output_lines.pop()

    return "\n".join(output_lines)

