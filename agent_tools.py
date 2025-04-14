# agent_tools.py
import logging
from datetime import datetime, timezone, timedelta
from typing import Type
from pydantic.v1 import BaseModel, Field # Use v1 pydantic for Langchain tool compatibility

from langchain.tools import BaseTool # Use BaseTool for async/context
from dateutil import parser as dateutil_parser

import google_services as gs
import pytz # For timezone handling
from pytz.exceptions import UnknownTimeZoneError

import llm_service

logger = logging.getLogger(__name__)

# === Custom Base Tool with User Context ===
# Needed to pass user_id and user_tz to the underlying google_services functions

class CalendarBaseTool(BaseTool):
    user_id: int
    user_timezone_str: str # IANA timezone string

    def _run(self, *args, **kwargs): raise NotImplementedError("Sync execution not supported")


# === Tool Definitions ===

class ReadCalendarEventsTool(CalendarBaseTool):
    name: str = "read_calendar_events"
    description: str = "Input is a natural language time period (e.g., 'today', 'next week'). Fetches events from the user's calendar for that period."
    # args_schema: Type[BaseModel] = CalendarReadInput # Removed schema

    async def _arun(self, time_period: str) -> str: # Takes NL string
        """Use the tool asynchronously."""
        logger.info(f"Tool: ReadCalendarEvents: User={self.user_id}, Period='{time_period}'")
        if not self.user_id: return "Error: User context missing."
        if not time_period: time_period = "today" # Default if empty

        # 1. Get user's current time for LLM context
        try: user_tz = pytz.timezone(self.user_timezone_str)
        except UnknownTimeZoneError: user_tz = pytz.utc
        now_local_iso = datetime.now(user_tz).isoformat()

        # 2. Call LLM to extract structured date arguments
        parsed_args = await llm_service.extract_read_args_llm(time_period, now_local_iso)
        if not parsed_args: return f"Error: Could not understand the time period '{time_period}' from LLM."

        start_iso = parsed_args['start_iso']
        end_iso = parsed_args['end_iso']

        # 3. Fetch events using structured args
        events = await gs.get_calendar_events(self.user_id, time_min_iso=start_iso, time_max_iso=end_iso)

        # 4. Format response (remains similar)
        if events is None: return "Error: Could not fetch calendar events."
        elif not events: return f"No events found for '{time_period}'."
        else:
            summary_lines = [f"Events for {time_period} (Times in {self.user_timezone_str}):"]
            # ... (Loop and formatting logic using _format_event_time or similar) ...
            for event in events:
                 try: # Inline formatting for simplicity
                    time_str = ""
                    start_data=event.get('start',{}); end_data=event.get('end',{})
                    start_str = start_data.get('dateTime', start_data.get('date'))
                    if not start_str: continue
                    if 'date' in start_data: start_dt = dateutil_parser.isoparse(start_str).date(); time_str = f"{start_dt.strftime('%a, %b %d')} (All day)"
                    else: start_dt = dateutil_parser.isoparse(start_str).astimezone(user_tz); end_dt = dateutil_parser.isoparse(end_data.get('dateTime', start_str)).astimezone(user_tz); start_fmt = start_dt.strftime('%a, %b %d %I:%M %p %Z'); end_fmt = end_dt.strftime('%I:%M %p %Z'); time_str = f"{start_fmt} - {end_fmt}"
                 except Exception: time_str = f"Raw: {start_str} [Fmt Err]"
                 summary_lines.append(f"- {event.get('summary', 'No Title')} ({time_str})")
            return "\n".join(summary_lines)

class SearchCalendarEventsTool(CalendarBaseTool):
    name: str = "search_calendar_events"
    description: str = "Input is a natural language search query, potentially including a time period (e.g., 'project alpha meeting next month'). Searches events based on keywords. Returns event summaries, times, and IDs."
    # args_schema: Type[BaseModel] = CalendarSearchInput # Removed schema

    async def _arun(self, search_query: str) -> str: # Takes NL string
        """Use the tool asynchronously."""
        logger.info(f"Tool: SearchCalendarEvents: User={self.user_id}, Query='{search_query}'")
        if not self.user_id: return "Error: User context missing."
        if not search_query: return "Error: Search query cannot be empty."

        # 1. Get user's current time for LLM context
        try: user_tz = pytz.timezone(self.user_timezone_str)
        except UnknownTimeZoneError: user_tz = pytz.utc
        now_local_iso = datetime.now(user_tz).isoformat()

        # 2. Call LLM to extract structured search arguments
        parsed_args = await llm_service.extract_search_args_llm(search_query, now_local_iso)
        if not parsed_args: return f"Error: Could not understand search query details for '{search_query}' from LLM."

        query = parsed_args['query']
        start_iso = parsed_args['start_iso']
        end_iso = parsed_args['end_iso']

        # 3. Search events using structured args
        events = await gs.search_calendar_events(self.user_id, query=query, time_min_iso=start_iso, time_max_iso=end_iso)

        # 4. Format response (remains similar)
        if events is None: return "Error: Could not search calendar events."
        elif not events: return f"No events found matching '{query}' in the specified period."
        else:
            results = [f"Found {len(events)} matching events for '{query}':"]
            # ... (Loop and formatting logic, including event ID) ...
            for event in events:
                time_str = "Unknown Time"
                try: # Inline formatting
                    start_data=event.get('start',{}); start_str = start_data.get('dateTime', start_data.get('date'))
                    if not start_str: continue
                    if 'date' in start_data: time_str = dateutil_parser.isoparse(start_str).strftime('%Y-%m-%d (All day)')
                    else: time_str = dateutil_parser.isoparse(start_str).astimezone(user_tz).strftime('%a, %b %d %I:%M%p %Z')
                except Exception: pass
                results.append(f"- Summary: {event.get('summary', 'No Title')}, Time: {time_str}, ID: {event.get('id')}")
            return "\n".join(results)

