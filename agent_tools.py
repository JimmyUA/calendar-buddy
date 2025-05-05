# agent_tools.py
import logging
import urllib.parse  # <--- IMPORT URL encoding
from datetime import datetime

import pytz  # For timezone handling
from dateutil import parser as dateutil_parser
from langchain.tools import BaseTool  # Use BaseTool for async/context
from pytz.exceptions import UnknownTimeZoneError

import config  # Need access to pending_actions
import google_services as gs
import llm_service
from handlers import parse_and_format_event_time
from utils import _format_event_time

logger = logging.getLogger(__name__)


# --- NEW Formatting Function ---
def format_event_list_for_agent(events: list, time_period_str: str, user_timezone_str: str,
                                include_ids: bool = False) -> str:
    """Formats a list of events into a readable string for the agent/user."""
    if not events:
        return f"No events found for '{time_period_str}'."

    try:
        user_tz = pytz.timezone(user_timezone_str)
    except UnknownTimeZoneError:
        user_tz = pytz.utc

    output_lines = [f"🗓️ Events for {time_period_str} (Times in {user_timezone_str}):\n"]  # Add newline
    current_day_str = None

    # Sort events just in case (API usually returns sorted)
    events.sort(key=lambda e: e.get('start', {}).get('dateTime', e.get('start', {}).get('date', '')))

    for event in events:
        summary = event.get('summary', 'No Title')
        location = event.get('location')
        event_id = event.get('id')  # Keep ID for search results

        time_info = parse_and_format_event_time(event, user_tz)

        if not time_info:
            # Handle parsing error for this specific event
            start_str = event.get('start', {}).get('dateTime', event.get('start', {}).get('date', '[No Start]'))
            output_lines.append(f"- **{summary}** (Time Error: {start_str})")
            continue

        # --- Group by Day ---
        day_str = time_info['start_dt'].strftime('%a, %b %d, %Y')
        if day_str != current_day_str:
            output_lines.append(f"\n--- {day_str} ---")  # Add separator
            current_day_str = day_str

        # --- Format Event Line ---
        line = f"- **{summary}**"  # Bold summary
        line += f"\n  ⏰ {time_info['time_str']}"  # Time info
        if time_info['duration_str'] and not time_info['is_all_day']:
            line += f" ({time_info['duration_str']})"  # Add duration
            # Location with Google Maps Link
        if location:
            # URL Encode the location string for the query parameter
            encoded_location = urllib.parse.quote_plus(location)
            maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_location}"
            # Create HTML link
            line += f'\n  📍 <a href="{maps_url}">{location}</a>'
        # Add ID only if needed (e.g., for search results)
        # Optional Event ID
        if include_ids and event_id:
            line += f"\n  🆔 <code>{event_id}</code>"  # Use HTML code tag

        output_lines.append(line)

    # Join lines, ensuring proper spacing after day separators
    formatted_output = ""
    for i, line in enumerate(output_lines):
        if line.startswith("---") and i > 1 and not output_lines[i - 1].strip() == "":
            formatted_output += "\n"  # Add extra newline before date separator
        formatted_output += line + "\n"


# === Custom Base Tool with User Context ===
# Needed to pass user_id and user_tz to the underlying google_services functions

class CalendarBaseTool(BaseTool):
    user_id: int
    user_timezone_str: str  # IANA timezone string

    def _run(self, *args, **kwargs): raise NotImplementedError("Sync execution not supported")


# === Tool Definitions ===

class ReadCalendarEventsTool(CalendarBaseTool):
    name: str = "read_calendar_events"
    description: str = "Input is a natural language time period (e.g., 'today', 'next week'). Fetches events from the user's calendar for that period."

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


class SearchCalendarEventsTool(CalendarBaseTool):
    name: str = "search_calendar_events"
    description: str = "Input is a natural language search query, potentially including a time period (e.g., 'project alpha meeting next month'). Searches events based on keywords. Returns event summaries, times, and IDs."

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


class CreateCalendarEventTool(CalendarBaseTool):
    name: str = "create_calendar_event"
    description: str = "Input is a natural language description of the event to create (e.g., 'Meeting with Bob tomorrow 3pm about project X'). Prepares the event and asks the user for confirmation before actually creating it."

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


class DeleteCalendarEventTool(CalendarBaseTool):
    name: str = "delete_calendar_event"
    description: str = "Input is the specific Google Calendar event ID string. Prepares to delete the event with that ID and asks the user for confirmation."

    # args_schema: Type[BaseModel] = CalendarDeleteInput # If using Pydantic

    async def _arun(self, event_id: str) -> str:  # Takes ONLY event_id
        """Fetches event summary, stores pending delete, returns confirmation string."""
        logger.info(f"Tool: DeleteCalendarEvent Prep: User={self.user_id}, ID='{event_id}'")
        if not self.user_id: return "Error: User context missing."
        if not event_id or not isinstance(event_id, str) or len(event_id) < 5:
            return "Error: A valid event ID is required. Use search_calendar_events first if you don't have the ID."

        # 1. Fetch event details to get summary for confirmation
        event_details = await gs.get_calendar_event_by_id(self.user_id, event_id)
        if not event_details:
            return f"Error: Could not find event with ID '{event_id}'. It might be incorrect or already deleted."

        event_summary = event_details.get('summary', 'No Title')

        # 2. Format confirmation string
        try:
            user_tz = pytz.timezone(self.user_timezone_str)
            time_confirm = _format_event_time(event_details, user_tz)
        except Exception:
            time_confirm = "[Could not format time]"
        confirmation_string = f"Found event: '{event_summary}' ({time_confirm}).\n\nShould I delete this event?"

        # 3. Store pending action data
        config.pending_deletions[self.user_id] = {'event_id': event_id, 'summary': event_summary}
        if self.user_id in config.pending_events: del config.pending_events[self.user_id]  # Clear other pending action

        # 4. Return confirmation string
        return confirmation_string


class GetCurrentTimeTool(CalendarBaseTool):
    name: str = "get_current_datetime"
    # Static description - doesn't mention specific user TZ here
    description: str = (
        "Returns the current date and time based on the user's configured timezone settings. "
        "Use this when you need the precise current time to understand relative requests "
        "like 'in 2 hours', 'later today', or to calculate future dates."
    )

    async def _arun(self, *args, **kwargs) -> str:  # Accept and ignore extra args
        """Use the tool asynchronously."""
        logger.info(f"Tool: GetCurrentTimeTool called by agent for user {self.user_id}")
        # self.user_timezone_str IS available here because this is an instance method
        try:
            user_tz = pytz.timezone(self.user_timezone_str)
        except UnknownTimeZoneError:
            logger.warning(
                f"GetCurrentTimeTool: Invalid timezone '{self.user_timezone_str}' for user {self.user_id}. Using UTC.")
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
