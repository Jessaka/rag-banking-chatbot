"""Redis-backed implementations of CacheBackend and SessionBackend.

These are optional backends — if Redis is unavailable they log a warning
and the application continues using the in-memory default.

Requires: redis>=5.0 (pip install redis)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

_REDIS_AVAILABLE: bool = False
_REDIS_IMPORT_ERROR: str | None = None

try:
    import redis.asyncio as aioredis
    from redis import Redis as SyncRedis
    from redis.exceptions import ConnectionError as RedisConnectionError, RedisError

    _REDIS_AVAILABLE = True
except ImportError as exc:
    _REDIS_AVAILABLE = False
    _REDIS_IMPORT_ERROR = str(exc)
    RedisConnectionError = Exception
    RedisError = Exception


# ======================================================================
# Redis connection helper
# ======================================================================

_REDIS_CLIENT: Any | None = None


def _get_redis_client() -> Any | None:
    """Return a Redis client or None if unavailable.

    The client is lazily initialized on first call. If Redis is not
    available (import error or connection error), None is returned
    and a warning is logged once.
    """
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT
    if not _REDIS_AVAILABLE:
        logger.warning(f"Redis unavailable (import error: {_REDIS_IMPORT_ERROR}) — falling back to in-memory")
        return None

    import config
    try:
        _REDIS_CLIENT = SyncRedis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            password=config.REDIS_PASSWORD or None,
            db=config.REDIS_DB,
            socket_connect_timeout=config.REDIS_TIMEOUT,
            decode_responses=True,
        )
        _REDIS_CLIENT.ping()
        logger.info(f"Redis connected: {config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}")
        return _REDIS_CLIENT
    except RedisError as exc:
        logger.warning(f"Redis connection failed ({exc}) — falling back to in-memory")
        _REDIS_CLIENT = None
        return None


# ======================================================================
# RedisCacheBackend
# ======================================================================

class RedisCacheBackend:
    """Redis-backed cache storage.

    Graceful degradation: if Redis is unavailable at runtime, all
    operations silently no-op (return None / do nothing) so the
    application continues with in-memory fallback.
    """

    def __init__(self, key_prefix: str = "rag:cache:") -> None:
        self._prefix = key_prefix
        self._client: Any | None = None
        self._hit_count = 0
        self._miss_count = 0
        logger.info(f"RedisCacheBackend: prefix='{key_prefix}'")

    def _redis(self) -> Any | None:
        if self._client is None:
            self._client = _get_redis_client()
        return self._client

    def _pkey(self, key: str) -> str:
        return f"{self._prefix}{key}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> dict | None:
        r = self._redis()
        if r is None:
            self._miss_count += 1
            return None
        try:
            raw = r.get(self._pkey(key))
            if raw is None:
                self._miss_count += 1
                return None
            self._hit_count += 1
            return json.loads(raw)
        except RedisError:
            self._miss_count += 1
            return None

    def set(self, key: str, value: dict, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        r = self._redis()
        if r is None:
            return
        try:
            r.setex(self._pkey(key), ttl_seconds, json.dumps(value, default=str))
        except RedisError:
            pass

    def delete(self, key: str) -> None:
        r = self._redis()
        if r is None:
            return
        try:
            r.delete(self._pkey(key))
        except RedisError:
            pass

    def clear(self) -> None:
        r = self._redis()
        if r is None:
            return
        try:
            for k in r.scan_iter(match=f"{self._prefix}*"):
                r.delete(k)
        except RedisError:
            pass

    @property
    def stats(self) -> dict[str, Any]:
        r = self._redis()
        entries = 0
        if r is not None:
            try:
                entries = len(list(r.scan_iter(match=f"{self._prefix}*")))
            except RedisError:
                pass
        total = self._hit_count + self._miss_count
        return {
            "backend": "redis" if r is not None else "redis_unavailable",
            "entries": entries,
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": round(self._hit_count / max(total, 1), 4),
        }


# ======================================================================
# RedisSessionBackend
# ======================================================================

class RedisSessionBackend:
    """Redis-backed session storage.

    Graceful degradation: if Redis is unavailable, all operations
    silently no-op so the application continues with in-memory fallback.
    """

    def __init__(self, key_prefix: str = "rag:session:") -> None:
        self._prefix = key_prefix
        self._client: Any | None = None
        logger.info(f"RedisSessionBackend: prefix='{key_prefix}'")

    def _redis(self) -> Any | None:
        if self._client is None:
            self._client = _get_redis_client()
        return self._client

    def _pkey(self, key: str) -> str:
        return f"{self._prefix}{key}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, session_id: str) -> dict | None:
        r = self._redis()
        if r is None:
            return None
        try:
            raw = r.get(self._pkey(session_id))
            if raw is None:
                return None
            return json.loads(raw)
        except RedisError:
            return None

    def set(self, session_id: str, data: dict, ttl_seconds: int | None = None) -> None:
        r = self._redis()
        if r is None:
            return
        try:
            if ttl_seconds:
                r.setex(self._pkey(session_id), ttl_seconds, json.dumps(data, default=str))
            else:
                r.set(self._pkey(session_id), json.dumps(data, default=str))
        except RedisError:
            pass

    def delete(self, session_id: str) -> None:
        r = self._redis()
        if r is None:
            return
        try:
            r.delete(self._pkey(session_id))
        except RedisError:
            pass

    def exists(self, session_id: str) -> bool:
        r = self._redis()
        if r is None:
            return False
        try:
            return r.exists(self._pkey(session_id)) > 0
        except RedisError:
            return False

    def cleanup(self) -> int:
        """Redis handles TTL automatically; this is a no-op."""
        return 0

    @property
    def stats(self) -> dict[str, Any]:
        r = self._redis()
        entries = 0
        if r is not None:
            try:
                entries = len(list(r.scan_iter(match=f"{self._prefix}*")))
            except RedisError:
                pass
        return {
            "backend": "redis" if r is not None else "redis_unavailable",
            "active_sessions": entries,
        }
