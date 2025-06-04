import sys
import types
import zoneinfo
import importlib
from unittest.mock import AsyncMock, MagicMock
import asyncio

import pytest

# provide a minimal pytz replacement since package may not be installed
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

# fixture that loads handlers with patched pytz
@pytest.fixture
def handlers_module(monkeypatch):
    dummy = DummyPytzModule("pytz")
    monkeypatch.setitem(sys.modules, "pytz", dummy)
    exc_mod = types.ModuleType("pytz.exceptions")
    exc_mod.UnknownTimeZoneError = dummy.UnknownTimeZoneError
    monkeypatch.setitem(sys.modules, "pytz.exceptions", exc_mod)
    # minimal dateutil.parser replacement
    parser_mod = types.ModuleType("dateutil.parser")
    def isoparse(s: str):
        from datetime import datetime
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    parser_mod.isoparse = isoparse
    monkeypatch.setitem(sys.modules, "dateutil", types.ModuleType("dateutil"))
    monkeypatch.setitem(sys.modules, "dateutil.parser", parser_mod)
    # stub config module
    config_mod = types.ModuleType("config")
    config_mod.TELEGRAM_BOT_TOKEN = ""
    config_mod.GOOGLE_CLIENT_SECRETS_FILE = ""
    config_mod.GOOGLE_API_KEY = ""
    config_mod.OAUTH_REDIRECT_URI = ""
    monkeypatch.setitem(sys.modules, "config", config_mod)
    # stub google_services module and related functions
    gs_mod = types.ModuleType("google_services")
    async def async_noop(*args, **kwargs):
        return None
    gs_mod.get_user_timezone_str = async_noop
    sys.modules["google_services"] = gs_mod
    # also provide names imported separately
    sys.modules["google_services"].add_pending_event = async_noop
    sys.modules["google_services"].get_pending_event = async_noop
    sys.modules["google_services"].delete_pending_event = async_noop
    sys.modules["google_services"].add_pending_deletion = async_noop
    sys.modules["google_services"].get_pending_deletion = async_noop
    sys.modules["google_services"].delete_pending_deletion = async_noop
    # minimal telegram modules
    telegram_mod = types.ModuleType("telegram")
    class Update: pass
    class InlineKeyboardButton: pass
    class InlineKeyboardMarkup: pass
    class KeyboardButton: pass
    class ReplyKeyboardMarkup: pass
    class KeyboardButtonRequestUsers: pass
    telegram_mod.Update = Update
    telegram_mod.InlineKeyboardButton = InlineKeyboardButton
    telegram_mod.InlineKeyboardMarkup = InlineKeyboardMarkup
    telegram_mod.KeyboardButton = KeyboardButton
    telegram_mod.ReplyKeyboardMarkup = ReplyKeyboardMarkup
    telegram_mod.KeyboardButtonRequestUsers = KeyboardButtonRequestUsers
    monkeypatch.setitem(sys.modules, "telegram", telegram_mod)

    telegram_ext = types.ModuleType("telegram.ext")
    telegram_ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
    telegram_ext.ConversationHandler = types.SimpleNamespace(END=0)
    monkeypatch.setitem(sys.modules, "telegram.ext", telegram_ext)

    telegram_constants = types.ModuleType("telegram.constants")
    telegram_constants.ParseMode = types.SimpleNamespace(MARKDOWN="markdown", MARKDOWN_V2="markdown_v2", HTML="html")
    monkeypatch.setitem(sys.modules, "telegram.constants", telegram_constants)
    # stub google generativeai
    google_mod = types.ModuleType("google")
    google_genai = types.ModuleType("google.generativeai")
    google_api_core = types.ModuleType("google.api_core.exceptions")
    class GoogleAPIError(Exception):
        pass
    google_api_core.GoogleAPIError = GoogleAPIError
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.generativeai", google_genai)
    monkeypatch.setitem(sys.modules, "google.api_core.exceptions", google_api_core)
    # stub llm package
    llm_pkg = types.ModuleType("llm")
    llm_service_mod = types.ModuleType("llm.llm_service")
    agent_mod = types.ModuleType("llm.agent")
    agent_mod.initialize_agent = lambda *args, **kwargs: None
    llm_pkg.llm_service = llm_service_mod
    llm_pkg.agent = agent_mod
    sys.modules["llm"] = llm_pkg
    sys.modules["llm.llm_service"] = llm_service_mod
    sys.modules["llm.agent"] = agent_mod
    # stub utils module
    utils_mod = types.ModuleType("utils")
    utils_mod._format_event_time = lambda *args, **kwargs: ""
    utils_mod.escape_markdown_v2 = lambda text: text
    sys.modules["utils"] = utils_mod
    # stub handler.message_formatter
    msg_mod = types.ModuleType("handler.message_formatter")
    msg_mod.create_final_message = lambda data: ""
    sys.modules["handler.message_formatter"] = msg_mod
    handlers = importlib.import_module("handlers")
    return handlers

