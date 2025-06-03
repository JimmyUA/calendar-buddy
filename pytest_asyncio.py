import asyncio
import inspect
import pytest

def fixture(*args, **kwargs):
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @pytest.fixture(*args, **kwargs)
            def wrapper(*w_args, **w_kwargs):
                return asyncio.run(func(*w_args, **w_kwargs))
            return wrapper
        return pytest.fixture(*args, **kwargs)(func)
    return decorator

def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test to run asynchronously")


def pytest_pyfunc_call(pyfuncitem):
    if pyfuncitem.get_closest_marker("asyncio"):
        func = pyfuncitem.obj
        if inspect.iscoroutinefunction(func):
            asyncio.run(func(**pyfuncitem.funcargs))
            return True
    return None
