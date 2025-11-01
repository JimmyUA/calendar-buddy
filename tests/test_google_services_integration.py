import sys
import types
import importlib
import asyncio
import uuid

import pytest

# Fake Firestore implementation
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
    def get(self, key):
        return self._data.get(key) if self._data else None

class FakeDocument:
    def __init__(self, collection, doc_id):
        self.collection = collection
        self.doc_id = doc_id
    def get(self, **kwargs):
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
    def update(self, data):
        existing = self.collection.store.get(self.doc_id, {})
        existing.update(data)
        self.collection.store[self.doc_id] = existing
    def collection(self, name):
        return self.collection.subcollections.setdefault((self.doc_id, name), FakeCollection())

class FakeCollection:
    def __init__(self):
        self.store = {}
        self.subcollections = {}
    def document(self, doc_id=None):
        doc_id = doc_id or str(uuid.uuid4())
        return FakeDocument(self, doc_id)

class FakeTransaction:
    def delete(self, doc_ref):
        doc_ref.delete()

class FakeDB:
    def __init__(self):
        self.collections = {}
    def collection(self, name):
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]
    def transaction(self):
        return FakeTransaction()

@pytest.fixture
def gs_module(monkeypatch):
    # stub config
    config_mod = types.ModuleType("config")
    config_mod.FIRESTORE_DB = FakeDB()
    config_mod.FS_COLLECTION_PREFS = "prefs"
    config_mod.FS_COLLECTION_PENDING_EVENTS = "pe"
    config_mod.FS_COLLECTION_PENDING_DELETIONS = "pd"
    config_mod.FS_COLLECTION_STATES = "states"
    config_mod.FS_COLLECTION_TOKENS = "tokens"
    config_mod.FS_COLLECTION_CALENDAR_ACCESS_REQUESTS = "car"
    config_mod.FS_COLLECTION_GROCERY_LISTS = "grocery"
    config_mod.FS_COLLECTION_GROCERY_LIST_GROUPS = "groups"
    config_mod.FS_COLLECTION_GROCERY_SHARE_REQUESTS = "share"
    config_mod.FS_COLLECTION_LC_CHAT_HISTORIES = "lc"
    config_mod.FS_COLLECTION_GENERAL_CHAT_HISTORIES = "gc"
    config_mod.GOOGLE_CALENDAR_SCOPES = []
    config_mod.OAUTH_REDIRECT_URI = "http://localhost"
    config_mod.MAX_HISTORY_MESSAGES = 5
    monkeypatch.setitem(sys.modules, "config", config_mod)

    # dummy pytz
    pytz_mod = types.ModuleType("pytz")
    class UnknownTimeZoneError(Exception):
        pass

    def timezone(name: str):
        if name == "UTC":
            return name
        raise UnknownTimeZoneError

    pytz_mod.UnknownTimeZoneError = UnknownTimeZoneError
    pytz_mod.timezone = timezone
    pytz_mod.utc = "UTC"
    monkeypatch.setitem(sys.modules, "pytz", pytz_mod)
    monkeypatch.setitem(sys.modules, "pytz.exceptions", types.SimpleNamespace(UnknownTimeZoneError=UnknownTimeZoneError))

    # minimal dateutil
    dateutil_pkg = types.ModuleType("dateutil")
    parser_mod = types.ModuleType("dateutil.parser")
    parser_mod.isoparse = lambda s: s
    monkeypatch.setitem(sys.modules, "dateutil", dateutil_pkg)
    monkeypatch.setitem(sys.modules, "dateutil.parser", parser_mod)

    # minimal pydantic
    pydantic_mod = types.ModuleType("pydantic")
    class BaseModel:
        pass
    pydantic_mod.BaseModel = BaseModel
    monkeypatch.setitem(sys.modules, "pydantic", pydantic_mod)

    # google packages
    google_pkg = types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    google_pkg.cloud = types.ModuleType("google.cloud")
    monkeypatch.setitem(sys.modules, "google.cloud", google_pkg.cloud)
    firestore_mod = types.ModuleType("google.cloud.firestore")
    firestore_mod.ArrayUnion = FakeArrayUnion
    firestore_mod.SERVER_TIMESTAMP = object()
    firestore_mod.Query = types.SimpleNamespace(DESCENDING="DESC")
    firestore_mod.transactional = lambda f: f
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

    services_mod = types.ModuleType("services")
    pending_mod = types.ModuleType("services.pending")
    prefs_mod = types.ModuleType("services.preferences")
    async def async_true(*args, **kwargs):
        return True

    # a bit of a hack to simulate the firestore db
    db = {"pe": {}, "pd": {}, "prefs": {}}

    async def add_pending_event(user_id, event_data):
        db["pe"][user_id] = event_data
        return True
    async def get_pending_event(user_id):
        return db["pe"].get(user_id)
    async def delete_pending_event(user_id):
        db["pe"].pop(user_id, None)
        return True
    async def add_pending_deletion(user_id, deletion_data):
        db["pd"][user_id] = deletion_data
        return True
    async def get_pending_deletion(user_id):
        return db["pd"].get(user_id)
    async def delete_pending_deletion(user_id):
        db["pd"].pop(user_id, None)
        return True
    async def set_user_timezone(user_id, timezone_str):
        if timezone_str == "Invalid/Zone":
            return False
        db["prefs"][user_id] = timezone_str
        return True
    async def get_user_timezone_str(user_id):
        return db["prefs"].get(user_id)

    pending_mod.add_pending_event = add_pending_event
    pending_mod.get_pending_event = get_pending_event
    pending_mod.delete_pending_event = delete_pending_event
    pending_mod.add_pending_deletion = add_pending_deletion
    pending_mod.get_pending_deletion = get_pending_deletion
    pending_mod.delete_pending_deletion = delete_pending_deletion
    prefs_mod.set_user_timezone = set_user_timezone
    prefs_mod.get_user_timezone_str = get_user_timezone_str
    services_mod.pending = pending_mod
    services_mod.preferences = prefs_mod
    monkeypatch.setitem(sys.modules, "services", services_mod)
    monkeypatch.setitem(sys.modules, "services.pending", pending_mod)
    monkeypatch.setitem(sys.modules, "services.preferences", prefs_mod)

    if "google_services" in sys.modules:
        del sys.modules["google_services"]
    if "server.google_services" in sys.modules:
        del sys.modules["server.google_services"]
    gs = importlib.import_module("server.google_services")
    return gs

