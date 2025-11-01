import sys
import types
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

@pytest.fixture(autouse=True)
def langchain_mock(monkeypatch):
    langchain_mod = types.ModuleType("langchain")
    langchain_mod.tools = types.ModuleType("langchain.tools")
    class BaseTool:
        name = ""
    langchain_mod.tools.BaseTool = BaseTool
    monkeypatch.setitem(sys.modules, "langchain", langchain_mod)
    monkeypatch.setitem(sys.modules, "langchain.tools", langchain_mod.tools)

    def tool_init(self, *args, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    pydantic_mod = types.ModuleType("pydantic")
    pydantic_mod.BaseModel = type("BaseModel", (), {})
    pydantic_mod.Field = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "pydantic", pydantic_mod)

    llm_mod = types.ModuleType("llm")
    llm_mod.tools = types.ModuleType("llm.tools")
    llm_mod.tools.create_calendar = types.ModuleType("llm.tools.create_calendar")
    llm_mod.tools.create_calendar.CreateCalendarEventTool = type("CreateCalendarEventTool", (langchain_mod.tools.BaseTool,), {"__init__": tool_init, "name": "create_calendar_event"})
    llm_mod.tools.delete_calendar = types.ModuleType("llm.tools.delete_calendar")
    llm_mod.tools.delete_calendar.DeleteCalendarEventTool = type("DeleteCalendarEventTool", (langchain_mod.tools.BaseTool,), {"__init__": tool_init, "name": "delete_calendar_event"})
    llm_mod.tools.get_current_time_tool = types.ModuleType("llm.tools.get_current_time_tool")
    llm_mod.tools.get_current_time_tool.GetCurrentTimeTool = type("GetCurrentTimeTool", (langchain_mod.tools.BaseTool,), {"__init__": tool_init, "name": "get_current_time"})
    llm_mod.tools.read_calendar = types.ModuleType("llm.tools.read_calendar")
    llm_mod.tools.read_calendar.ReadCalendarEventsTool = type("ReadCalendarEventsTool", (langchain_mod.tools.BaseTool,), {"__init__": tool_init, "name": "read_calendar_events"})
    llm_mod.tools.search_calendar = types.ModuleType("llm.tools.search_calendar")
    llm_mod.tools.search_calendar.SearchCalendarEventsTool = type("SearchCalendarEventsTool", (langchain_mod.tools.BaseTool,), {"__init__": tool_init, "name": "search_calendar_events"})
    llm_mod.tools.add_grocery_item_tool = types.ModuleType("llm.tools.add_grocery_item_tool")
    llm_mod.tools.add_grocery_item_tool.AddGroceryItemTool = type("AddGroceryItemTool", (langchain_mod.tools.BaseTool,), {"__init__": tool_init, "name": "add_grocery_item"})
    llm_mod.tools.show_grocery_list_tool = types.ModuleType("llm.tools.show_grocery_list_tool")
    llm_mod.tools.show_grocery_list_tool.ShowGroceryListTool = type("ShowGroceryListTool", (langchain_mod.tools.BaseTool,), {"__init__": tool_init, "name": "show_grocery_list"})
    llm_mod.tools.clear_grocery_list_tool = types.ModuleType("llm.tools.clear_grocery_list_tool")
    llm_mod.tools.clear_grocery_list_tool.ClearGroceryListTool = type("ClearGroceryListTool", (langchain_mod.tools.BaseTool,), {"__init__": tool_init, "name": "clear_grocery_list"})

    monkeypatch.setitem(sys.modules, "llm", llm_mod)
    monkeypatch.setitem(sys.modules, "llm.tools", llm_mod.tools)
    monkeypatch.setitem(sys.modules, "llm.tools.create_calendar", llm_mod.tools.create_calendar)
    monkeypatch.setitem(sys.modules, "llm.tools.delete_calendar", llm_mod.tools.delete_calendar)
    monkeypatch.setitem(sys.modules, "llm.tools.get_current_time_tool", llm_mod.tools.get_current_time_tool)
    monkeypatch.setitem(sys.modules, "llm.tools.read_calendar", llm_mod.tools.read_calendar)
    monkeypatch.setitem(sys.modules, "llm.tools.search_calendar", llm_mod.tools.search_calendar)
    monkeypatch.setitem(sys.modules, "llm.tools.add_grocery_item_tool", llm_mod.tools.add_grocery_item_tool)
    monkeypatch.setitem(sys.modules, "llm.tools.show_grocery_list_tool", llm_mod.tools.show_grocery_list_tool)
    monkeypatch.setitem(sys.modules, "llm.tools.clear_grocery_list_tool", llm_mod.tools.clear_grocery_list_tool)


@pytest.fixture
def mcp_client_mock():
    client = MagicMock()
    client.call_tool = AsyncMock()
    return client

def test_add_grocery_item_tool(mcp_client_mock):
    from server.llm.agent_tools import get_tools
    from server.llm.tools.add_grocery_item_tool import AddGroceryItemTool
    tools = get_tools(1, "UTC", mcp_client_mock)
    add_tool = next(t for t in tools if t.name == "add_grocery_item")
    add_tool._arun = AddGroceryItemTool._arun

    asyncio.run(add_tool._arun(add_tool, "milk, eggs"))

    mcp_client_mock.call_tool.assert_awaited_once_with(
        "add_to_grocery_list", user_id=1, items_to_add=["milk", "eggs"]
    )

def test_show_grocery_list_tool(mcp_client_mock):
    from server.llm.agent_tools import get_tools
    from server.llm.tools.show_grocery_list_tool import ShowGroceryListTool
    tools = get_tools(1, "UTC", mcp_client_mock)
    show_tool = next(t for t in tools if t.name == "show_grocery_list")
    show_tool._arun = ShowGroceryListTool._arun

    asyncio.run(show_tool._arun(show_tool))

    mcp_client_mock.call_tool.assert_awaited_once_with(
        "get_grocery_list", user_id=1
    )

def test_clear_grocery_list_tool(mcp_client_mock):
    from server.llm.agent_tools import get_tools
    from server.llm.tools.clear_grocery_list_tool import ClearGroceryListTool
    tools = get_tools(1, "UTC", mcp_client_mock)
    clear_tool = next(t for t in tools if t.name == "clear_grocery_list")
    clear_tool._arun = ClearGroceryListTool._arun

    asyncio.run(clear_tool._arun(clear_tool))

    mcp_client_mock.call_tool.assert_awaited_once_with(
        "delete_grocery_list", user_id=1
    )
