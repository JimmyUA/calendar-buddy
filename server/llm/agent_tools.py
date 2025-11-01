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


def get_tools(user_id: int, user_timezone_str: str, mcp_client) -> list[BaseTool]:
    """Factory function to create tools with user context."""
    return [
        ReadCalendarEventsTool(user_id=user_id, user_timezone_str=user_timezone_str, mcp_client=mcp_client),
        SearchCalendarEventsTool(user_id=user_id, user_timezone_str=user_timezone_str, mcp_client=mcp_client),
        CreateCalendarEventTool(user_id=user_id, user_timezone_str=user_timezone_str, mcp_client=mcp_client),
        DeleteCalendarEventTool(user_id=user_id, user_timezone_str=user_timezone_str, mcp_client=mcp_client),
        GetCurrentTimeTool(user_id=user_id, user_timezone_str=user_timezone_str, mcp_client=mcp_client),
        AddGroceryItemTool(user_id=user_id, user_timezone_str=user_timezone_str, mcp_client=mcp_client),
        ShowGroceryListTool(user_id=user_id, user_timezone_str=user_timezone_str, mcp_client=mcp_client),
        ClearGroceryListTool(user_id=user_id, user_timezone_str=user_timezone_str, mcp_client=mcp_client),
    ]
