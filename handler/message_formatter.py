import html

from time_util import format_to_nice_date


async def create_final_message(pending_event_data):
    """Format a pending event or list of events for user confirmation."""
    if isinstance(pending_event_data, list):
        lines = ["Okay, I can create these events:\n"]
        for idx, ev in enumerate(pending_event_data, 1):
            summary = html.escape(ev.get("summary", "N/A"))
            start_dt_iso = ev.get("start", {})
            end_dt_iso = ev.get("end", {})
            if not start_dt_iso:
                raise ValueError("Missing start dateTime in pending event")
            start_date_time = start_dt_iso.get("dateTime", "")
            end_date_time = end_dt_iso.get("dateTime", "")
            description_text = ev.get("description", "-") or "-"
            location_text = ev.get("location", "-") or "-"
            lines.extend(
                [
                    f"{idx}. <b>{summary}</b>",
                    f"   <i>{format_to_nice_date(start_date_time)} - {format_to_nice_date(end_date_time)}</i>",
                    f"   Desc: {html.escape(description_text)}",
                    f"   Loc: {html.escape(location_text)}",
                    "",
                ]
            )
        lines.append("Ready to add these to your Google Calendar?")
        return "\n".join(lines)

    summary = pending_event_data.get("summary", "N/A")
    start_dt_iso = pending_event_data.get("start", {})
    end_dt_iso = pending_event_data.get("end", {})
    if not start_dt_iso:
        raise ValueError("Missing start dateTime in pending event")

    start_date_time = start_dt_iso.get("dateTime", "")
    end_date_time = end_dt_iso.get("dateTime", "")
    escaped_summary = html.escape(summary)
    description_text = pending_event_data.get("description", "-")
    location_text = pending_event_data.get("location", "-")
    display_description = f"<i>{description_text if description_text else 'Not specified'}</i>"
    display_location = f"<i>{location_text if location_text else 'Not specified'}</i>"

    return (
        f"Okay, I can create this event for you:\n\n"
        f"✨ <b>{escaped_summary}</b> ✨\n\n"
        f"📅 <b><u>Event Details</u></b>\n"
        f"<b>Start:</b>       <code>{format_to_nice_date(start_date_time)}</code>\n"
        f"<b>End:</b>         <code>{format_to_nice_date(end_date_time)}</code>\n"
        f"<b>Description:</b> {display_description}\n"
        f"<b>Location:</b>    {display_location}\n\n"
        f"Ready to add this to your Google Calendar?"
    )
