import logging

import pytz  # For timezone handling

from google_services import add_pending_deletion, delete_pending_event # For Firestore pending actions
import google_services as gs
from llm.tools.calendar_base import CalendarBaseTool
from handler.message_formatter import create_delete_confirmation_message
from utils import _format_event_time

logger = logging.getLogger(__name__)


class DeleteCalendarEventTool(CalendarBaseTool):
    name: str = "delete_calendar_event"
    description: str = ("Input is the specific Google Calendar event ID string. Prepares to delete the event with that "
                        "ID and asks the user for confirmation.")

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

        # 2. Format confirmation string with detailed info
        try:
            confirmation_string = await create_delete_confirmation_message(event_details)
        except Exception:
            try:
                user_tz = pytz.timezone(self.user_timezone_str)
                time_confirm = _format_event_time(event_details, user_tz)
            except Exception:
                time_confirm = "[Could not format time]"
            confirmation_string = f"Found event: '{event_summary}' ({time_confirm}).\n\nShould I delete this event?"

        # 3. Store pending action data
        # Clear any pending event creation first to avoid conflicting states
        delete_pending_event(self.user_id)

        pending_data = {'event_id': event_id, 'summary': event_summary}
        if add_pending_deletion(self.user_id, pending_data):
            logger.info(f"Tool: Pending deletion for user {self.user_id} (event: {event_id}) stored in Firestore.")
            # 4. Return confirmation string
            return confirmation_string
        else:
            logger.error(f"Tool: Failed to store pending deletion in Firestore for user {self.user_id}.")
            return "Error: Failed to save the event deletion details for confirmation. Please try again."
