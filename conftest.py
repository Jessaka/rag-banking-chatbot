import asyncio
import pytest

# Initialize a global event loop for the test session
_global_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_global_loop)

# Provide an event loop fixture for async tests (used by pytest-asyncio)
@pytest.fixture(scope="session")
def event_loop():
    loop = _global_loop
    yield loop
    loop.close()

