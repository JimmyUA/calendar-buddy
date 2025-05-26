import logging
from datetime import datetime, timedelta # Added timedelta
import pytz # For timezone handling
from dateutil import parser as dateutil_parser
from pytz.exceptions import UnknownTimeZoneError

import config
from llm import llm_service
from llm.tools.calendar_base import CalendarBaseTool
from google_services import get_calendar_event_by_id, search_calendar_events # Assuming these exist and are async

logger = logging.getLogger(__name__)

class UpdateCalendarEventTool(CalendarBaseTool):
    name: str = "update_calendar_event"
    description: str = (
        "Input is a natural language description of the event to update and the changes to make "
        "(e.g., 'Reschedule my meeting with Bob from 3pm to 4pm and change location to Main Hall', "
        "'Update the event "Project Sync" next Tuesday to start at 10am and add 'important' to description'). "
        "Identifies the event, extracts changes, and asks for user confirmation before applying them."
    )

    async def _arun(self, user_request: str) -> str:
        """Identifies event, extracts updates, stores pending data, returns confirmation string."""
        logger.info(f"Tool: UpdateCalendarEvent Prep: User={self.user_id}, Request='{user_request[:100]}...'")
        if not self.user_id:
            return "Error: User context missing for event update."
        if not user_request:
            return "Error: Please specify which event to update and how."

        try:
            user_tz = pytz.timezone(self.user_timezone_str)
        except UnknownTimeZoneError:
            logger.warning(f"Unknown timezone '{self.user_timezone_str}' for user {self.user_id}. Defaulting to UTC.")
            user_tz = pytz.utc
        now_local_iso = datetime.now(user_tz).isoformat()

        # 1. LLM call to extract:
        #    a) Search query/description of the event to find.
        #    b) The actual changes to be made (as a natural language string).
        #    c) Potentially a time frame for the search.
        # The actual prompt construction and LLM call are handled by llm_service
        parsed_search_and_changes = await llm_service.extract_update_search_and_changes(user_request, now_local_iso)
        if not parsed_search_and_changes or not parsed_search_and_changes.get("search_query") or not parsed_search_and_changes.get("changes_description"):
             return "Error: Could not understand which event to update or what changes to make from your request. Please be more specific."

        search_query = parsed_search_and_changes["search_query"]
        changes_description = parsed_search_and_changes["changes_description"]
        search_start_iso = parsed_search_and_changes.get("search_start_iso")
        search_end_iso = parsed_search_and_changes.get("search_end_iso")

        # 2. Search for potential events
        if not search_start_iso or not search_end_iso:
            search_start_dt = datetime.now(user_tz).replace(hour=0, minute=0, second=0, microsecond=0)
            search_end_dt = search_start_dt + timedelta(days=14)
            search_start_iso = search_start_dt.isoformat()
            search_end_iso = search_end_dt.isoformat()

        logger.info(f"Searching for events matching '{search_query}' between {search_start_iso} and {search_end_iso}")
        potential_events = await search_calendar_events(
            self.user_id,
            query=search_query,
            time_min_iso=search_start_iso,
            time_max_iso=search_end_iso,
            max_results=10
        )

        if potential_events is None:
            return "Error: Could not search your calendar. Please ensure it's connected and permissions are correct."
        if not potential_events:
            return f"Error: No events found matching your description '{search_query}'. Please try a different description or time frame."

        # 3. LLM call to select the best match from potential_events (if more than one)
        event_to_update_id = None
        original_event_details_for_confirm = None

        if len(potential_events) == 1:
            event_to_update_id = potential_events[0].get("id")
            original_event_details_for_confirm = await get_calendar_event_by_id(self.user_id, event_to_update_id)
            if not original_event_details_for_confirm:
                 logger.error(f"Could not fetch details for event ID {event_to_update_id} even after search.")
                 return "Error: Found a matching event but could not fetch its full details. Please try again."
        else: # len(potential_events) > 1 or len(potential_events) == 0 (already handled)
            logger.info(f"Asking LLM to match '{search_query}' against {len(potential_events)} candidates for update.")
            # Simplified: if multiple events, ask user to be more specific.
            # A real implementation would call:
            # match_result = await llm_service.find_event_match_llm(search_query, potential_events, "update")
            # if match_result and match_result.get('match_type') == 'SINGLE':
            #     event_index = match_result.get('event_index')
            #     event_to_update_id = potential_events[event_index].get("id")
            #     original_event_details_for_confirm = await get_calendar_event_by_id(self.user_id, event_to_update_id)
            #     if not original_event_details_for_confirm: # Should not happen if ID is valid
            #         return "Error: Matched event by LLM but failed to fetch details."
            # else: # AMBIGUOUS or NO_MATCH
            #     # Construct a list for the user to choose or for a more advanced LLM to pick from.
            event_options_str = ""
            for i, ev in enumerate(potential_events[:3]): # Show first 3
                summary = ev.get('summary', 'No Title')
                start_obj = ev.get('start', {})
                time_str = "Unknown time"
                if start_obj:
                    date_val = start_obj.get('dateTime', start_obj.get('date'))
                    if date_val:
                        try:
                            dt_obj = dateutil_parser.isoparse(date_val).astimezone(user_tz)
                            time_str = dt_obj.strftime('%a, %b %d at %I:%M %p')
                        except:
                            time_str = str(date_val)
                event_options_str += f"\n- '{summary}' on {time_str}"
            return (f"Found multiple events matching your description '{search_query}'. "
                     f"Please be more specific (e.g., include exact time or more title details). Options found:{event_options_str}")

        if not event_to_update_id: # Should be caught by logic above if not single event found and resolved
            return f"Error: Could not confidently identify a single event to update based on '{search_query}'. Please be more specific."

        # 4. LLM call to extract structured update_data from 'changes_description'
        logger.info(f"Asking LLM to extract structured updates from: '{changes_description}' for event ID {event_to_update_id}")
        update_data_dict = await llm_service.extract_calendar_update_details_llm(
            natural_language_changes=changes_description,
            original_event_details=original_event_details_for_confirm,
            current_time_iso=now_local_iso,
            user_timezone_str=self.user_timezone_str
        )

        if not update_data_dict:
            return (f"Error: Could not understand the specific changes you want to make ('{changes_description}'). "
                    "Please specify fields like summary, time, location, or description clearly.")

        update_data_dict = {k: v for k, v in update_data_dict.items() if v is not None}
        if not update_data_dict:
             return "Error: No valid changes were extracted from your request. Please specify what you want to update."

        # 5. Format user-friendly confirmation string
        try:
            confirm_parts = ["Okay, I can update this event:"]
            original_summary = original_event_details_for_confirm.get('summary', 'N/A')
            original_start_str = original_event_details_for_confirm.get('start', {}).get('dateTime', original_event_details_for_confirm.get('start', {}).get('date'))
            original_start_confirm = "N/A"
            if original_start_str:
                original_start_dt_local = dateutil_parser.isoparse(original_start_str).astimezone(user_tz)
                original_start_confirm = original_start_dt_local.strftime('%a, %b %d, %Y at %I:%M %p %Z')

            confirm_parts.append(f"<b>Original Event:</b> {original_summary} (Starts: {original_start_confirm})")
            confirm_parts.append("<b>Proposed Changes:</b>")

            changed_fields_formatted = []
            for field, new_value in update_data_dict.items():
                if field == 'start' or field == 'end':
                    dt_str = new_value.get('dateTime') if isinstance(new_value, dict) else None
                    if dt_str: # Expects {'dateTime': 'ISO_STRING', 'timeZone': '...'}
                        dt_local = dateutil_parser.isoparse(dt_str).astimezone(user_tz)
                        formatted_dt = dt_local.strftime('%a, %b %d, %Y at %I:%M %p %Z')
                        changed_fields_formatted.append(f"  - {field.capitalize()}: {formatted_dt}")
                    else:
                        # If new_value is not a dict or dateTime is missing, log and show raw
                        logger.warning(f"Update data for {field} is not in expected format: {new_value}")
                        changed_fields_formatted.append(f"  - {field.capitalize()}: {str(new_value)}")
                elif isinstance(new_value, str):
                     changed_fields_formatted.append(f"  - {field.capitalize()}: {new_value}")
                else:
                     changed_fields_formatted.append(f"  - {field.capitalize()}: {str(new_value)}")

            if not changed_fields_formatted:
                return "Error: No specific changes identified to confirm."

            confirm_parts.extend(changed_fields_formatted)
            confirm_parts.append("\nShould I apply these updates?")
            confirmation_string = "\n".join(confirm_parts)

        except Exception as e:
            logger.error(f"Error formatting update confirmation for user {self.user_id}: {e}", exc_info=True)
            return "Error: Could not process the extracted event details for update confirmation."

        # 6. Store pending action data
        pending_update_info = {
            'event_id': event_to_update_id,
            'update_data': update_data_dict,
            'original_summary_for_confirm': original_summary,
            'original_start_for_confirm': original_start_confirm,
            'confirmation_message_from_tool': confirmation_string
        }
        # Ensure pending_updates dictionary exists in config
        if not hasattr(config, 'pending_updates'):
            config.pending_updates = {}

        config.pending_updates[self.user_id] = pending_update_info
        if hasattr(config, 'pending_events') and self.user_id in config.pending_events:
             del config.pending_events[self.user_id]
        if hasattr(config, 'pending_deletions') and self.user_id in config.pending_deletions:
             del config.pending_deletions[self.user_id]

        # 7. Return the confirmation string to the agent/handler
        return confirmation_string
