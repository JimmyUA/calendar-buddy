import pytest
from unittest import mock

class SimpleMocker:
    def __init__(self):
        self.patch = mock.patch
        self.patch.object = mock.patch.object
        self.patch.dict = mock.patch.dict

    def __getattr__(self, name):
        return getattr(mock, name)

@pytest.fixture
def mocker():
    return SimpleMocker()
