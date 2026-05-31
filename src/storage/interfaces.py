"""Abstract interfaces for pluggable storage backends.

These protocols define the contract for cache and session storage,
allowing in-memory, Redis, or any future backend to be swapped in.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CacheBackend(Protocol):
    """Interface for response cache storage."""

    def get(self, key: str) -> dict | None:
        """Return cached result dict or None (on miss or expiry)."""
        ...

    def set(self, key: str, value: dict, ttl_seconds: int) -> None:
        """Store a value with TTL.

        Args:
            key: Cache key string.
            value: The result dict to cache.
            ttl_seconds: Time-to-live in seconds for this entry.
        """
        ...

    def delete(self, key: str) -> None:
        """Remove a single entry from cache."""
        ...

    def clear(self) -> None:
        """Remove all entries (for testing / admin)."""
        ...

    @property
    def stats(self) -> dict[str, Any]:
        """Return diagnostic stats: entries, hit_count, miss_count, hit_rate."""
        ...


@runtime_checkable
class SessionBackend(Protocol):
    """Interface for session storage (conversation state)."""

    def get(self, session_id: str) -> dict | None:
        """Return session data dict or None if session does not exist."""
        ...

    def set(self, session_id: str, data: dict, ttl_seconds: int | None = None) -> None:
        """Store session data with optional TTL."""
        ...

    def delete(self, session_id: str) -> None:
        """Remove a session."""
        ...

    def exists(self, session_id: str) -> bool:
        """Check if a session exists without loading data."""
        ...

    def cleanup(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        ...

    @property
    def stats(self) -> dict[str, Any]:
        """Return diagnostic stats: active_sessions, etc."""
        ...
