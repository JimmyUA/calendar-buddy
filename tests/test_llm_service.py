import importlib
import types
import asyncio
import sys
from unittest.mock import AsyncMock


def setup_llm(monkeypatch, response):
    sys.modules.pop("llm", None)
    sys.modules.pop("llm.llm_service", None)
    # stub packages required during import
    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.genai")
    genai_mod.Client = lambda api_key: None
    google_mod.genai = genai_mod
    api_core_mod = types.ModuleType("google.api_core")
    exceptions_mod = types.ModuleType("google.api_core.exceptions")
    exceptions_mod.GoogleAPIError = type("GoogleAPIError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.api_core", api_core_mod)
    monkeypatch.setitem(sys.modules, "google.api_core.exceptions", exceptions_mod)
    dateutil_pkg = types.ModuleType("dateutil")
    parser_mod = types.ModuleType("dateutil.parser")
    parser_mod.parse = lambda s: None
    monkeypatch.setitem(sys.modules, "dateutil", dateutil_pkg)
    monkeypatch.setitem(sys.modules, "dateutil.parser", parser_mod)
    config_mod = types.ModuleType("config")
    config_mod.GOOGLE_API_KEY = "test-key"
    monkeypatch.setitem(sys.modules, "config", config_mod)

    llm = importlib.import_module("llm.llm_service")
    gem_model = types.SimpleNamespace(
        aio=types.SimpleNamespace(
            models=types.SimpleNamespace(
                generate_content=AsyncMock(return_value=response)
            )
        )
    )
    monkeypatch.setattr(llm, "gemini_client", gem_model)
    monkeypatch.setattr(llm, "llm_available", True)
    return llm, gem_model


def test_extract_text_from_image_returns_text(monkeypatch):
    response = types.SimpleNamespace(text="hello", prompt_feedback=None)
    llm, model = setup_llm(monkeypatch, response)
    result = asyncio.run(llm.extract_text_from_image(b"img"))
    assert result == "hello"
    model.aio.models.generate_content.assert_awaited_once()


def test_extract_text_from_image_blocked(monkeypatch):
    feedback = types.SimpleNamespace(block_reason="safe")
    response = types.SimpleNamespace(text="ignored", prompt_feedback=feedback)
    llm, _ = setup_llm(monkeypatch, response)
    result = asyncio.run(llm.extract_text_from_image(b"img"))
    assert result is None
