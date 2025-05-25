# agent_tools.py
import logging

from langchain.tools import BaseTool  # Use BaseTool for async/context

from llm.tools.create_calendar import CreateCalendarEventTool
from llm.tools.delete_calendar import DeleteCalendarEventTool
from llm.tools.get_current_time_tool import GetCurrentTimeTool
from llm.tools.read_calendar import ReadCalendarEventsTool
from llm.tools.search_calendar import SearchCalendarEventsTool
from llm.tools.add_grocery_item_tool import AddGroceryItemTool
from llm.tools.show_grocery_list_tool import ShowGroceryListTool
from llm.tools.clear_grocery_list_tool import ClearGroceryListTool

logger = logging.getLogger(__name__)


def get_tools(user_id: int, user_timezone_str: str) -> list[BaseTool]:
    """Factory function to create tools with user context."""
    return [
        ReadCalendarEventsTool(user_id=user_id, user_timezone_str=user_timezone_str),
        SearchCalendarEventsTool(user_id=user_id, user_timezone_str=user_timezone_str),
        CreateCalendarEventTool(user_id=user_id, user_timezone_str=user_timezone_str),
        DeleteCalendarEventTool(user_id=user_id, user_timezone_str=user_timezone_str),
        GetCurrentTimeTool(user_id=user_id, user_timezone_str=user_timezone_str),
        AddGroceryItemTool(user_id=user_id, user_timezone_str=user_timezone_str),
        ShowGroceryListTool(user_id=user_id, user_timezone_str=user_timezone_str),
        ClearGroceryListTool(user_id=user_id, user_timezone_str=user_timezone_str),
    ]
