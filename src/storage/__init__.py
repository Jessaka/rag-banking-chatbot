"""Pluggable storage backends for cache and session state.

Usage:
    from src.storage.interfaces import CacheBackend, SessionBackend
    from src.storage.memory import InMemoryCacheBackend, InMemorySessionBackend
    from src.storage.session_store import DistributedSessionStore
    from src.storage.response_cache import DistributedResponseCache, build_cache_key

    # Production distributed stores (Redis + graceful fallback)
    session_store = DistributedSessionStore(default_ttl=3600)
    response_cache = DistributedResponseCache()
"""

from src.storage.interfaces import CacheBackend, SessionBackend
from src.storage.memory import InMemoryCacheBackend, InMemorySessionBackend
from src.storage.session_store import DistributedSessionStore
from src.storage.response_cache import DistributedResponseCache, build_cache_key
