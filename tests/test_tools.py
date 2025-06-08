import sys
import types
import importlib
import zoneinfo
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

class DummyPytzModule(types.ModuleType):
    class UnknownTimeZoneError(Exception):
        pass

    class BaseTzInfo(zoneinfo.ZoneInfo):
        pass

    def timezone(self, name: str):
        try:
            return zoneinfo.ZoneInfo(name)
        except Exception:
            raise self.UnknownTimeZoneError

    utc = zoneinfo.ZoneInfo("UTC")


@pytest.fixture
def tools(monkeypatch):
    dummy = DummyPytzModule("pytz")
    monkeypatch.setitem(sys.modules, "pytz", dummy)
    exc_mod = types.ModuleType("pytz.exceptions")
    exc_mod.UnknownTimeZoneError = dummy.UnknownTimeZoneError
    monkeypatch.setitem(sys.modules, "pytz.exceptions", exc_mod)

    parser_mod = types.ModuleType("dateutil.parser")
    def isoparse(s: str):
        from datetime import datetime
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    parser_mod.isoparse = isoparse
    relativedelta_mod = types.ModuleType("dateutil.relativedelta")
    class relativedelta:
        def __init__(self, *args, **kwargs):
            self.years = kwargs.get("years", 0)
            self.months = kwargs.get("months", 0)
            self.days = kwargs.get("days", 0)
            self.hours = kwargs.get("hours", 0)
            self.minutes = kwargs.get("minutes", 0)
    relativedelta_mod.relativedelta = relativedelta
    dateutil_pkg = types.ModuleType("dateutil")
    dateutil_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "dateutil", dateutil_pkg)
    monkeypatch.setitem(sys.modules, "dateutil.parser", parser_mod)
    monkeypatch.setitem(sys.modules, "dateutil.relativedelta", relativedelta_mod)

    pydantic_mod = types.ModuleType("pydantic")
    class BaseModel:
        pass
    def Field(**kwargs):
        return None
    pydantic_mod.BaseModel = BaseModel
    pydantic_mod.Field = Field
    monkeypatch.setitem(sys.modules, "pydantic", pydantic_mod)

    langchain_tools = types.ModuleType("langchain.tools")
    class BaseTool:
        def __init__(self, *a, **k):
            for key, val in k.items():
                setattr(self, key, val)
    langchain_tools.BaseTool = BaseTool
    monkeypatch.setitem(sys.modules, "langchain.tools", langchain_tools)
    langchain_core_tools = types.ModuleType("langchain_core.tools")
    langchain_core_tools.BaseTool = BaseTool
    monkeypatch.setitem(sys.modules, "langchain_core.tools", langchain_core_tools)

    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "dotenv", dotenv_mod)

    config_mod = types.ModuleType("config")
    config_mod.TELEGRAM_BOT_TOKEN = ""
    config_mod.GOOGLE_CLIENT_SECRETS_FILE = ""
    config_mod.GOOGLE_API_KEY = ""
    config_mod.OAUTH_REDIRECT_URI = ""
    monkeypatch.setitem(sys.modules, "config", config_mod)

    gs_mod = types.ModuleType("grocery_services")
    from unittest.mock import MagicMock

    async def async_true(*args, **kwargs):
        return True

    async def async_list(*args, **kwargs):
        return ["milk"]

    gs_mod.add_to_grocery_list = async_true
    gs_mod.delete_grocery_list = async_true
    gs_mod.get_grocery_list = MagicMock(side_effect=async_list)
    gs_mod.add_pending_event = AsyncMock(return_value=True)
    gs_mod.delete_pending_deletion = lambda *a, **k: None
    gs_mod.get_calendar_event_by_id = AsyncMock(return_value={
        "summary": "Event",
        "start": {"dateTime": "2024-01-01T00:00:00+00:00"},
        "end": {"dateTime": "2024-01-01T01:00:00+00:00"},
        "id": "1",
    })
    gs_mod.add_pending_deletion = lambda *a, **k: True
    gs_mod.delete_pending_event = lambda *a, **k: None
    gs_mod.get_calendar_events = AsyncMock(return_value=[{"id": "ev1"}])
    gs_mod.search_calendar_events = AsyncMock(return_value=[{"id": "ev2"}])
    sys.modules["google_services"] = gs_mod
    sys.modules["grocery_services"] = gs_mod
    sys.modules["calendar_services"] = gs_mod

    llm_service_mod = types.ModuleType("llm.llm_service")
    llm_service_mod.extract_create_args_llm = AsyncMock(return_value={
        "summary": "Event",
        "start": {"dateTime": "2024-01-01T00:00:00+00:00"},
        "end": {"dateTime": "2024-01-01T01:00:00+00:00"},
        "description": "desc",
        "location": "loc",
    })
    llm_service_mod.extract_read_args_llm = AsyncMock(return_value={
        "start_iso": "2024-01-01T00:00:00+00:00",
        "end_iso": "2024-01-02T00:00:00+00:00",
    })
    llm_service_mod.extract_search_args_llm = AsyncMock(return_value={
        "query": "meet",
        "start_iso": "2024-01-01T00:00:00+00:00",
        "end_iso": "2024-01-02T00:00:00+00:00",
    })
    if "llm" in sys.modules:
        del sys.modules["llm"]
    import importlib
    llm_pkg = importlib.import_module("llm")
    monkeypatch.setattr(llm_pkg, "llm_service", llm_service_mod, raising=False)
    sys.modules["llm.llm_service"] = llm_service_mod

    utils_mod = types.ModuleType("utils")
    utils_mod._format_event_time = lambda *a, **k: "formatted time"
    sys.modules["utils"] = utils_mod

    fmt_mod = importlib.import_module("llm.tools.formatting")
    monkeypatch.setattr(fmt_mod, "format_event_list_for_agent", lambda *a, **k: "formatted events")

    modules = {}
    names = [
        "add_grocery_item_tool",
        "clear_grocery_list_tool",
        "show_grocery_list_tool",
        "get_current_time_tool",
        "create_calendar",
        "delete_calendar",
        "read_calendar",
        "search_calendar",
    ]
    for name in names:
        mod = importlib.import_module(f"llm.tools.{name}")
        importlib.reload(mod)
        modules[name] = mod
    return modules

