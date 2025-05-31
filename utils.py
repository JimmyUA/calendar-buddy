# utils.py
import logging
from datetime import datetime, timedelta, timezone
import pytz
from pytz.exceptions import UnknownTimeZoneError
from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

def _format_event_time(event: dict, user_tz: pytz.BaseTzInfo) -> str:
    """Formats event start/end time nicely for display in user's timezone."""
    start_data = event.get('start', {})
    end_data = event.get('end', {})
    start_str = start_data.get('dateTime', start_data.get('date'))
    end_str = end_data.get('dateTime', end_data.get('date'))

    if not start_str:
        logger.warning(f"Event missing start date/time info. Event ID: {event.get('id')}")
        return "[Unknown Start Time]"

    try:
        if 'date' in start_data: # All day event
            end_dt_str = end_data.get('date')
            start_dt = dateutil_parser.isoparse(start_str).date()
            if end_dt_str:
                end_dt = dateutil_parser.isoparse(end_dt_str).date() - timedelta(days=1)
                if end_dt > start_dt: # Multi-day
                    return f"{start_dt.strftime('%a, %b %d')} - {end_dt.strftime('%a, %b %d')} (All day)"
            return f"{start_dt.strftime('%a, %b %d')} (All day)" # Single day
        else: # Timed event
             if not end_str: end_str = start_str # Fallback if end missing

             start_dt_aware = dateutil_parser.isoparse(start_str).astimezone(user_tz)
             end_dt_aware = dateutil_parser.isoparse(end_str).astimezone(user_tz)

             start_fmt = start_dt_aware.strftime('%a, %b %d, %Y at %I:%M %p %Z')
             end_fmt = end_dt_aware.strftime('%I:%M %p %Z')
             if start_dt_aware.date() != end_dt_aware.date():
                 end_fmt = end_dt_aware.strftime('%b %d, %Y %I:%M %p %Z')
             return f"{start_fmt} - {end_fmt}"
    except Exception as e:
        logger.error(f"Error parsing/formatting event time: {e}. Event ID: {event.get('id')}, Start: '{start_str}', End: '{end_str}'", exc_info=True)
        return f"{start_str} [Error Formatting]"

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!' # Corrected: removed 煖 and ensured - is present
    # In MarkdownV2, reserved characters are: _ * [ ] ( ) ~ ` > # + - = | { } . !
    # All of these characters must be escaped with a preceding '\' character.
    for char_to_escape in escape_chars:
        if char_to_escape == '*':
            text = text.replace(char_to_escape, '[ASTERISK_LITERAL]') # Temporarily neutralize asterisks
        else:
            text = text.replace(char_to_escape, '\\' + char_to_escape)
    return text

# Add any other general utility functions here later