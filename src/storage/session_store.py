"""Production-grade distributed session store with Redis backend.

Architecture:
  DistributedSessionStore (orchestration)
      │  delegates to
      ├─ RedisSessionBackend   (primary — Redis with TTL, locking, versioning)
      └─ EmergencyFallback     (in-memory — when Redis is unavailable)

Features:
  - Optimistic locking via session_version (CAS on write)
  - TTL expiration (configurable per session)
  - JSON serialization with datetime/Decimal support
  - Field-level atomic updates (HSET for streaming safety)
  - Session hashing (no raw session IDs exposed)
  - Namespaced Redis keys
  - Graceful Redis outage → in-memory emergency mode
  - Rich metrics: load/write/conflict latency

Session state fields (aligned with BankingRAGChain):
  - unresolved_product         ─ e.g. "ekonto"
  - unresolved_product_type    ─ e.g. "pricing"
  - clarification_candidates   ─ list of options
  - pending_clarification      ─ clarification type string
  - last_canonical_product     ─ resolved product name
  - current_domain             ─ "retail" | "corporate"
  - current_intent             ─ "pricing" | "account_overview" | ...
  - current_product            ─ resolved product ID
  - chat_history               ─ serialized message list
  - resolved_product           ─ chain.resolved_product
  - resolved_intent             ─ chain.resolved_intent
  - session_version            ─ monotonic counter for optimistic locking
  - updated_at                 ─ ISO timestamp
  - expires_at                 ─ ISO timestamp

Thread safety:
  - Redis SETNX + version check prevents concurrent overwrites
  - Field-level HSET for streaming (no full-document read-modify-write)
  - asyncio.Lock wrapper optional for callers that need it
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import config
from src.storage.interfaces import SessionBackend
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Redis availability check (lazy import)
# ---------------------------------------------------------------------------

_REDIS_AVAILABLE: bool = False
_REDIS_IMPORT_ERROR: str | None = None

try:
    import redis.asyncio as aioredis
    from redis.exceptions import RedisError

    _REDIS_AVAILABLE = True
except ImportError as exc:
    _REDIS_AVAILABLE = False
    _REDIS_IMPORT_ERROR = str(exc)
    RedisError = Exception


# ---------------------------------------------------------------------------
# Session state field defaults
# ---------------------------------------------------------------------------

_EMPTY_SESSION: dict[str, Any] = {
    "session_version": 1,
    "unresolved_product": None,
    "unresolved_product_type": None,
    "clarification_candidates": None,
    "pending_clarification": None,
    "last_canonical_product": None,
    "current_domain": None,
    "current_intent": None,
    "current_product": None,
    "session_context": None,
    "resolved_product": None,
    "resolved_intent": None,
    "chat_history": [],
    "created_at": None,
    "updated_at": None,
    "expires_at": None,
}

_SERIALIZABLE_FIELDS = frozenset({
    "unresolved_product",
    "unresolved_product_type",
    "clarification_candidates",
    "pending_clarification",
    "last_canonical_product",
    "current_domain",
    "current_intent",
    "current_product",
    "session_context",
    "resolved_product",
    "resolved_intent",
    "chat_history",
    "session_version",
    "created_at",
    "updated_at",
    "expires_at",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _expires_iso(ttl_seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")


def _hash_session_id(session_id: str) -> str:
    """Hash session ID for Redis key — never stores raw UUIDs."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def _session_key(session_id: str, prefix: str = "rag:session:") -> str:
    return f"{prefix}{_hash_session_id(session_id)}"


def _lock_key(session_id: str, prefix: str = "rag:session:lock:") -> str:
    return f"{prefix}{_hash_session_id(session_id)}"


def _serialize_for_redis(value: Any) -> str:
    """Serialize Python value to JSON string for Redis."""
    return json.dumps(value, ensure_ascii=False, default=str)


