import sys
import types
import importlib
import zoneinfo
import platform

import pytest

# Dummy pytz replacement similar to fixture in test_handlers
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
def utils_module(monkeypatch):
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
    monkeypatch.setitem(sys.modules, "dateutil", types.ModuleType("dateutil"))
    monkeypatch.setitem(sys.modules, "dateutil.parser", parser_mod)

    utils = importlib.import_module("utils")
    importlib.reload(utils)
    return utils

def test_format_event_time_all_day_single(utils_module):
    tz = zoneinfo.ZoneInfo("UTC")
    event = {"start": {"date": "2024-01-01"}, "end": {"date": "2024-01-02"}}
    result = utils_module._format_event_time(event, tz)
    assert result == "Mon, Jan 01 (All day)"


def test_format_event_time_all_day_multi(utils_module):
    tz = zoneinfo.ZoneInfo("UTC")
    event = {"start": {"date": "2024-01-01"}, "end": {"date": "2024-01-05"}}
    result = utils_module._format_event_time(event, tz)
    assert result == "Mon, Jan 01 - Thu, Jan 04 (All day)"


def test_format_event_time_timed_single_day(utils_module):
    tz = zoneinfo.ZoneInfo("UTC")
    event = {
        "start": {"dateTime": "2024-01-01T09:00:00+00:00"},
        "end": {"dateTime": "2024-01-01T10:30:00+00:00"},
    }
    result = utils_module._format_event_time(event, tz)
    assert result == "Mon, Jan 01, 2024 at 09:00 AM UTC - 10:30 AM UTC"


def test_format_event_time_timed_multi_day(utils_module):
    tz = zoneinfo.ZoneInfo("UTC")
    event = {
        "start": {"dateTime": "2024-01-01T23:00:00+00:00"},
        "end": {"dateTime": "2024-01-02T01:00:00+00:00"},
    }
    result = utils_module._format_event_time(event, tz)
    assert result == "Mon, Jan 01, 2024 at 11:00 PM UTC - Jan 02, 2024 01:00 AM UTC"


def test_format_event_time_missing_start(utils_module):
    tz = zoneinfo.ZoneInfo("UTC")
    event = {"start": {}, "end": {"dateTime": "2024-01-01T10:00:00+00:00"}}
    result = utils_module._format_event_time(event, tz)
    assert result == "[Unknown Start Time]"


def test_format_event_time_parse_error(utils_module):
    tz = zoneinfo.ZoneInfo("UTC")
    event = {"start": {"dateTime": "bad"}, "end": {"dateTime": "bad"}}
    result = utils_module._format_event_time(event, tz)
    assert result == "bad [Error Formatting]"


def test_escape_markdown_v2(utils_module):
    result = utils_module.escape_markdown_v2("Hello [world]!")
    assert result == "Hello \\[world\\]\\!"


def test_format_to_nice_date_windows(monkeypatch):
    import time_util
    importlib.reload(time_util)
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    result = time_util.format_to_nice_date("2024-01-02T05:06:00")
    assert result == "Tuesday, 2 January 2024 \u00b7 05:06"


def test_format_to_nice_date_unix(monkeypatch):
    import time_util
    importlib.reload(time_util)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    result = time_util.format_to_nice_date("2024-01-02T05:06:00")
    assert result == "Tuesday, 2 January 2024 \u00b7 05:06"
