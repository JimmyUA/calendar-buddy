from types import ModuleType
import sys

cloud = ModuleType('google.cloud')
sys.modules[__name__ + '.cloud'] = cloud

secretmanager = ModuleType('google.cloud.secretmanager')
class SecretManagerServiceClient:
    def __init__(self, *a, **k):
        pass
secretmanager.SecretManagerServiceClient = SecretManagerServiceClient
cloud.secretmanager = secretmanager
sys.modules[__name__ + '.cloud.secretmanager'] = secretmanager

api_core = ModuleType('google.api_core')
exceptions = ModuleType('google.api_core.exceptions')
class NotFound(Exception):
    pass
class GoogleAPIError(Exception):
    pass
exceptions.NotFound = NotFound
exceptions.GoogleAPIError = GoogleAPIError
api_core.exceptions = exceptions
sys.modules[__name__ + '.api_core'] = api_core
sys.modules[__name__ + '.api_core.exceptions'] = exceptions

oauth2 = ModuleType('google.oauth2')
credentials_mod = ModuleType('google.oauth2.credentials')
class Credentials:
    def __init__(self, *a, **k):
        pass
credentials_mod.Credentials = Credentials
oauth2.credentials = credentials_mod
sys.modules[__name__ + '.oauth2'] = oauth2
sys.modules[__name__ + '.oauth2.credentials'] = credentials_mod

auth_mod = ModuleType('google.auth')
transport_mod = ModuleType('google.auth.transport')
requests_mod = ModuleType('google.auth.transport.requests')
class Request:
    pass
requests_mod.Request = Request
transport_mod.requests = requests_mod
auth_mod.transport = transport_mod
sys.modules[__name__ + '.auth'] = auth_mod
sys.modules[__name__ + '.auth.transport'] = transport_mod
sys.modules[__name__ + '.auth.transport.requests'] = requests_mod

cloud_firestore = ModuleType('google.cloud.firestore')
class Client:
    def __init__(self, *a, **k):
        pass
    def collection(self, *a, **k):
        from unittest.mock import MagicMock
        return MagicMock(name='FirestoreCollection')

    class Transaction:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            pass

    def transaction(self):
        return self.Transaction()

def transactional(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

SERVER_TIMESTAMP = object()
class ArrayUnion:
    def __init__(self, items):
        self.items = items
cloud_firestore.Client = Client
cloud_firestore.SERVER_TIMESTAMP = SERVER_TIMESTAMP
cloud_firestore.ArrayUnion = ArrayUnion
cloud.firestore = cloud_firestore
sys.modules[__name__ + '.cloud.firestore'] = cloud_firestore
cloud_firestore.transactional = transactional

fs_v1 = ModuleType('google.cloud.firestore_v1')
base_query = ModuleType('google.cloud.firestore_v1.base_query')
class FieldFilter:
    def __init__(self, *a, **k):
        pass
base_query.FieldFilter = FieldFilter
fs_v1.base_query = base_query
sys.modules[__name__ + '.cloud.firestore_v1'] = fs_v1
sys.modules[__name__ + '.cloud.firestore_v1.base_query'] = base_query

sys.modules[__name__ + '.cloud'] = cloud
