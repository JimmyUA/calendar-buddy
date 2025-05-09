import logging
import urllib.parse
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta # For duration

# Timezone libraries
import pytz
from dateutil import parser as dateutil_parser
from pytz.exceptions import UnknownTimeZoneError

logger = logging.getLogger(__name__)

def parse_and_format_event_time(event_data: dict, user_tz: pytz.BaseTzInfo) -> dict | None:
    """
    Parses Google Calendar event time data and returns structured, timezone-aware info.

    Returns:
        A dictionary like:
        {
            'is_all_day': bool,
            'start_dt': datetime, # Timezone-aware in user_tz
            'end_dt': datetime,   # Timezone-aware in user_tz
            'time_str': str,    # Pre-formatted basic time string
            'duration_str': str # Optional: Human-readable duration
        }
        or None if parsing fails.
    """
    start_info = event_data.get('start', {})
    end_info = event_data.get('end', {})

    start_str = start_info.get('dateTime', start_info.get('date'))
    end_str = end_info.get('dateTime', end_info.get('date'))

    if not start_str:
        logger.warning(f"Event missing start date/time info. Event ID: {event_data.get('id')}")
        return None

    try:
        is_all_day = 'date' in start_info
        start_dt_aware = None
        end_dt_aware = None
        time_str = ""
        duration_str = ""

        if is_all_day:
            start_dt_naive = dateutil_parser.isoparse(start_str).date()
            # For calculation/comparison, treat all-day start/end as start of day in user's TZ
            start_dt_aware = user_tz.localize(datetime.combine(start_dt_naive, datetime.min.time()))
            # Google's all-day end date is exclusive
            end_dt_naive = dateutil_parser.isoparse(end_info.get('date', start_str)).date()  # Use start if end missing
            # Treat end as start of the *next* day in UTC for duration calc, then convert
            end_dt_for_calc = datetime.combine(end_dt_naive, datetime.min.time())
            end_dt_aware = user_tz.localize(end_dt_for_calc)  # End is start of next day

            num_days = (end_dt_naive - start_dt_naive).days
            if num_days <= 1:
                time_str = f"{start_dt_naive.strftime('%a, %b %d')} (All Day)"
                duration_str = "All day"
            else:
                # Display end date is one day prior to exclusive date
                display_end_dt = end_dt_naive - timedelta(days=1)
                time_str = f"{start_dt_naive.strftime('%a, %b %d')} - {display_end_dt.strftime('%a, %b %d')} (All Day)"
                duration_str = f"{num_days} days"

        else:  # Timed event
            if not end_str: end_str = start_str  # Should not happen, but fallback

            start_dt_aware = dateutil_parser.isoparse(start_str).astimezone(user_tz)
            end_dt_aware = dateutil_parser.isoparse(end_str).astimezone(user_tz)

            start_fmt = start_dt_aware.strftime('%I:%M %p')  # Time only
            end_fmt = end_dt_aware.strftime('%I:%M %p %Z')  # Time + Zone

            if start_dt_aware.date() == end_dt_aware.date():
                time_str = f"{start_dt_aware.strftime('%a, %b %d')}, {start_fmt} - {end_fmt}"
            else:
                # Multi-day timed event
                start_fmt_full = start_dt_aware.strftime('%a, %b %d, %I:%M %p %Z')
                end_fmt_full = end_dt_aware.strftime('%a, %b %d, %I:%M %p %Z')
                time_str = f"{start_fmt_full} - {end_fmt_full}"

            # Calculate duration
            delta = relativedelta(end_dt_aware, start_dt_aware)
            parts = []
            if delta.years: parts.append(f"{delta.years}y")
            if delta.months: parts.append(f"{delta.months}m")
            if delta.days: parts.append(f"{delta.days}d")
            if delta.hours: parts.append(f"{delta.hours}h")
            if delta.minutes: parts.append(f"{delta.minutes}min")
            duration_str = " ".join(parts) if parts else ""

        return {
            'is_all_day': is_all_day,
            'start_dt': start_dt_aware,
            'end_dt': end_dt_aware,
            'time_str': time_str.strip(),
            'duration_str': duration_str.strip()
        }

    except Exception as e:
        logger.error(
            f"Error parsing/formatting event time: {e}. Event ID: {event_data.get('id')}, Start: '{start_str}', End: '{end_str}'",
            exc_info=True)
        return None  # Indicate failure

# --- NEW Formatting Function ---
def format_event_list_for_agent(events: list, time_period_str: str, user_timezone_str: str,
                                include_ids: bool = False) -> str:
    """Formats a list of events into a readable string for the agent/user."""
    if not events:
        return f"No events found for '{time_period_str}'."

    try:
        user_tz = pytz.timezone(user_timezone_str)
    except UnknownTimeZoneError:
        user_tz = pytz.utc

    output_lines = [f"🗓️ Events for {time_period_str} (Times in {user_timezone_str}):\n"]  # Add newline
    current_day_str = None

    # Sort events just in case (API usually returns sorted)
    events.sort(key=lambda e: e.get('start', {}).get('dateTime', e.get('start', {}).get('date', '')))

    for event in events:
        summary = event.get('summary', 'No Title')
        location = event.get('location')
        event_id = event.get('id')  # Keep ID for search results

        time_info = parse_and_format_event_time(event, user_tz)

        if not time_info:
            # Handle parsing error for this specific event
            start_str = event.get('start', {}).get('dateTime', event.get('start', {}).get('date', '[No Start]'))
            output_lines.append(f"- **{summary}** (Time Error: {start_str})")
            continue

        # --- Group by Day ---
        day_str = time_info['start_dt'].strftime('%a, %b %d, %Y')
        if day_str != current_day_str:
            output_lines.append(f"\n--- {day_str} ---")  # Add separator
            current_day_str = day_str

        # --- Format Event Line ---
        line = f"- **{summary}**"  # Bold summary
        line += f"\n  ⏰ {time_info['time_str']}"  # Time info
        if time_info['duration_str'] and not time_info['is_all_day']:
            line += f" ({time_info['duration_str']})"  # Add duration
            # Location with Google Maps Link
        if location:
            # URL Encode the location string for the query parameter
            encoded_location = urllib.parse.quote_plus(location)
            maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_location}"
            # Create HTML link
            line += f'\n  📍 <a href="{maps_url}">{location}</a>'
        # Add ID only if needed (e.g., for search results)
        # Optional Event ID
        if include_ids and event_id:
            line += f"\n  🆔 <code>{event_id}</code>"  # Use HTML code tag

        output_lines.append(line)

        # Check if output_lines only contains the initial header
        if len(output_lines) <= 1:
            logger.warning(f"Event formatting resulted in no event lines being added. Initial header: {output_lines}")
            # Return the "No events found" message instead of just the header
            return f"No events found {time_period_str} (or failed to format events)."

    # Join lines, ensuring proper spacing after day separators
    formatted_output = ""
    for i, line in enumerate(output_lines):
        if line.startswith("---") and i > 1 and not output_lines[i - 1].strip() == "":
            formatted_output += "\n"  # Add extra newline before date separator
        formatted_output += line + "\n"

    return formatted_output.strip()