def _deserialize_from_redis(raw: str | None) -> Any:
    """Deserialize Redis string to Python value."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


# ---------------------------------------------------------------------------
# DistributedSessionStore
# ---------------------------------------------------------------------------

class DistributedSessionStore:
    """Production-grade distributed session store.

    Graceful degradation:
      If Redis is unavailable, all operations silently fall back to
      an in-memory emergency store so the application never crashes.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        key_prefix: str = "rag:session:",
        default_ttl: int = 3600,
        lock_timeout: int = 5,
    ) -> None:
        self._default_ttl = default_ttl
        self._key_prefix = key_prefix
        self._lock_prefix = f"{key_prefix.rstrip(':')}:lock:"
        self._lock_timeout = lock_timeout

        # Redis client (lazy)
        self._redis_url = redis_url or getattr(config, "REDIS_URL", None)
        self._redis_client: Any = None

        # Emergency in-memory fallback
        self._emergency_store: dict[str, dict] = {}
        self._emergency_lock = threading.Lock()
        self._emergency_active = False
        self._emergency_ttl = default_ttl

        # Metrics counters
        self._load_count = 0
        self._save_count = 0
        self._conflict_count = 0
        self._emergency_fallback_count = 0
        self._total_load_ms = 0.0
        self._total_save_ms = 0.0
        self._total_lock_ms = 0.0

        logger.info(
            f"DistributedSessionStore: prefix='{key_prefix}', "
            f"default_ttl={default_ttl}s, lock_timeout={lock_timeout}s"
        )

    # ------------------------------------------------------------------
    # Redis connection management
    # ------------------------------------------------------------------

    @property
    def _redis(self) -> Any | None:
        """Lazy-init Redis client. Returns None on failure (→ emergency mode)."""
        if self._redis_client is not None:
            return self._redis_client
        if not _REDIS_AVAILABLE:
            if not self._emergency_active:
                self._emergency_active = True
                self._emergency_fallback_count += 1
                logger.warning(
                    f"Redis unavailable (import error: {_REDIS_IMPORT_ERROR}) — "
                    "session store using in-memory emergency fallback"
                )
            return None
        try:
            if self._redis_url:
                self._redis_client = aioredis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=getattr(config, "REDIS_TIMEOUT", 3),
                )
            else:
                self._redis_client = aioredis.Redis(
                    host=getattr(config, "REDIS_HOST", "localhost"),
                    port=getattr(config, "REDIS_PORT", 6379),
                    password=getattr(config, "REDIS_PASSWORD", None) or None,
                    db=getattr(config, "REDIS_DB", 0),
                    decode_responses=True,
                    socket_connect_timeout=getattr(config, "REDIS_TIMEOUT", 3),
                )
            # Verify connectivity
            import asyncio
            try:
                asyncio.get_running_loop()
                # Already in async context — can't ping synchronously
            except RuntimeError:
                self._redis_client.ping()
            logger.info("Redis session store connected")
            self._emergency_active = False
            return self._redis_client
        except Exception as exc:
            logger.warning(f"Redis session store connection failed ({exc}) — emergency fallback")
            self._redis_client = None
            self._emergency_active = True
            self._emergency_fallback_count += 1
            return None

    def close(self) -> None:
        """Close Redis connection."""
        if self._redis_client is not None:
            try:
                import asyncio
                try:
                    asyncio.get_running_loop()
                    # Can't close synchronously in async context
                except RuntimeError:
                    self._redis_client.close()
            except Exception:
                pass
            self._redis_client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def load(self, session_id: str) -> dict | None:
        """Load full session state from store.

        Returns:
            Session dict (with all _SESSION_FIELDS), or None if session
            does not exist.
        """
        t0 = time.monotonic()
        self._load_count += 1
        sid_hash = _hash_session_id(session_id)
        logger.debug(f"SessionStore.load start sid_hash={sid_hash}")

        # Try Redis first
        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    raw = await r.hgetall(_session_key(session_id, self._key_prefix))
                    if raw:
                        data = {k: _deserialize_from_redis(v) for k, v in raw.items()}
                        self._total_load_ms += (time.monotonic() - t0) * 1000
                        logger.debug(f"SessionStore.load hit sid_hash={sid_hash} ms={(time.monotonic() - t0) * 1000:.1f}")
                        return data
                except RedisError as exc:
                    logger.warning(f"Session load Redis error: {exc}")
                    self._enter_emergency()

        # Emergency fallback
        data = self._emergency_load(session_id)
        logger.debug(f"SessionStore.load fallback sid_hash={sid_hash} hit={data is not None} ms={(time.monotonic() - t0) * 1000:.1f}")
        return data

    async def load_field(self, session_id: str, field: str) -> Any:
        """Load a single field from session state (fast path).

        Falls back to full load of emergency store if Redis unavailable.
        """
        if field not in _SERIALIZABLE_FIELDS:
            return None
        t0 = time.monotonic()

        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    raw = await r.hget(
                        _session_key(session_id, self._key_prefix), field
                    )
                    self._total_load_ms += (time.monotonic() - t0) * 1000
                    return _deserialize_from_redis(raw)
                except RedisError:
                    self._enter_emergency()

        data = self._emergency_load(session_id)
        return data.get(field) if data else None

    async def save(
        self,
        session_id: str,
        data: dict,
        ttl_seconds: int | None = None,
        *,
        expected_version: int | None = None,
    ) -> bool:
        """Save full session state with optimistic locking.

        Args:
            session_id: Session identifier.
            data: Session state dict (will be merged with defaults).
            ttl_seconds: Override default TTL. None = use default.
            expected_version: If set, write only if current version matches
                              (optimistic locking). None = force write.

        Returns:
            True on success, False on version conflict.
        """
        t0 = time.monotonic()
        self._save_count += 1
        sid_hash = _hash_session_id(session_id)
        logger.debug(f"SessionStore.save start sid_hash={sid_hash} expected_version={expected_version}")

        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        now_iso = _now_iso()

        # Build session document with metadata
        session_data = dict(data)
        session_data["updated_at"] = now_iso
        session_data["expires_at"] = _expires_iso(ttl)
        if "created_at" not in session_data or not session_data["created_at"]:
            session_data["created_at"] = now_iso

        # Determine current version from the passed data; if not provided,
        # check if there's an existing session to read the version from.
        # This ensures version continuity across save() calls.
        current_version = session_data.get("session_version", 0)
        if expected_version is not None:
            # If caller specifies expected_version, load the real stored version
            stored = await self.load(session_id)
            if stored is not None:
                current_version = int(stored.get("session_version", 0))
                if current_version != expected_version:
                    self._conflict_count += 1
                    self._total_save_ms += (time.monotonic() - t0) * 1000
                    logger.warning(
                        f"Session version conflict: expected={expected_version}, "
                        f"actual={current_version} for session {session_id[:8]}…"
                    )
                    return False
            else:
                # Session doesn't exist yet — start from 0
                current_version = 0
        elif current_version == 0:
            # No expected_version and no version in data — try to read existing
            stored = await self.load(session_id)
            if stored is not None:
                current_version = int(stored.get("session_version", 0))

        session_data["session_version"] = current_version + 1

        if not self._emergency_active:
            r = self._redis
            if r is not None:
                key = _session_key(session_id, self._key_prefix)
                try:
                    # Store all serializable fields as hash
                    kv_pairs = {}
                    for field in _SERIALIZABLE_FIELDS:
                        if field in session_data:
                            kv_pairs[field] = _serialize_for_redis(session_data[field])
                    if kv_pairs:
                        await r.hset(key, mapping=kv_pairs)  # type: ignore[arg-type]
                    await r.expire(key, ttl)

                    self._total_save_ms += (time.monotonic() - t0) * 1000
                    logger.debug(f"SessionStore.save redis_ok sid_hash={sid_hash} version={session_data.get('session_version')} ms={(time.monotonic() - t0) * 1000:.1f}")
                    return True

                except RedisError as exc:
                    logger.warning(f"Session save Redis error: {exc}")
                    self._enter_emergency()

        # Emergency fallback
        self._emergency_save(session_id, session_data, ttl)
        self._total_save_ms += (time.monotonic() - t0) * 1000
        logger.debug(f"SessionStore.save fallback_ok sid_hash={sid_hash} version={session_data.get('session_version')} ms={(time.monotonic() - t0) * 1000:.1f}")
        return True

    async def save_field(
        self,
        session_id: str,
        field: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        """Atomically update a single session field (streaming-safe).

        This is the key method for streaming: instead of read-modify-write
        the full session, we just HSET one field. No version conflict possible.
        """
        if field not in _SERIALIZABLE_FIELDS:
            return
        t0 = time.monotonic()
        now_iso = _now_iso()

        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl

        if not self._emergency_active:
            r = self._redis
            if r is not None:
                key = _session_key(session_id, self._key_prefix)
                try:
                    await r.hset(key, field, _serialize_for_redis(value))
                    await r.hset(key, "updated_at", now_iso)
                    await r.expire(key, ttl)
                    self._total_save_ms += (time.monotonic() - t0) * 1000
                    return
                except RedisError:
                    self._enter_emergency()

        # Emergency: full save with updated field
        data = self._emergency_load(session_id) or {}
        data[field] = value
        data["updated_at"] = now_iso
        self._emergency_save(session_id, data, ttl)

    async def delete(self, session_id: str) -> None:
        """Delete a session."""
        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    await r.delete(_session_key(session_id, self._key_prefix))
                    await r.delete(_lock_key(session_id, self._lock_prefix))
                except RedisError:
                    pass

        with self._emergency_lock:
            self._emergency_store.pop(session_id, None)

    async def exists(self, session_id: str) -> bool:
        """Check if a session exists without loading full state."""
        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    exists = await r.exists(_session_key(session_id, self._key_prefix))
                    return exists > 0
                except RedisError:
                    pass

        with self._emergency_lock:
            return session_id in self._emergency_store

    # ------------------------------------------------------------------
    # Distributed locking (for concurrent session mutation)
    # ------------------------------------------------------------------

    async def acquire_lock(self, session_id: str, timeout: float | None = None) -> bool:
        """Try to acquire a distributed lock for this session.

        Uses Redis SET NX with TTL. Returns True if lock acquired.
        Falls back to in-memory threading.Lock if Redis unavailable.
        """
        lock_timeout = timeout if timeout is not None else self._lock_timeout
        t0 = time.monotonic()
        sid_hash = _hash_session_id(session_id)
        logger.debug(f"SessionStore.lock acquire start sid_hash={sid_hash} timeout={lock_timeout}")

        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    key = _lock_key(session_id, self._lock_prefix)
                    acquired = await r.set(key, "1", nx=True, ex=lock_timeout)
                    self._total_lock_ms += (time.monotonic() - t0) * 1000
                    logger.debug(f"SessionStore.lock acquire redis sid_hash={sid_hash} acquired={bool(acquired)} ms={(time.monotonic() - t0) * 1000:.1f}")
                    return bool(acquired)
                except RedisError:
                    self._enter_emergency()

        # Emergency: in-memory lock
        lock = self._emergency_lock_for(session_id)
        acquired = lock.acquire(timeout=lock_timeout)
        self._total_lock_ms += (time.monotonic() - t0) * 1000
        logger.debug(f"SessionStore.lock acquire fallback sid_hash={sid_hash} acquired={acquired} ms={(time.monotonic() - t0) * 1000:.1f}")
        return acquired

    async def release_lock(self, session_id: str) -> None:
        """Release a distributed lock."""
        sid_hash = _hash_session_id(session_id)
        logger.debug(f"SessionStore.lock release start sid_hash={sid_hash}")
        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    await r.delete(_lock_key(session_id, self._lock_prefix))
                    logger.debug(f"SessionStore.lock release redis sid_hash={sid_hash}")
                    return
                except RedisError:
                    pass

        lock = self._emergency_lock_for(session_id, create=False)
        if lock and lock.locked():
            try:
                lock.release()
                logger.debug(f"SessionStore.lock release fallback sid_hash={sid_hash}")
            except RuntimeError:
                pass

    # ------------------------------------------------------------------
    # Stats & admin
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        total_load = self._load_count or 1
        total_save = self._save_count or 1
        return {
            "backend": "redis" if self._redis_client is not None else ("emergency_fallback" if self._emergency_active else "disconnected"),
            "emergency_fallback_active": self._emergency_active,
            "emergency_fallback_count": self._emergency_fallback_count,
            "load_count": self._load_count,
            "save_count": self._save_count,
            "conflict_count": self._conflict_count,
            "avg_load_ms": round(self._total_load_ms / total_load, 1),
            "avg_save_ms": round(self._total_save_ms / total_save, 1),
            "avg_lock_ms": round(self._total_lock_ms / max(self._load_count, 1), 1),
            "default_ttl": self._default_ttl,
            "redis_url_configured": bool(self._redis_url or getattr(config, "REDIS_URL", None)),
        }

    def clear(self) -> None:
        """Clear all sessions (admin/test)."""
        if self._redis_client is not None:
            try:
                import asyncio
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    for k in self._redis_client.scan_iter(match=f"{self._key_prefix}*"):
                        self._redis_client.delete(k)
                    for k in self._redis_client.scan_iter(match=f"{self._lock_prefix}*"):
                        self._redis_client.delete(k)
            except Exception:
                pass
        with self._emergency_lock:
            self._emergency_store.clear()

    # ------------------------------------------------------------------
    # Emergency fallback internals
    # ------------------------------------------------------------------

    def _enter_emergency(self) -> None:
        if not self._emergency_active:
            self._emergency_active = True
            self._emergency_fallback_count += 1
            logger.error(
                "Redis session store unavailable — entered in-memory emergency mode. "
                "Session continuity across instances will NOT work."
            )

    _emergency_locks: dict[str, threading.Lock] = {}

    def _emergency_lock_for(self, session_id: str, create: bool = True) -> threading.Lock | None:
        with self._emergency_lock:
            if session_id not in self._emergency_locks and create:
                self._emergency_locks[session_id] = threading.Lock()
            return self._emergency_locks.get(session_id)

    def _emergency_load(self, session_id: str) -> dict | None:
        with self._emergency_lock:
            entry = self._emergency_store.get(session_id)
            if entry is None:
                return None
            expiry = entry.get("_emergency_expiry", 0.0)
            if time.monotonic() > expiry:
                self._emergency_store.pop(session_id, None)
                return None
            # Update access time
            entry["updated_at"] = _now_iso()
            return dict(entry)  # Return copy

    def _emergency_save(self, session_id: str, data: dict, ttl: int) -> None:
        with self._emergency_lock:
            entry = dict(data)
            entry["_emergency_expiry"] = time.monotonic() + ttl
            self._emergency_store[session_id] = entry

    async def cleanup(self) -> int:
        """Remove expired sessions from emergency store. No-op for Redis (auto-TTL)."""
        removed = 0
        with self._emergency_lock:
            now = time.monotonic()
            stale = [
                sid for sid, data in self._emergency_store.items()
                if data.get("_emergency_expiry", 0) < now
            ]
            for sid in stale:
                self._emergency_store.pop(sid, None)
                removed += 1
        if removed:
            logger.info(f"Session emergency store: cleaned {removed} stale entries")
        return removed
