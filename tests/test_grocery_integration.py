import sys
import types
import importlib
import asyncio

import pytest

# ---- Fake Firestore Implementation ----

class FakeArrayUnion:
    def __init__(self, items):
        self.items = list(items)

class FakeSnapshot:
    def __init__(self, data):
        self._data = data
    @property
    def exists(self):
        return self._data is not None
    def to_dict(self):
        return self._data

class FakeDocument:
    def __init__(self, collection, doc_id):
        self.collection = collection
        self.doc_id = doc_id
    def get(self):
        data = self.collection.store.get(self.doc_id)
        return FakeSnapshot(data)
    def set(self, data, merge=False):
        existing = self.collection.store.get(self.doc_id, {}) if merge else {}
        for key, value in data.items():
            if isinstance(value, FakeArrayUnion):
                items = existing.get(key, [])
                for item in value.items:
                    if item not in items:
                        items.append(item)
                existing[key] = items
            else:
                existing[key] = value
        self.collection.store[self.doc_id] = existing
    def delete(self):
        self.collection.store.pop(self.doc_id, None)

class FakeCollection:
    def __init__(self):
        self.store = {}
    def document(self, doc_id):
        return FakeDocument(self, doc_id)

# ---- Pytest Fixture ----

@pytest.fixture
def gs_module(monkeypatch):
    # stub config before importing grocery_services
    config_mod = types.ModuleType("config")
    config_mod.FIRESTORE_DB = None
    config_mod.FS_COLLECTION_GROCERY_LISTS = "grocery"
    config_mod.FS_COLLECTION_GROCERY_LIST_GROUPS = "groups"
    config_mod.FS_COLLECTION_GROCERY_SHARE_REQUESTS = "requests"
    config_mod.FS_COLLECTION_PREFS = "prefs"
    config_mod.FS_COLLECTION_PENDING_EVENTS = "pe"
    config_mod.FS_COLLECTION_PENDING_DELETIONS = "pd"
    config_mod.FS_COLLECTION_CALENDAR_ACCESS_REQUESTS = "car"
    config_mod.FS_COLLECTION_LC_CHAT_HISTORIES = "lc"
    config_mod.FS_COLLECTION_GENERAL_CHAT_HISTORIES = "gc"
    config_mod.GOOGLE_CALENDAR_SCOPES = []
    config_mod.OAUTH_REDIRECT_URI = "http://localhost"
    monkeypatch.setitem(sys.modules, "config", config_mod)

    # dummy pytz module
    pytz_mod = types.ModuleType("pytz")
    class UnknownTimeZoneError(Exception):
        pass
    pytz_mod.UnknownTimeZoneError = UnknownTimeZoneError
    pytz_mod.timezone = lambda name: name
    pytz_mod.utc = "UTC"
    monkeypatch.setitem(sys.modules, "pytz", pytz_mod)
    monkeypatch.setitem(sys.modules, "pytz.exceptions", types.SimpleNamespace(UnknownTimeZoneError=UnknownTimeZoneError))

    # minimal dateutil module
    dateutil_mod = types.ModuleType("dateutil")
    parser_mod = types.ModuleType("dateutil.parser")
    parser_mod.isoparse = lambda s: s
    monkeypatch.setitem(sys.modules, "dateutil", dateutil_mod)
    monkeypatch.setitem(sys.modules, "dateutil.parser", parser_mod)

    # minimal pydantic module
    pydantic_mod = types.ModuleType("pydantic")
    class BaseModel:
        pass
    pydantic_mod.BaseModel = BaseModel
    monkeypatch.setitem(sys.modules, "pydantic", pydantic_mod)

    # stub google packages used during import
    google_pkg = types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    google_pkg.cloud = types.ModuleType("google.cloud")
    monkeypatch.setitem(sys.modules, "google.cloud", google_pkg.cloud)
    firestore_mod = types.ModuleType("google.cloud.firestore")
    firestore_mod.ArrayUnion = FakeArrayUnion
    firestore_mod.SERVER_TIMESTAMP = object()
    def transactional(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    firestore_mod.transactional = transactional
    monkeypatch.setitem(sys.modules, "google.cloud.firestore", firestore_mod)
    google_pkg.cloud.firestore = firestore_mod
    firestore_v1_mod = types.ModuleType("google.cloud.firestore_v1")
    base_query_mod = types.ModuleType("google.cloud.firestore_v1.base_query")
    base_query_mod.FieldFilter = object
    monkeypatch.setitem(sys.modules, "google.cloud.firestore_v1", firestore_v1_mod)
    monkeypatch.setitem(sys.modules, "google.cloud.firestore_v1.base_query", base_query_mod)
    secret_mod = types.ModuleType("google.cloud.secretmanager")
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager", secret_mod)

    google_pkg.oauth2 = types.ModuleType("google.oauth2")
    cred_mod = types.ModuleType("google.oauth2.credentials")
    cred_mod.Credentials = object
    monkeypatch.setitem(sys.modules, "google.oauth2", google_pkg.oauth2)
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", cred_mod)

    google_auth_mod = types.ModuleType("google_auth_oauthlib")
    flow_mod = types.ModuleType("google_auth_oauthlib.flow")
    flow_mod.Flow = object
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", google_auth_mod)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_mod)

    google_pkg.auth = types.ModuleType("google.auth")
    google_pkg.auth.transport = types.ModuleType("google.auth.transport")
    requests_mod = types.ModuleType("google.auth.transport.requests")
    requests_mod.Request = object
    monkeypatch.setitem(sys.modules, "google.auth", google_pkg.auth)
    monkeypatch.setitem(sys.modules, "google.auth.transport", google_pkg.auth.transport)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_mod)

    googleapiclient_mod = types.ModuleType("googleapiclient")
    discovery_mod = types.ModuleType("googleapiclient.discovery")
    discovery_mod.build = lambda *a, **kw: None
    errors_mod = types.ModuleType("googleapiclient.errors")
    class HttpError(Exception):
        def __init__(self, resp=None, content=b""):
            self.resp = types.SimpleNamespace(status=500, reason="error")
            self.content = content
    errors_mod.HttpError = HttpError
    monkeypatch.setitem(sys.modules, "googleapiclient", googleapiclient_mod)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery_mod)
    monkeypatch.setitem(sys.modules, "googleapiclient.errors", errors_mod)

    api_core_mod = types.ModuleType("google.api_core")
    exceptions_mod = types.ModuleType("google.api_core.exceptions")
    class NotFound(Exception):
        pass
    exceptions_mod.NotFound = NotFound
    monkeypatch.setitem(sys.modules, "google.api_core", api_core_mod)
    monkeypatch.setitem(sys.modules, "google.api_core.exceptions", exceptions_mod)

    # ensure clean import
    if "grocery_services" in sys.modules:
        del sys.modules["grocery_services"]
    gs = importlib.import_module("grocery_services")

    # replace the Firestore collection with our fake implementation
    fake_collection = FakeCollection()
    monkeypatch.setattr(gs, "FS_COLLECTION_GROCERY_LISTS", fake_collection)
    monkeypatch.setattr(gs, "FS_COLLECTION_GROCERY_GROUPS", FakeCollection())
    monkeypatch.setattr(gs, "firestore", types.SimpleNamespace(ArrayUnion=FakeArrayUnion))
    return gs

# ---- Tests ----

def test_grocery_list_flow(gs_module):
    gs = gs_module
    user_id = 42

    # initially empty
    result = asyncio.run(gs.get_grocery_list(user_id))
    assert result == []


def test_merge_grocery_lists(gs_module):
    gs = gs_module
    user_a = 1
    user_b = 2
    asyncio.run(gs.add_to_grocery_list(user_a, ["apples"]))
    asyncio.run(gs.add_to_grocery_list(user_b, ["bananas"]))
    success = asyncio.run(gs.merge_grocery_lists(user_a, user_b))
    assert success
    list_a = asyncio.run(gs.get_grocery_list(user_a))
    list_b = asyncio.run(gs.get_grocery_list(user_b))
    assert sorted(list_a) == sorted(list_b) == ["apples", "bananas"]
    asyncio.run(gs.add_to_grocery_list(user_a, ["carrots"]))
    list_b_after = asyncio.run(gs.get_grocery_list(user_b))
    assert "carrots" in list_b_after
