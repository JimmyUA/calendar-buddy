import logging
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta # For duration

# Timezone libraries
import pytz
from dateutil import parser as dateutil_parser

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

