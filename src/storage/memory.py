"""In-memory implementations of CacheBackend and SessionBackend.

These are the default backends — zero dependencies, thread-safe,
and compatible with single-process deployments.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


# ======================================================================
# InMemoryCacheBackend
# ======================================================================

class InMemoryCacheBackend:
    """Thread-safe in-memory cache storage with LRU eviction.

    This is the default backend used when Redis is not configured.
    """

    def __init__(self, max_entries: int = 500) -> None:
        self._max = max_entries
        self._store: dict[str, tuple[float, dict]] = {}  # key → (expiry_monotonic, value)
        self._lock = threading.Lock()
        self._hit_count = 0
        self._miss_count = 0
        logger.info(f"InMemoryCacheBackend: max_entries={max_entries}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> dict | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._miss_count += 1
                return None
            expiry, value = entry
            if time.monotonic() > expiry:
                self._store.pop(key, None)
                self._miss_count += 1
                return None
            self._hit_count += 1
            return value

    def set(self, key: str, value: dict, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            if len(self._store) >= self._max:
                # Evict oldest entry (LRU-like: earliest expiry)
                oldest = min(self._store, key=lambda k: self._store[k][0])
                self._store.pop(oldest, None)
            expiry = time.monotonic() + ttl_seconds
            self._store[key] = (expiry, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hit_count = 0
            self._miss_count = 0
            logger.info("InMemoryCacheBackend: cleared")

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._hit_count + self._miss_count
            return {
                "backend": "in_memory",
                "entries": len(self._store),
                "max_entries": self._max,
                "hit_count": self._hit_count,
                "miss_count": self._miss_count,
                "hit_rate": round(self._hit_count / max(total, 1), 4),
            }


# ======================================================================
# InMemorySessionBackend
# ======================================================================

class InMemorySessionBackend:
    """Thread-safe in-memory session storage with TTL eviction and LRU.

    This is the default backend used when Redis is not configured.
    """

    def __init__(self, ttl_seconds: int = 3600, max_sessions: int = 50) -> None:
        self._ttl = ttl_seconds
        self._max = max_sessions
        self._store: dict[str, tuple[float, dict]] = {}  # session_id → (last_access_monotonic, data)
        self._lock = threading.Lock()
        logger.info(f"InMemorySessionBackend: ttl={ttl_seconds}s, max_sessions={max_sessions}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, session_id: str) -> dict | None:
        with self._lock:
            entry = self._store.get(session_id)
            if entry is None:
                return None
            expiry, data = entry
            if time.monotonic() > expiry + self._ttl:
                self._store.pop(session_id, None)
                return None
            # Update access time
            self._store[session_id] = (time.monotonic(), data)
            return data

    def set(self, session_id: str, data: dict, ttl_seconds: int | None = None) -> None:
        with self._lock:
            if session_id not in self._store and len(self._store) >= self._max:
                # LRU eviction of oldest session
                oldest = min(self._store, key=lambda k: self._store[k][0])
                self._store.pop(oldest, None)
                logger.debug(f"Session LRU eviction: {oldest[:8]}…")
            self._store[session_id] = (time.monotonic(), data)

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)

    def exists(self, session_id: str) -> bool:
        with self._lock:
            entry = self._store.get(session_id)
            if entry is None:
                return False
            expiry, _ = entry
            if time.monotonic() > expiry + self._ttl:
                self._store.pop(session_id, None)
                return False
            return True

    def cleanup(self) -> int:
        """Remove all expired sessions. Returns count removed."""
        removed = 0
        with self._lock:
            now = time.monotonic()
            stale = [sid for sid, (ts, _) in self._store.items() if now > ts + self._ttl]
            for sid in stale:
                self._store.pop(sid, None)
                removed += 1
        if removed:
            logger.info(f"InMemorySessionBackend: cleaned {removed} stale sessions")
        return removed

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "backend": "in_memory",
                "active_sessions": len(self._store),
                "max_sessions": self._max,
                "ttl_seconds": self._ttl,
            }
