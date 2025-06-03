from unittest.mock import MagicMock

def build(*args, **kwargs):
    return MagicMock(name='GoogleAPIBuild')
