import logging
from datetime import datetime

import pytz
from pytz.exceptions import UnknownTimeZoneError

import google_services as gs
from llm import llm_service
from llm.tools.calendar_base import CalendarBaseTool
from llm.tools.delete_calendar import DeleteCalendarEventTool
from llm.tools.formatting import format_event_list_for_agent

logger = logging.getLogger(__name__)


class DeleteCalendarEventByQueryTool(CalendarBaseTool):
    """Searches for an event using a natural language query and prepares it for deletion."""

    name: str = "delete_calendar_event_by_query"
    description: str = (
        "Input is a natural language description of the event to delete. "
        "Searches for matching events and, if exactly one match is found, "
        "asks the user for confirmation to delete it. If multiple matches are "
        "found, returns the list with event IDs."
    )

    async def _arun(self, search_query: str) -> str:
        logger.info(
            f"Tool: DeleteCalendarEventByQuery: User={self.user_id}, Query='{search_query}'"
        )
        if not self.user_id:
            return "Error: User context missing."
        if not search_query:
            return "Error: Search query cannot be empty."

        try:
            user_tz = pytz.timezone(self.user_timezone_str)
        except UnknownTimeZoneError:
            user_tz = pytz.utc
        now_local_iso = datetime.now(user_tz).isoformat()

        parsed_args = await llm_service.extract_search_args_llm(search_query, now_local_iso)
        if not parsed_args:
            return f"Error: Could not understand search query '{search_query}'."

        query = parsed_args["query"]
        start_iso = parsed_args["start_iso"]
        end_iso = parsed_args["end_iso"]

        events = await gs.search_calendar_events(
            self.user_id,
            query=query,
            time_min_iso=start_iso,
            time_max_iso=end_iso,
            max_results=5,
        )
        if events is None:
            return "Error: Could not search calendar events."
        if not events:
            return f"No events found matching '{query}'."

        if len(events) > 1:
            formatted = format_event_list_for_agent(
                events, f"matching '{query}'", self.user_timezone_str, include_ids=True
            )
            return (
                "Multiple events found. Please specify the ID of the event to delete:\n\n"
                + formatted
            )

        event_id = events[0].get("id")
        if not event_id:
            return "Error: Event ID missing."

        del_tool = DeleteCalendarEventTool(
            user_id=self.user_id, user_timezone_str=self.user_timezone_str
        )
        return await del_tool._arun(event_id)
