import sys
import types
import importlib

import pytest


class DummyApplication:
    def __init__(self):
        self.handlers = []
        self.error_handler = None
        self.run_called = False
        self.allowed_updates = None
        self.bot_data = {}

    def add_handler(self, handler):
        self.handlers.append(handler)

    def add_error_handler(self, handler):
        self.error_handler = handler

    def run_polling(self, allowed_updates=None):
        self.allowed_updates = allowed_updates
        self.run_called = True


class DummyBuilder:
    def __init__(self, app):
        self.app = app
    def token(self, *a, **k):
        return self
    def connection_pool_size(self, *a, **k):
        return self
    def concurrent_updates(self, *a, **k):
        return self
    def build(self):
        return self.app


created_threads = []

class DummyThread:
    def __init__(self, target=None, daemon=None):
        self.target = target
        self.daemon = daemon
        self.started = False
        created_threads.append(self)

    def start(self):
        self.started = True


@pytest.fixture
def bot_module(monkeypatch):
    # stub fastmcp
    fastmcp_mod = types.ModuleType("fastmcp")
    fastmcp_mod.Client = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "fastmcp", fastmcp_mod)

    # stub config
    config_mod = types.ModuleType("config")
    config_mod.os = types.SimpleNamespace(getenv=lambda k, default=None: default)
    config_mod.TELEGRAM_BOT_TOKEN = "token"
    config_mod.FIRESTORE_DB = object()
    monkeypatch.setitem(sys.modules, "config", config_mod)

    # stub handlers
    handlers_mod = types.ModuleType("handlers")
    handlers_mod.ASKING_TIMEZONE = 0
    names = [
        "set_timezone_start",
        "received_timezone",
        "cancel_timezone",
        "start",
        "help_command",
        "menu_command",
        "connect_calendar",
        "my_status",
        "disconnect_calendar",
        "summary_command",
        "request_calendar_access_command",
        "glist_add",
        "glist_clear",
        "glist_show",
        "share_glist_command",
        "handle_message",
        "button_callback",
        "users_shared_handler",
        "error_handler",
    ]
    for name in names:
        setattr(handlers_mod, name, lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "handlers", handlers_mod)

    # stub telegram modules
    telegram_mod = types.ModuleType("telegram")
    telegram_mod.Update = types.SimpleNamespace(ALL_TYPES="ALL")
    monkeypatch.setitem(sys.modules, "telegram", telegram_mod)

    telegram_ext_mod = types.ModuleType("telegram.ext")
    app_instance = DummyApplication()
    telegram_ext_mod.Application = types.SimpleNamespace(builder=lambda: DummyBuilder(app_instance))
    telegram_ext_mod.CommandHandler = lambda *a, **k: ("CommandHandler", a, k)
    telegram_ext_mod.MessageHandler = lambda *a, **k: ("MessageHandler", a, k)
    telegram_ext_mod.CallbackQueryHandler = lambda *a, **k: ("CallbackQueryHandler", a, k)
    telegram_ext_mod.filters = types.SimpleNamespace(
        TEXT=1,
        PHOTO=4,
        VOICE=5,
        AUDIO=6,
        COMMAND=2,
        StatusUpdate=types.SimpleNamespace(USERS_SHARED=3),
    )
    telegram_ext_mod.ConversationHandler = type("ConversationHandler", (), {"END": 0, "__init__": lambda self, *a, **k: None})
    monkeypatch.setitem(sys.modules, "telegram.ext", telegram_ext_mod)

    # stub flask
    flask_mod = types.ModuleType("flask")
    class DummyFlask:
        def __init__(self, name):
            self.name = name
        def route(self, *a, **k):
            def decorator(f):
                return f
            return decorator
        def run(self, host=None, port=None, use_reloader=None):
            self.run_args = (host, port, use_reloader)
    flask_mod.Flask = DummyFlask
    monkeypatch.setitem(sys.modules, "flask", flask_mod)

    if "bot" in sys.modules:
        del sys.modules["bot"]
    bot = importlib.import_module("bot")

    # patch threading.Thread after import
    monkeypatch.setattr(bot.threading, "Thread", DummyThread)
    return bot, app_instance, created_threads


def test_health_check(bot_module):
    bot, app, threads = bot_module
    body, status = bot.health_check()
    assert body == "OK"
    assert status == 200


def test_main_runs_polling(monkeypatch, bot_module):
    bot, app, threads = bot_module
    bot.main()
    assert app.run_called
    assert app.allowed_updates == "ALL"
    assert threads and threads[0].started


def test_main_exits_without_token(monkeypatch, bot_module):
    bot, app, threads = bot_module
    app.run_called = False
    threads.clear()
    monkeypatch.setattr(bot.config, "TELEGRAM_BOT_TOKEN", "")
    bot.main()
    assert not app.run_called
    assert not threads