# ---------- Tests for _format_iso_datetime_for_display ----------
@pytest.mark.parametrize(
    "iso_string,target_tz,expected",
    [
        ("2024-01-01T12:00:00+00:00", "America/Los_Angeles", "2024-01-01 04:00 AM PST"),
        ("2024-06-01T15:30:00+02:00", None, "2024-06-01 03:30 PM UTC+02:00"),
    ],
)
def test_format_iso_datetime_for_display(handlers_module, iso_string, target_tz, expected):
    result = handlers_module._format_iso_datetime_for_display(iso_string, target_tz)
    assert result == expected


def test_format_iso_datetime_for_display_invalid_timezone(handlers_module, caplog):
    iso = "2024-01-01T12:00:00+00:00"
    result = handlers_module._format_iso_datetime_for_display(iso, "Invalid/Zone")
    assert result.endswith("UTC")
    assert "Unknown timezone string" in caplog.text


# ---------- Tests for _get_user_tz_or_prompt ----------
def test_get_user_tz_or_prompt_returns_timezone(handlers_module, monkeypatch):
    mock_update = MagicMock()
    mock_message = MagicMock()
    mock_update.effective_user.id = 1
    mock_update.message = mock_message
    mock_message.reply_text = AsyncMock()

    mock_context = MagicMock()

    monkeypatch.setattr(handlers_module.gs, "get_user_timezone_str", AsyncMock(return_value="UTC"))

    tz = asyncio.run(handlers_module._get_user_tz_or_prompt(mock_update, mock_context))

    assert tz.key == "UTC"
    mock_message.reply_text.assert_not_called()


def test_get_user_tz_or_prompt_prompts_when_missing(handlers_module, monkeypatch):
    mock_update = MagicMock()
    mock_message = MagicMock()
    mock_update.effective_user.id = 1
    mock_update.message = mock_message
    mock_message.reply_text = AsyncMock()

    mock_context = MagicMock()

    monkeypatch.setattr(handlers_module.gs, "get_user_timezone_str", AsyncMock(return_value=None))

    tz = asyncio.run(handlers_module._get_user_tz_or_prompt(mock_update, mock_context))

    assert tz is None
    mock_message.reply_text.assert_called_once()


# ---------- Test for start command ----------
def test_start_sends_welcome_message(handlers_module):
    mock_update = MagicMock()
    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.username = "tester"
    mock_user.mention_html.return_value = "<a>tester</a>"
    mock_update.effective_user = mock_user

    mock_message = MagicMock()
    mock_message.reply_html = AsyncMock()
    mock_update.message = mock_message

    mock_context = MagicMock()

    asyncio.run(handlers_module.start(mock_update, mock_context))

    mock_message.reply_html.assert_called_once()


def test_menu_command_shows_main_menu(handlers_module):
    mock_update = MagicMock()
    mock_message = MagicMock()
    mock_message.reply_text = AsyncMock()
    mock_update.message = mock_message
    mock_update.effective_user = MagicMock()

    mock_context = MagicMock()

    asyncio.run(handlers_module.menu_command(mock_update, mock_context))

    mock_message.reply_text.assert_called_once()


def test_menu_calendar_shows_submenu(handlers_module):
    mock_update = MagicMock()
    mock_message = MagicMock()
    mock_message.reply_text = AsyncMock()
    mock_update.message = mock_message
    mock_update.effective_user = MagicMock()

    mock_context = MagicMock()

    asyncio.run(handlers_module.menu_calendar(mock_update, mock_context))

    mock_message.reply_text.assert_called_once()
