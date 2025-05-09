import logging
from datetime import datetime

import pytz  # For timezone handling
from dateutil import parser as dateutil_parser
from pytz.exceptions import UnknownTimeZoneError

import config
from llm import llm_service
from llm.tools.calendar_base import CalendarBaseTool

logger = logging.getLogger(__name__)


class CreateCalendarEventTool(CalendarBaseTool):
    name: str = "create_calendar_event"
    description: str = ("Input is a natural language description of the event to create (e.g., 'Meeting with Bob "
                        "tomorrow 3pm about project X'). Prepares the event and asks the user for confirmation before "
                        "actually creating it.")

    # No args_schema needed if taking simple string

    async def _arun(self, event_description: str) -> str:
        """Prepares event, stores pending data, returns confirmation string."""
        logger.info(f"Tool: CreateCalendarEvent Prep: User={self.user_id}, Desc='{event_description[:50]}...'")
        if not self.user_id: return "Error: User context missing."
        if not event_description: return "Error: Event description needed."

        try:
            user_tz = pytz.timezone(self.user_timezone_str)
        except UnknownTimeZoneError:
            user_tz = pytz.utc
        now_local_iso = datetime.now(user_tz).isoformat()

        # 1. Call LLM to extract structured event data dictionary
        event_data = await llm_service.extract_create_args_llm(event_description, now_local_iso, self.user_timezone_str)
        if not event_data: return f"Error: Could not extract valid event details from '{event_description}'. Please provide more specific information like date and time."

        # 2. Format user-friendly confirmation string
        try:
            summary = event_data.get('summary', 'N/A')
            start_str = event_data.get('start', {}).get('dateTime')
            end_str = event_data.get('end', {}).get('dateTime')
            if not start_str or not end_str: raise ValueError("Missing start/end dateTime from LLM")

            # Format times in user's local timezone for confirmation message
            start_dt_local = dateutil_parser.isoparse(start_str).astimezone(user_tz)
            end_dt_local = dateutil_parser.isoparse(end_str).astimezone(user_tz)
            start_confirm = start_dt_local.strftime('%a, %b %d, %Y at %I:%M %p %Z')
            end_confirm = end_dt_local.strftime('%a, %b %d, %Y at %I:%M %p %Z')

            confirmation_string = (
                f"Okay, I can create this event:\n"
                f"Summary: {summary}\n"
                f"Start: {start_confirm}\n"
                f"End: {end_confirm}\n"
                f"Description: {event_data.get('description', '-')}\n"
                f"Location: {event_data.get('location', '-')}\n\n"
                f"Should I add this to your calendar?"
            )
        except Exception as e:
            logger.error(f"Error formatting create confirmation: {e}", exc_info=True)
            return "Error: Could not process the extracted event details for confirmation."

        # 3. Store pending action data (the structured data needed by Google API)
        config.pending_events[self.user_id] = event_data
        # Clear any pending delete for the same user
        if self.user_id in config.pending_deletions: del config.pending_deletions[self.user_id]

        # 4. Return the confirmation string to the agent
        return confirmation_string
