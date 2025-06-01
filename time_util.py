import platform
from datetime import datetime, timedelta, time
import pytz


def get_next_day_range_iso(timezone_str: str) -> tuple[str, str]:
    """
    Calculates the start and end ISO strings for the next day in the given timezone.
    Start is tomorrow at 00:00:00.
    End is tomorrow at 23:59:59.999999.
    """
    try:
        user_tz = pytz.timezone(timezone_str)
    except pytz.exceptions.UnknownTimeZoneError:
        # Log or raise, or default to UTC. For now, let it raise to be caught by caller.
        raise

    now_in_timezone = datetime.now(user_tz)
    tomorrow_in_timezone = now_in_timezone + timedelta(days=1)

    start_of_next_day = tomorrow_in_timezone.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_next_day = tomorrow_in_timezone.replace(hour=23, minute=59, second=59, microsecond=999999)

    return start_of_next_day.isoformat(), end_of_next_day.isoformat()

def get_next_week_range_iso(timezone_str: str) -> tuple[str, str]:
    """
    Calculates the start and end ISO strings for the next week (Monday to Sunday)
    in the given timezone.
    Start is the upcoming Monday at 00:00:00.
    End is the following Sunday at 23:59:59.999999.
    """
    try:
        user_tz = pytz.timezone(timezone_str)
    except pytz.exceptions.UnknownTimeZoneError:
        raise

    now_in_timezone = datetime.now(user_tz)

    # Calculate days until next Monday
    # weekday() returns 0 for Monday, 1 for Tuesday, ..., 6 for Sunday
    days_until_monday = (0 - now_in_timezone.weekday() + 7) % 7
    if days_until_monday == 0 and now_in_timezone.time() >= time(20,0,0) : # If it's currently Sunday after 8 PM, get next week starting from the day after.
            days_until_monday = 7


    start_of_next_week = (now_in_timezone + timedelta(days=days_until_monday)).replace(hour=0, minute=0, second=0, microsecond=0)

    # End of next week is 6 days after the start of next week
    end_of_next_week = (start_of_next_week + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)

    return start_of_next_week.isoformat(), end_of_next_week.isoformat()


def format_to_nice_date(iso_date_string: str, user_timezone_str: str = "UTC") -> str:
    """
    Formats an ISO date string to a nice, human-readable format in the user's timezone.
    Example: "Mon, Jan 1, 2024, 10:00 AM (EST)"
    """
    if not iso_date_string:
        return "N/A"
    try:
        # Attempt to parse assuming it might be a dict like {'dateTime': '...', 'timeZone': '...'}
        # or a direct ISO string.
        if isinstance(iso_date_string, dict):
            iso_str = iso_date_string.get('dateTime', iso_date_string.get('date')) # Handle all-day events
            # Event specific timezone might be in iso_date_string.get('timeZone')
            # For simplicity, we'll use user_timezone_str for display for now.
        else:
            iso_str = iso_date_string

        if not iso_str: return "N/A"

        dt_obj = datetime.fromisoformat(iso_str.replace('Z', '+00:00')) # Handle 'Z' for UTC

        # If datetime object is timezone naive, assume it's UTC
        if dt_obj.tzinfo is None:
            dt_obj = pytz.utc.localize(dt_obj)

        try:
            target_tz = pytz.timezone(user_timezone_str)
        except pytz.exceptions.UnknownTimeZoneError:
            target_tz = pytz.utc # Default to UTC if user's timezone is invalid

        dt_in_user_tz = dt_obj.astimezone(target_tz)

        # Check if it's an all-day event (time is midnight)
        if dt_in_user_tz.time() == time(0, 0, 0) and isinstance(iso_date_string, dict) and 'date' in iso_date_string :
                return dt_in_user_tz.strftime('%a, %b %d, %Y (All-day)')
        else:
                return dt_in_user_tz.strftime('%a, %b %d, %Y, %I:%M %p (%Z)')
    except Exception as e:
        # logging.error(f"Error formatting date '{iso_date_string}': {e}", exc_info=True)
        return f"Invalid date ({iso_date_string})"