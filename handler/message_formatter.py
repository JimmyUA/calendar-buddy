import html

from time_util import format_to_nice_date


async def create_final_message(pending_event_data):
    summary = pending_event_data.get('summary', 'N/A')
    # Re-parse and format start/end times for confirmation display
    # This assumes start/end in pending_event_data are like {'dateTime': ISO, 'timeZone': IANA}
    start_dt_iso = pending_event_data.get('start', {})
    end_dt_iso = pending_event_data.get('end', {})
    if not start_dt_iso: raise ValueError("Missing start dateTime in pending event")
    # Construct the detailed confirmation message HERE
    start_date_time = start_dt_iso.get('dateTime', '')
    end_date_time = end_dt_iso.get('dateTime', '')
    escaped_summary = html.escape(summary)
    description_text = pending_event_data.get('description', '-')
    location_text = pending_event_data.get('location', '-')
    display_description = f"<i>{description_text if description_text else 'Not specified'}</i>"
    display_location = f"<i>{location_text if location_text else 'Not specified'}</i>"

    return (
        f"Okay, I can create this event for you:\n\n"
        f"✨ <b>{escaped_summary}</b> ✨\n\n"  # Emphasized Summary/Title
        f"📅 <b><u>Event Details</u></b>\n"
        f"<b>Start:</b>       <code>{format_to_nice_date(start_date_time)}</code>\n"
        f"<b>End:</b>         <code>{format_to_nice_date(end_date_time)}</code>\n"
        f"<b>Description:</b> {display_description}\n"
        f"<b>Location:</b>    {display_location}\n\n"
        f"Ready to add this to your Google Calendar?"
    )


async def create_delete_confirmation_message(event_details: dict) -> str:
    """Format a confirmation message for deleting an event."""

    summary = event_details.get("summary", "N/A")
    start_info = event_details.get("start", {})
    end_info = event_details.get("end", {})

    start_iso = start_info.get("dateTime") or start_info.get("date", "")
    end_iso = end_info.get("dateTime") or end_info.get("date", "")

    description_text = event_details.get("description", "") or "Not specified"
    location_text = event_details.get("location", "") or "Not specified"

    return (
        f"I found this event:\n\n"
        f"✨ <b>{html.escape(summary)}</b> ✨\n\n"
        f"📅 <b><u>Event Details</u></b>\n"
        f"<b>Start:</b>       <code>{format_to_nice_date(start_iso)}</code>\n"
        f"<b>End:</b>         <code>{format_to_nice_date(end_iso)}</code>\n"
        f"<b>Description:</b> <i>{html.escape(description_text)}</i>\n"
        f"<b>Location:</b>    <i>{html.escape(location_text)}</i>\n\n"
        "Should I delete this event?"
    )
