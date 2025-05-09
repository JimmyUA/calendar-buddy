import logging
from datetime import datetime

import pytz  # For timezone handling
from pytz.exceptions import UnknownTimeZoneError

import google_services as gs
from llm import llm_service
from llm.tools.calendar_base import CalendarBaseTool
from llm.tools.formatting import format_event_list_for_agent

logger = logging.getLogger(__name__)


class SearchCalendarEventsTool(CalendarBaseTool):
    name: str = "search_calendar_events"
    description: str = ("Input is a natural language search query, potentially including a time period (e.g., "
                        "'project alpha meeting next month'). Searches events based on keywords. Returns event "
                        "summaries, times, and IDs.")

    # args_schema: Type[BaseModel] = CalendarSearchInput # Removed schema

    async def _arun(self, search_query: str) -> str:  # Takes NL string
        """Use the tool asynchronously."""
        logger.info(f"Tool: SearchCalendarEvents: User={self.user_id}, Query='{search_query}'")
        if not self.user_id: return "Error: User context missing."
        if not search_query: return "Error: Search query cannot be empty."

        # 1. Get user's current time for LLM context
        try:
            user_tz = pytz.timezone(self.user_timezone_str)
        except UnknownTimeZoneError:
            user_tz = pytz.utc
        now_local_iso = datetime.now(user_tz).isoformat()

        # 2. Call LLM to extract structured search arguments
        parsed_args = await llm_service.extract_search_args_llm(search_query, now_local_iso)
        if not parsed_args: return f"Error: Could not understand search query details for '{search_query}' from LLM."

        query = parsed_args['query']
        start_iso = parsed_args['start_iso']
        end_iso = parsed_args['end_iso']

        # 3. Search events using structured args
        events = await gs.search_calendar_events(self.user_id, query=query, time_min_iso=start_iso,
                                                 time_max_iso=end_iso)

        # 4. Format response (remains similar)
        if events is None:
            return "Error: Could not search calendar events."
        elif not events:
            return f"No events found matching '{query}' in the specified period."
        else:
            # ---> Use new formatter, include_ids=True <---
            return format_event_list_for_agent(
                events,
                f"matching '{query}'",  # Context description
                self.user_timezone_str,
                include_ids=True  # SHOW IDs for search results
            )