# ---- Tests ----

def test_pending_event_flow(gs_module):
    gs = gs_module
    user_id = 1
    event = {"id": "abc"}
    assert asyncio.run(gs.add_pending_event(user_id, event))
    fetched = asyncio.run(gs.get_pending_event(user_id))
    assert fetched == event
    assert asyncio.run(gs.delete_pending_event(user_id))
    assert asyncio.run(gs.get_pending_event(user_id)) is None


def test_pending_deletion_flow(gs_module):
    gs = gs_module
    user_id = 1
    deletion = {"event_id": "xyz"}
    assert asyncio.run(gs.add_pending_deletion(user_id, deletion))
    fetched = asyncio.run(gs.get_pending_deletion(user_id))
    assert fetched == deletion
    assert asyncio.run(gs.delete_pending_deletion(user_id))
    assert asyncio.run(gs.get_pending_deletion(user_id)) is None


def test_timezone_set_get(gs_module):
    gs = gs_module
    user_id = 2
    assert asyncio.run(gs.set_user_timezone(user_id, "UTC"))
    assert asyncio.run(gs.get_user_timezone_str(user_id)) == "UTC"
    assert not asyncio.run(gs.set_user_timezone(user_id, "Invalid/Zone"))


def test_oauth_state_flow(gs_module):
    gs = gs_module
    user_id = 3
    state = asyncio.run(gs.generate_oauth_state(user_id))
    assert state is not None
    assert gs.verify_oauth_state(state) == user_id
    # state should be consumed
    assert gs.verify_oauth_state(state) is None


def test_user_token_flow(gs_module):
    gs = gs_module
    user_id = 4
    class Creds:
        def to_json(self):
            return "{}"
    creds = Creds()
    assert asyncio.run(gs.store_user_credentials(user_id, creds))
    assert asyncio.run(gs.is_user_connected(user_id))
    assert asyncio.run(gs.delete_user_token(user_id))
    assert not asyncio.run(gs.is_user_connected(user_id))
