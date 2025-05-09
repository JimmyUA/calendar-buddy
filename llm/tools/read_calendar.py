import logging
from datetime import datetime

import pytz  # For timezone handling
from pytz.exceptions import UnknownTimeZoneError

import google_services as gs
from llm import llm_service
from llm.tools.calendar_base import CalendarBaseTool
from llm.tools.formatting import format_event_list_for_agent

logger = logging.getLogger(__name__)


class ReadCalendarEventsTool(CalendarBaseTool):
    name: str = "read_calendar_events"
    description: str = ("Input is a natural language time period (e.g., 'today', 'next week'). Fetches events from the "
                        "user's calendar for that period.")

    # args_schema: Type[BaseModel] = CalendarReadInput # Removed schema

    async def _arun(self, time_period: str) -> str:  # Takes NL string
        """Use the tool asynchronously."""
        logger.info(f"Tool: ReadCalendarEvents: User={self.user_id}, Period='{time_period}'")
        if not self.user_id: return "Error: User context missing."
        if not time_period: time_period = "today"  # Default if empty

        # 1. Get user's current time for LLM context
        try:
            user_tz = pytz.timezone(self.user_timezone_str)
        except UnknownTimeZoneError:
            user_tz = pytz.utc
        now_local_iso = datetime.now(user_tz).isoformat()

        # 2. Call LLM to extract structured date arguments
        parsed_args = await llm_service.extract_read_args_llm(time_period, now_local_iso)
        if not parsed_args: return f"Error: Could not understand the time period '{time_period}' from LLM."

        start_iso = parsed_args['start_iso']
        end_iso = parsed_args['end_iso']

        # 3. Fetch events using structured args
        events = await gs.get_calendar_events(self.user_id, time_min_iso=start_iso, time_max_iso=end_iso)

        # 4. Format response (remains similar)
        if events is None:
            return "Error: Could not fetch calendar events."
        elif not events:
            return f"No events found for '{time_period}'."
        else:
            # ---> Use new formatter, include_ids=False <---
            return format_event_list_for_agent(
                events,
                f"for '{time_period}'",  # Context description
                self.user_timezone_str,
                include_ids=False  # Don't show IDs for general read
            )
