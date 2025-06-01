import html
# Assuming time_util.py is in the root directory and Python's import system can find it.
# If handler is a package, a relative import like `from .. import time_util` might be needed,
# but based on the current structure, `import time_util` should work if /app is in PYTHONPATH.
import time_util

def format_daily_summary(events: list, user_timezone_str: str) -> str:
    """
    Formats a list of events into a daily summary message.
    """
    if not events:
        return "Looks like there are no events scheduled for tomorrow!"

    message_parts = ["📅 <b>Events for Tomorrow</b> 📅\n"]
    for event in events:
        summary = html.escape(event.get('summary', 'No Title'))
        # The event.get('start') and event.get('end') can be dicts or ISO strings
        start_time_obj = event.get('start')
        end_time_obj = event.get('end')

        start_time_str = time_util.format_to_nice_date(start_time_obj, user_timezone_str)
        end_time_str = time_util.format_to_nice_date(end_time_obj, user_timezone_str)

        location = html.escape(event.get('location', ''))
        description = html.escape(event.get('description', ''))

        event_str = f"✨ <b>{summary}</b>\n"
        event_str += f"    <i>Start:</i> {start_time_str}\n"
        event_str += f"    <i>End:</i>   {end_time_str}\n"
        if location:
            event_str += f"    <i>Where:</i> {location}\n"
        if description:
            # Show first 50 chars of description as a snippet
            desc_snippet = description[:50] + "..." if len(description) > 50 else description
            event_str += f"    <i>About:</i> {desc_snippet}\n"

        message_parts.append(event_str)

    return "\n".join(message_parts)

def format_weekly_summary(events: list, user_timezone_str: str) -> str:
    """
    Formats a list of events into a weekly summary message.
    """
    if not events:
        return "Looks like there are no events scheduled for next week!"

    message_parts = ["🗓️ <b>Upcoming Events Next Week</b> 🗓️\n"]

    for event in events:
        summary = html.escape(event.get('summary', 'No Title'))
        # The event.get('start') and event.get('end') can be dicts or ISO strings
        start_time_obj = event.get('start')
        end_time_obj = event.get('end')

        start_time_str = time_util.format_to_nice_date(start_time_obj, user_timezone_str)
        end_time_str = time_util.format_to_nice_date(end_time_obj, user_timezone_str)

        location = html.escape(event.get('location', ''))
        description = html.escape(event.get('description', ''))

        event_str = f"✨ <b>{summary}</b>\n"
        # Date is already part of start_time_str from format_to_nice_date
        event_str += f"    <i>Start:</i> {start_time_str}\n"
        event_str += f"    <i>End:</i>   {end_time_str}\n"
        if location:
            event_str += f"    <i>Where:</i> {location}\n"
        if description:
            desc_snippet = description[:50] + "..." if len(description) > 50 else description
            event_str += f"    <i>About:</i> {desc_snippet}\n"

        message_parts.append(event_str)

    return "\n".join(message_parts)