class CreateCalendarEventTool(CalendarBaseTool):
    name: str = "create_calendar_event"
    description: str = "Input is a natural language description of the event to create (e.g., 'Meeting with Bob tomorrow 3pm about project X'). Creates the event in the user's calendar."
    # args_schema: Type[BaseModel] = CalendarCreateInput # Removed schema

    async def _arun(self, event_description: str) -> str: # Takes NL string
        """Use the tool asynchronously."""
        logger.info(f"Tool: CreateCalendarEvent: User={self.user_id}, Desc='{event_description[:50]}...'")
        if not self.user_id: return "Error: User context missing."
        if not event_description: return "Error: Event description cannot be empty."

        # 1. Get user's current time for LLM context
        try: user_tz = pytz.timezone(self.user_timezone_str)
        except UnknownTimeZoneError: user_tz = pytz.utc
        now_local_iso = datetime.now(user_tz).isoformat()

        # 2. Call LLM to extract structured event data dictionary
        event_data = await llm_service.extract_create_args_llm(event_description, now_local_iso, self.user_timezone_str)
        if not event_data: return f"Error: Could not extract valid event details from '{event_description}' using LLM."

        # 3. Create event using structured data
        # Note: Confirmation step is removed here. The agent might need to be prompted
        # differently if confirmation before creation is desired.
        success, message, link = await gs.create_calendar_event(self.user_id, event_data)

        return message + (f" Link: {link}" if link else "")
class DeleteCalendarEventTool(CalendarBaseTool):
    name: str = "delete_calendar_event"
    description: str = "Input is the specific Google Calendar event ID string. Deletes the event with that ID. Use 'search_calendar_events' first to find the correct ID."
    # args_schema: Type[BaseModel] = CalendarDeleteInput # Removed schema

    async def _arun(self, event_id: str) -> str: # Takes event ID string
        """Use the tool asynchronously."""
        logger.info(f"Tool: DeleteCalendarEvent: User={self.user_id}, ID='{event_id}'")
        if not self.user_id: return "Error: User context missing."
        if not event_id or not isinstance(event_id, str) or len(event_id) < 5: # Basic ID validation
            return "Error: A valid event ID is required. Please use the search tool first to find the ID."

        # Note: Confirmation step removed. Agent should confirm before calling if needed.
        success, message = await gs.delete_calendar_event(self.user_id, event_id)
        return message

class GetCurrentTimeTool(CalendarBaseTool):
    name: str = "get_current_datetime"
    # Static description - doesn't mention specific user TZ here
    description: str = (
        "Returns the current date and time based on the user's configured timezone settings. "
        "Use this when you need the precise current time to understand relative requests "
        "like 'in 2 hours', 'later today', or to calculate future dates."
    )

    async def _arun(self) -> str: # No specific args needed
        """Use the tool asynchronously."""
        logger.info(f"Tool: GetCurrentTimeTool called by agent for user {self.user_id}")
        # self.user_timezone_str IS available here because this is an instance method
        try:
            user_tz = pytz.timezone(self.user_timezone_str)
        except UnknownTimeZoneError:
            logger.warning(f"GetCurrentTimeTool: Invalid timezone '{self.user_timezone_str}' for user {self.user_id}. Using UTC.")
            user_tz = pytz.utc

        now_local = datetime.now(user_tz)
        iso_now = now_local.isoformat()
        human_readable_now = now_local.strftime('%Y-%m-%d %H:%M:%S %Z (%A)')
        # Return the actual current time in the user's specific TZ
        return f"Current date and time is: {human_readable_now} (ISO: {iso_now})"

def get_tools(user_id: int, user_timezone_str: str) -> list[BaseTool]:
    """Factory function to create tools with user context."""
    return [
        ReadCalendarEventsTool(user_id=user_id, user_timezone_str=user_timezone_str),
        SearchCalendarEventsTool(user_id=user_id, user_timezone_str=user_timezone_str),
        CreateCalendarEventTool(user_id=user_id, user_timezone_str=user_timezone_str),
        DeleteCalendarEventTool(user_id=user_id, user_timezone_str=user_timezone_str),
        GetCurrentTimeTool(user_id=user_id, user_timezone_str=user_timezone_str),  # Add the new tool
    ]