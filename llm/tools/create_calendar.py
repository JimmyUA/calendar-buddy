import logging
from datetime import datetime

import pytz  # For timezone handling
from dateutil import parser as dateutil_parser
from pytz.exceptions import UnknownTimeZoneError

import config
from llm import llm_service
from llm.tools.calendar_base import CalendarBaseTool
import json

logger = logging.getLogger(__name__)


class CreateCalendarEventTool(CalendarBaseTool):
    name: str = "create_calendar_event"
    description: str = (
        "Input is a natural language description of the event to create (e.g., 'Meeting with Bob "
        "tomorrow 3pm about project X'). Prepares the event and returns a detailed confirmation question "
        "along with structured event data for final creation by the user."
    )

    # No args_schema needed if taking simple string

    async def _arun(self, event_description: str) -> str:
        """
        Prepares event, formats a detailed confirmation, and returns structured JSON output
        containing the confirmation question and event data.
        """
        logger.info(f"Tool: CreateCalendarEvent Prep: User={self.user_id}, Desc='{event_description[:50]}...'")
        if not self.user_id: return json.dumps({"error": "User context missing."})
        if not event_description: return json.dumps({"error": "Event description needed."})

        try:
            user_tz = pytz.timezone(self.user_timezone_str)
        except UnknownTimeZoneError:
            logger.warning(f"CreateTool: Invalid user_timezone_str '{self.user_timezone_str}'. Using UTC.")
            user_tz = pytz.utc
        now_local_iso = datetime.now(user_tz).isoformat()

        # 1. Call LLM to extract structured event data dictionary
        event_data = await llm_service.extract_create_args_llm(event_description, now_local_iso, self.user_timezone_str)
        if not event_data:
            return json.dumps({
                                  "error": f"Could not extract valid event details from '{event_description}'. Please provide more specific information like date and time."})

        # 2. Format user-friendly and DETAILED confirmation string
        try:
            summary = event_data.get('summary', 'N/A')
            start_info = event_data.get('start', {})
            end_info = event_data.get('end', {})
            start_str = start_info.get('dateTime')
            end_str = end_info.get('dateTime')

            if not start_str or not end_str:
                logger.error(f"CreateTool: LLM did not return valid start/end dateTime: {event_data}")
                return json.dumps({"error": "Could not determine the event's start or end time from your description."})

            # Parse and format times in user's local timezone for the confirmation message
            start_dt_local = dateutil_parser.isoparse(start_str).astimezone(user_tz)
            end_dt_local = dateutil_parser.isoparse(end_str).astimezone(user_tz)

            start_confirm = start_dt_local.strftime('%a, %b %d, %Y at %I:%M %p %Z')
            end_confirm = end_dt_local.strftime('%a, %b %d, %Y at %I:%M %p %Z')

            description_confirm = event_data.get('description', '-')
            location_confirm = event_data.get('location', '-')

            # Construct the detailed confirmation question using HTML for Telegram
            confirmation_question = (
                f"Okay, I can create this event:\n\n"
                f"<b>Summary:</b> {summary}\n"
                f"<b>Start:</b> {start_confirm}\n"
                f"<b>End:</b> {end_confirm}\n"
                f"<b>Description:</b> {description_confirm}\n"
                f"<b>Location:</b> {location_confirm}\n\n"
                f"Should I add this to your calendar?"
            )
        except Exception as e:
            logger.error(f"Error formatting create confirmation for user {self.user_id}: {e}", exc_info=True)
            return json.dumps({"error": "Could not process the extracted event details for confirmation."})

        # 3. Prepare structured output for the handler
        output_data = {
            "action": "confirm_create",
            "confirmation_question": confirmation_question,  # This now includes all details
            "event_data": event_data  # The dict needed by gs.create_calendar_event
        }

        # 4. Return the data as a JSON string
        try:
            json_output = json.dumps(output_data)
            logger.info(f"CreateTool: Returning detailed confirmation data for event '{summary}'")
            return json_output
        except Exception as e:
            logger.error(f"CreateTool: Failed to serialize output data to JSON: {e}")
            return json.dumps({"error": "Internal error preparing creation confirmation."})
