import logging
from datetime import datetime

import pytz  # For timezone handling
from pytz.exceptions import UnknownTimeZoneError
from dateutil import parser as dateutil_parser

import config
import google_services as gs
from llm import llm_service
from llm.tools.calendar_base import CalendarBaseTool
from llm.tools.formatting import format_event_list_for_agent

logger = logging.getLogger(__name__)


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