def test_add_grocery_item_success(tools):
    tool_cls = tools["add_grocery_item_tool"].AddGroceryItemTool
    tool = tool_cls(user_id=1, user_timezone_str="UTC")
    result = tool._run("eggs, bread")
    assert "Successfully added" in result


def test_add_grocery_item_invalid(tools):
    tool_cls = tools["add_grocery_item_tool"].AddGroceryItemTool
    tool = tool_cls(user_id=1, user_timezone_str="UTC")
    result = tool._run("")
    assert result.startswith("Input error")


def test_clear_grocery_list(tools):
    tool_cls = tools["clear_grocery_list_tool"].ClearGroceryListTool
    tool = tool_cls(user_id=1, user_timezone_str="UTC")
    result = tool._run()
    assert result.startswith("Successfully cleared")


def test_show_grocery_list(tools):
    tool_cls = tools["show_grocery_list_tool"].ShowGroceryListTool
    tool = tool_cls(user_id=1, user_timezone_str="UTC")
    result = tool._run()
    assert result.startswith("Your grocery list")


def test_show_grocery_list_empty(tools, monkeypatch):
    gs = sys.modules["grocery_services"]
    async def empty_list(*args, **kwargs):
        return []
    gs.get_grocery_list.side_effect = empty_list
    tool_cls = tools["show_grocery_list_tool"].ShowGroceryListTool
    tool = tool_cls(user_id=1, user_timezone_str="UTC")
    result = tool._run()
    assert "currently empty" in result


def test_get_current_time(tools, monkeypatch):
    tool_cls = tools["get_current_time_tool"].GetCurrentTimeTool
    tool = tool_cls(user_id=1, user_timezone_str="UTC")
    from datetime import datetime
    fixed = datetime(2024, 1, 1, 12, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
    monkeypatch.setattr(tools["get_current_time_tool"], "datetime", types.SimpleNamespace(now=lambda tz=None: fixed))
    result = asyncio.run(tool._arun())
    assert "2024-01-01" in result
    assert "ISO: 2024-01-01T12:00:00+00:00" in result


def test_create_calendar_event(tools):
    tool_cls = tools["create_calendar"].CreateCalendarEventTool
    tool = tool_cls(user_id=1, user_timezone_str="UTC")
    result = asyncio.run(tool._arun("meeting tomorrow"))
    assert result.endswith("Should I add this to your calendar?")


def test_delete_calendar_event(tools):
    tool_cls = tools["delete_calendar"].DeleteCalendarEventTool
    tool = tool_cls(user_id=1, user_timezone_str="UTC")
    result = asyncio.run(tool._arun("abcde"))
    assert result.startswith("Found event")


def test_read_calendar_events(tools):
    tool_cls = tools["read_calendar"].ReadCalendarEventsTool
    tool = tool_cls(user_id=1, user_timezone_str="UTC")
    result = asyncio.run(tool._arun("today"))
    assert result == "formatted events"


def test_search_calendar_events(tools):
    tool_cls = tools["search_calendar"].SearchCalendarEventsTool
    tool = tool_cls(user_id=1, user_timezone_str="UTC")
    result = asyncio.run(tool._arun("meeting"))
    assert result == "formatted events"
