"""Production-grade distributed response cache with unified governance.

Architecture:
  DistributedResponseCache (orchestration)
      │  delegates to
      ├─ RedisCacheBackend     (primary — Redis with TTL, namespaces, compression)
      └─ EmergencyFallback      (in-memory LRU — when Redis is unavailable)

Cache key governance:
  Every key encodes the namespace, canonical query, product context, and
  pricing version so that different products never poison each other's cache.

  Key format:  rag:cache:{namespace}:{product_hash}:{pricing_version}:{query_hash}

Namespaces (per strategy):
  - identity    — TTL: 24h  — user identity / greeting responses
  - overview    — TTL: 6h   — account overview / balance
  - pricing     — TTL: 15m  — pricing queries (fast invalidate on rate changes)
  - unsupported — TTL: 0    — never cache (marker only)
  - clarification — TTL: 0  — never cache

Per-strategy cache policy:
  - identity → long TTL (86400s), high compression threshold
  - overview → medium TTL (21600s), moderate compression
  - pricing → short TTL (900s), compressed
  - unsupported → never cache
  - clarification → never cache

Distributed safety:
  - In-flight deduplication via Redis SET NX (cross-worker dedup — best effort)
  - Graceful degradation: in-memory LRU fallback
  - Cache key normalization prevents fragment misses
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Callable

import config
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
# Cache policy
# ---------------------------------------------------------------------------

_CACHE_POLICY: dict[str, dict[str, int | bool]] = {
    "identity": {"ttl": 86400, "compress_threshold": 2048},
    "overview": {"ttl": 21600, "compress_threshold": 1024},
    "pricing": {"ttl": 900, "compress_threshold": 512},
    "unsupported": {"ttl": 0, "never_cache": True},
    "clarification": {"ttl": 0, "never_cache": True},
}

_DEFAULT_NAMESPACE = "pricing"

_NAMESPACES_THAT_CACHE = frozenset({"identity", "overview", "pricing"})

# ---------------------------------------------------------------------------
# Compression helpers
# ---------------------------------------------------------------------------

try:
    import zlib

    _COMPRESSION_AVAILABLE = True
except ImportError:
    _COMPRESSION_AVAILABLE = False


def _maybe_compress(value: str, threshold: int) -> tuple[int, bytes | str]:
    """Compress with zlib if value exceeds threshold.

    Returns (flag, data) where flag=1 means compressed, 0 means raw.
    """
    if not _COMPRESSION_AVAILABLE:
        return 0, value
    encoded = value.encode("utf-8")
    if len(encoded) < threshold:
        return 0, encoded
    compressed = zlib.compress(encoded, level=6)
    if len(compressed) < len(encoded):
        return 1, compressed
    return 0, encoded


def _maybe_decompress(flag: int, data: bytes) -> str:
    if flag and _COMPRESSION_AVAILABLE:
        try:
            return zlib.decompress(data).decode("utf-8")
        except Exception:
            pass
    if isinstance(data, bytes):
        return data.decode("utf-8")
    return str(data)


# ---------------------------------------------------------------------------
# Cache key helpers
# ---------------------------------------------------------------------------

def _normalize_query(query: str) -> str:
    """Normalize a query string for cache key consistency.

    - Lowercase
    - Strip punctuation
    - Collapse whitespace
    - Remove common filler words (a, an, the, prosím, etc.)
    """
    import re

    text = query.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    # Remove common filler words
    fillers = {"a", "an", "the", "prosím", "mohl", "bych", "chtěl", "by", "si", "se"}
    words = [w for w in text.split() if w not in fillers]
    return " ".join(words) if words else text


def _hash_key(parts: list[str]) -> str:
    raw = ":".join(str(p) for p in parts if p)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_cache_key(
    namespace: str,
    query: str,
    canonical_product: str | None = None,
    pricing_version: str | None = None,
    session_id: str | None = None,
) -> str:
    """Build a governed cache key for a response.

    Key format (Redis):
        rag:cache:{namespace}:{product_hash}:{pricing_version}:{query_hash}

    This prevents cache poisoning between products.
    """
    ns = namespace if namespace in _CACHE_POLICY else _DEFAULT_NAMESPACE
    q_hash = _hash_key([_normalize_query(query)])

    # Product-aware key
    if canonical_product and canonical_product not in ("unknown", "None", ""):
        prod_part = _hash_key([canonical_product.lower().replace(" ", "_")])
    else:
        prod_part = "none"

    if pricing_version and pricing_version not in ("unknown", "None", ""):
        ver_part = pricing_version.replace(" ", "_")
    else:
        ver_part = "v0"

    # If session_id is present, make key session-aware (for personalization)
    sid_part = _hash_key([session_id[:16]]) if session_id else None

    parts = ["rag:cache", ns, prod_part, ver_part, q_hash]
    if sid_part:
        parts.append(sid_part)

    return ":".join(parts)


def parse_cache_key(key: str) -> dict[str, str]:
    """Inverse of build_cache_key — for telemetry/troubleshooting."""
    parts = key.split(":")
    result: dict[str, str] = {}
    if len(parts) >= 5:
        result["prefix"] = parts[0]
        result["namespace"] = parts[2]
        result["product_hash"] = parts[3]
        result["pricing_version"] = parts[4]
        result["query_hash"] = parts[5] if len(parts) > 5 else ""
        result["session_id"] = parts[6] if len(parts) > 6 else ""
    return result


# ---------------------------------------------------------------------------
# DistributedResponseCache
# ---------------------------------------------------------------------------

class DistributedResponseCache:
    """Production-grade distributed response cache with unified governance.

    Provides:
      - Per-strategy TTL (from _CACHE_POLICY)
      - Query normalization for cache key consistency
      - Product-aware cache keys (no cross-contamination)
      - Pricing-version awareness
      - Session-aware keys (optional)
      - In-flight dedup across workers (Redis SET NX)
      - Graceful degradation to in-memory LRU
      - Compression for large payloads
      - Rich metrics: hit rate, latency, namespace distribution
    """

    def __init__(
        self,
        redis_url: str | None = None,
        key_prefix: str = "rag:cache",
        inflight_ttl: int = 30,
    ) -> None:
        self._key_prefix = key_prefix
        self._inflight_ttl = inflight_ttl

        # Redis client (lazy)
        self._redis_url = redis_url or getattr(config, "REDIS_URL", None)
        self._redis_client: Any = None

        # Emergency in-memory LRU
        self._emergency_cache: dict[str, tuple[float, str]] = {}
        self._emergency_max = 500
        self._emergency_lock = threading.Lock()
        self._emergency_active = False
        self._emergency_fallback_count = 0

        # In-flight dedup (local, best-effort)
        self._inflight_local: dict[str, threading.Event] = {}

        # Metrics
        self._hit_count = 0
        self._miss_count = 0
        self._inflight_hit_count = 0
        self._set_count = 0
        self._delete_count = 0
        self._total_get_ms = 0.0
        self._total_set_ms = 0.0
        self._namespace_hits: dict[str, int] = {}
        self._namespace_misses: dict[str, int] = {}

        logger.info(
            f"DistributedResponseCache: prefix='{key_prefix}', "
            f"inflight_ttl={inflight_ttl}s"
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
                    "response cache using in-memory emergency fallback"
                )
            return None
        try:
            if self._redis_url:
                self._redis_client = aioredis.from_url(
                    self._redis_url,
                    decode_responses=False,  # keep bytes for compression
                    socket_connect_timeout=getattr(config, "REDIS_TIMEOUT", 3),
                )
            else:
                self._redis_client = aioredis.Redis(
                    host=getattr(config, "REDIS_HOST", "localhost"),
                    port=getattr(config, "REDIS_PORT", 6379),
                    password=getattr(config, "REDIS_PASSWORD", None) or None,
                    db=getattr(config, "REDIS_DB", 0),
                    decode_responses=False,
                    socket_connect_timeout=getattr(config, "REDIS_TIMEOUT", 3),
                )
            # Verify connectivity
            import asyncio
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                self._redis_client.ping()
            logger.info("Redis response cache connected")
            self._emergency_active = False
            return self._redis_client
        except Exception as exc:
            logger.warning(f"Redis response cache connection failed ({exc}) — emergency fallback")
            self._redis_client = None
            self._emergency_active = True
            self._emergency_fallback_count += 1
            return None

    def close(self) -> None:
        if self._redis_client is not None:
            try:
                import asyncio
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    self._redis_client.close()
            except Exception:
                pass
            self._redis_client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_policy(self, namespace: str) -> dict[str, Any]:
        """Get cache policy for a namespace (TTL, never_cache, etc.)."""
        return dict(_CACHE_POLICY.get(namespace, _CACHE_POLICY[_DEFAULT_NAMESPACE]))

    def should_cache(self, namespace: str) -> bool:
        """Check if a namespace should be cached at all."""
        return namespace in _NAMESPACES_THAT_CACHE

    def get_ttl(self, namespace: str) -> int:
        """Get TTL in seconds for a namespace."""
        policy = _CACHE_POLICY.get(namespace, _CACHE_POLICY[_DEFAULT_NAMESPACE])
        return int(policy.get("ttl", 900))

    def get_compress_threshold(self, namespace: str) -> int:
        policy = _CACHE_POLICY.get(namespace, _CACHE_POLICY[_DEFAULT_NAMESPACE])
        return int(policy.get("compress_threshold", 1024))

    # ------------------------------------------------------------------
    # Cache operations
    # ------------------------------------------------------------------

    async def get(
        self,
        namespace: str,
        query: str,
        canonical_product: str | None = None,
        pricing_version: str | None = None,
        session_id: str | None = None,
    ) -> str | None:
        """Get cached response.

        Returns deserialized response string, or None on miss.
        """
        key = build_cache_key(namespace, query, canonical_product, pricing_version, session_id)
        return await self._get_by_key(key, namespace)

    async def _get_by_key(self, key: str, namespace: str) -> str | None:
        """Internal: get by pre-built key."""
        t0 = time.monotonic()

        # Check local in-flight first
        inflight_event = self._inflight_local.get(key)
        if inflight_event is not None:
            inflight_event.wait(timeout=self._inflight_ttl)
            self._inflight_hit_count += 1
            # Fall through to Redis for the actual value

        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    raw: bytes | None = await r.get(key)
                    self._total_get_ms += (time.monotonic() - t0) * 1000
                    if raw is not None and len(raw) > 0:
                        # First byte is compression flag, rest is data
                        flag = int(raw[0]) if len(raw) > 0 else 0
                        data = raw[1:] if len(raw) > 1 else b""
                        result = _maybe_decompress(flag, data)
                        self._hit_count += 1
                        if namespace not in self._namespace_hits:
                            self._namespace_hits[namespace] = 0
                        self._namespace_hits[namespace] += 1
                        return result
                    self._miss_count += 1
                    if namespace not in self._namespace_misses:
                        self._namespace_misses[namespace] = 0
                    self._namespace_misses[namespace] += 1
                    return None
                except RedisError:
                    self._enter_emergency()

        # Emergency fallback
        return self._emergency_get(key, namespace)

    def _emergency_get(self, key: str, namespace: str) -> str | None:
        with self._emergency_lock:
            entry = self._emergency_cache.get(key)
            if entry is None:
                self._miss_count += 1
                if namespace not in self._namespace_misses:
                    self._namespace_misses[namespace] = 0
                self._namespace_misses[namespace] += 1
                return None
            expiry, value = entry
            if time.monotonic() > expiry:
                self._emergency_cache.pop(key, None)
                self._miss_count += 1
                return None
            self._hit_count += 1
            if namespace not in self._namespace_hits:
                self._namespace_hits[namespace] = 0
            self._namespace_hits[namespace] += 1
            return value

    async def set(
        self,
        namespace: str,
        query: str,
        response: str,
        canonical_product: str | None = None,
        pricing_version: str | None = None,
        session_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        """Cache a response with governed key.

        Args:
            namespace: Cache namespace identity|overview|pricing
            query: Original user query (will be normalized for cache key)
            response: Serialized response string
            canonical_product: Product context for cache isolation
            pricing_version: Pricing version for cache invalidation
            session_id: Optional session ID for session-aware keys
            ttl_seconds: Override TTL. None = use namespace default.
        """
        if not self.should_cache(namespace):
            return

        key = build_cache_key(namespace, query, canonical_product, pricing_version, session_id)
        ttl = ttl_seconds if ttl_seconds is not None else self.get_ttl(namespace)
        threshold = self.get_compress_threshold(namespace)

        t0 = time.monotonic()

        # Compress
        flag, data = _maybe_compress(response, threshold)
        payload = bytes([flag]) + (data if isinstance(data, bytes) else data.encode("utf-8"))

        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    await r.setex(key, ttl, payload)
                    self._set_count += 1
                    self._total_set_ms += (time.monotonic() - t0) * 1000
                    # Clear local in-flight
                    self._inflight_local.pop(key, None)
                    return
                except RedisError:
                    self._enter_emergency()

        # Emergency fallback
        self._emergency_set(key, response, ttl)

    def _emergency_set(self, key: str, response: str, ttl: int) -> None:
        with self._emergency_lock:
            expiry = time.monotonic() + ttl
            # LRU: evict oldest if at capacity
            if len(self._emergency_cache) >= self._emergency_max:
                oldest_key = min(
                    self._emergency_cache.keys(),
                    key=lambda k: self._emergency_cache[k][0],
                )
                self._emergency_cache.pop(oldest_key, None)
            self._emergency_cache[key] = (expiry, response)
        self._set_count += 1

    async def invalidate(
        self,
        namespace: str | None = None,
        canonical_product: str | None = None,
    ) -> int:
        """Invalidate cache entries by namespace and/or product.

        Args:
            namespace: If set, only invalidate this namespace.
            canonical_product: If set, only invalidate this product.

        Returns: Number of keys deleted (best-effort for Redis).
        """
        count = 0
        pattern_parts = ["rag:cache"]
        if namespace:
            pattern_parts.append(namespace)
        else:
            pattern_parts.append("*")
        if canonical_product:
            prod_hash = _hash_key([canonical_product.lower().replace(" ", "_")])
            pattern_parts.append(prod_hash)
        else:
            pattern_parts.append("*")
        pattern_parts.append("*")  # pricing_version
        pattern_parts.append("*")  # query_hash
        pattern = ":".join(pattern_parts)

        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    cursor = 0
                    while True:
                        cursor, keys = await r.scan(
                            cursor=cursor, match=pattern, count=100
                        )
                        if keys:
                            del_count = await r.delete(*keys)
                            count += del_count
                            self._delete_count += del_count
                        if cursor == 0:
                            break
                except RedisError:
                    pass

        # Emergency: remove matching keys
        with self._emergency_lock:
            import re
            pattern_re = re.compile(pattern.replace("*", ".*"))
            stale = [k for k in self._emergency_cache if pattern_re.match(k)]
            for k in stale:
                self._emergency_cache.pop(k, None)
                count += 1

        if count:
            ns_label = namespace or "all"
            prod_label = canonical_product or "all"
            logger.info(f"Cache invalidated: namespace={ns_label}, product={prod_label}, count={count}")
        return count

    async def invalidate_all(self) -> int:
        """Invalidate entire cache. Use sparingly."""
        count = 0
        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    cursor = 0
                    while True:
                        cursor, keys = await r.scan(
                            cursor=cursor, match="rag:cache:*", count=200
                        )
                        if keys:
                            del_count = await r.delete(*keys)
                            count += del_count
                        if cursor == 0:
                            break
                except RedisError:
                    pass

        with self._emergency_lock:
            count += len(self._emergency_cache)
            self._emergency_cache.clear()

        logger.info(f"All cache invalidated: count={count}")
        return count

    # ------------------------------------------------------------------
    # In-flight dedup
    # ------------------------------------------------------------------

    async def inflight_acquire(
        self,
        namespace: str,
        query: str,
        canonical_product: str | None = None,
        pricing_version: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        """Try to acquire an in-flight slot for this query.

        If another worker is already computing this query, returns False.
        The caller should then wait for the result from cache.

        Cross-worker: uses Redis SET NX.
        Local: uses in-memory threading.Event.
        """
        key = build_cache_key(namespace, query, canonical_product, pricing_version, session_id)
        inflight_key = f"rag:inflight:{hashlib.sha256(key.encode()).hexdigest()[:24]}"

        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    acquired = await r.set(inflight_key, "1", nx=True, ex=self._inflight_ttl)
                    return bool(acquired)
                except RedisError:
                    pass

        # Local in-flight
        if key in self._inflight_local:
            return False
        self._inflight_local[key] = threading.Event()
        return True

    async def inflight_release(
        self,
        namespace: str,
        query: str,
        canonical_product: str | None = None,
        pricing_version: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Release an in-flight slot."""
        key = build_cache_key(namespace, query, canonical_product, pricing_version, session_id)
        inflight_key = f"rag:inflight:{hashlib.sha256(key.encode()).hexdigest()[:24]}"

        if not self._emergency_active:
            r = self._redis
            if r is not None:
                try:
                    await r.delete(inflight_key)
                except RedisError:
                    pass

        event = self._inflight_local.pop(key, None)
        if event:
            event.set()

    # ------------------------------------------------------------------
    # Stats & admin
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        total_reqs = self._hit_count + self._miss_count or 1
        return {
            "backend": "redis" if self._redis_client is not None else "in_memory",
            "emergency_fallback_active": self._emergency_active,
            "emergency_fallback_count": self._emergency_fallback_count,
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "inflight_hit_count": self._inflight_hit_count,
            "set_count": self._set_count,
            "delete_count": self._delete_count,
            "hit_rate": round(self._hit_count / total_reqs * 100, 1) if total_reqs else 0.0,
            "avg_get_ms": round(self._total_get_ms / max(self._hit_count + self._miss_count, 1), 2),
            "avg_set_ms": round(self._total_set_ms / max(self._set_count, 1), 2),
            "namespace_hits": dict(self._namespace_hits),
            "namespace_misses": dict(self._namespace_misses),
            "emergency_max_entries": self._emergency_max,
            "emergency_current_entries": len(self._emergency_cache),
        }

    async def cleanup(self) -> int:
        """Remove stale emergency cache entries. No-op for Redis (auto-TTL)."""
        removed = 0
        now = time.monotonic()
        with self._emergency_lock:
            stale = [
                k for k, (exp, _) in self._emergency_cache.items()
                if exp < now
            ]
            for k in stale:
                self._emergency_cache.pop(k, None)
                removed += 1
        if removed:
            logger.info(f"Response cache emergency store: cleaned {removed} stale entries")
        return removed

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _enter_emergency(self) -> None:
        if not self._emergency_active:
            self._emergency_active = True
            self._emergency_fallback_count += 1
            logger.error(
                "Redis response cache unavailable — entered in-memory emergency mode. "
                "Cache consistency across instances will NOT work."
            )
