"""
Production-grade response cache with per-route TTL, in-flight
deduplication, and pluggable storage backends (in-memory / Redis).

Architecture:
  ResponseCache (orchestration)
      │  delegates storage to
      └─ CacheBackend (interface)
            ├─ InMemoryCacheBackend (default)
            └─ RedisCacheBackend (optional, graceful fallback)

Cacheable routes:
  - identity_direct         (deterministic system response)           → 24h
  - overview_*_direct       (safe product overview formatters)        → 6h
  - soft_guidance_direct    (FAQ soft guidance)                       → 1h
  - guided_flow_direct      (card blocking, complaint, SEPA/SWIFT)    → 1h
  - procedural_flow_direct  (activation, limit, wallet, abroad, brand) → 1h
  - pricing_row_direct      (exact currently grounded pricing rows)   → 15 min

Cache key: normalized_query (question only — NO intent/product to avoid
session contamination). Clarification-dependent queries are not cacheable.

In-flight deduplication: parallel requests with the same cache key
coalesce into a single computation via threading.Event.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import unicodedata
from datetime import UTC, datetime
from typing import Any

import config
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Route → TTL mapping
# ---------------------------------------------------------------------------
_ROUTE_TTL: dict[str, int] = {
    "identity_direct": config.CACHE_TTL_IDENTITY,
    "guided_flow_direct": config.CACHE_TTL_PROCEDURAL,
    "procedural_flow_direct": config.CACHE_TTL_PROCEDURAL,
    "soft_guidance_direct": config.CACHE_TTL_SOFT_GUIDANCE,
    "card_overview_direct": config.CACHE_TTL_OVERVIEW,
    "account_overview_direct": config.CACHE_TTL_OVERVIEW,
    "mortgage_overview_direct": config.CACHE_TTL_OVERVIEW,
    "investment_overview_direct": config.CACHE_TTL_OVERVIEW,
    "rb_key_overview_direct": config.CACHE_TTL_OVERVIEW,
    "payment_overview_direct": config.CACHE_TTL_OVERVIEW,
    "sepa_swift_overview_direct": config.CACHE_TTL_OVERVIEW,
    "product_overview_direct": config.CACHE_TTL_OVERVIEW,
    "credit_card_catalog_direct": config.CACHE_TTL_OVERVIEW,
    "comparison_direct": config.CACHE_TTL_OVERVIEW,
    "pricing_row_direct": config.CACHE_TTL_PRICING,
}

_CACHEABLE_STRATEGIES = frozenset(_ROUTE_TTL.keys())

_NON_CACHEABLE_STRATEGIES = frozenset({
    "unsupported_direct",
    "fallback_no_answer",
    "clarification_direct",
})

# Strategies that depend on session state (clarification, context)
_SESSION_DEPENDENT_STRATEGIES = frozenset({
    "clarification_direct",
    "generic_llm",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_for_cache(text: str) -> str:
    """Strip diacritics, lowercase, collapse whitespace for cache key."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9\s]", "", text.lower())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _cache_key(question: str) -> str:
    """Build a deterministic cache key from the normalized question ONLY.

    Key design decision: we do NOT include resolved_intent or resolved_product
    in the key. This is intentional:
      - Cache must be session-safe: intent/product could differ between sessions.
      - Two users asking the same question should always get the same deterministic
        answer for cacheable routes.
      - The route determination (identity/overview/pricing/etc.) is deterministic
        based on the question text itself.
    """
    norm = _normalize_for_cache(question)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


def _route_ttl(strategy: str) -> int:
    """Return TTL in seconds for a given strategy; 0 means no caching."""
    return _ROUTE_TTL.get(strategy, 0)


def _is_cacheable(result: dict) -> bool:
    """Check whether a result dict should be cached.

    Rules:
      1. Strategy must be in _CACHEABLE_STRATEGIES.
      2. Must NOT be session-dependent (clarification, LLM).
      3. Must have a route-specific TTL > 0.
    """
    strategy = result.get("answer_strategy", "")
    if strategy in _SESSION_DEPENDENT_STRATEGIES:
        return False
    if strategy not in _CACHEABLE_STRATEGIES:
        return False
    return _route_ttl(strategy) > 0


# ---------------------------------------------------------------------------
# ResponseCache
# ---------------------------------------------------------------------------

class ResponseCache:
    """Orchestration layer for response caching with pluggable storage backends.

    Features:
      - Per-route TTL (see _ROUTE_TTL)
      - Pluggable CacheBackend (in-memory / Redis)
      - In-flight deduplication via threading.Event
      - Cache metadata: cached_at, cache_age_seconds, original_strategy
      - Session-safe: clarification/LLM responses are never cached
    """

    def __init__(self, backend: Any = None, max_entries: int = 500) -> None:
        """Initialize cache with optional backend injection.

        Args:
            backend: A CacheBackend-compatible instance. If None, uses
                     InMemoryCacheBackend(max_entries).
        """
        if backend is not None:
            self._backend = backend
            logger.info(f"ResponseCache: using injected backend={type(backend).__name__}")
        else:
            from src.storage.memory import InMemoryCacheBackend
            self._backend = InMemoryCacheBackend(max_entries=max_entries)
            logger.info(f"ResponseCache: using default InMemoryCacheBackend(max={max_entries})")

        self._inflight: dict[str, threading.Event] = {}   # key → event for dedup
        self._lock = threading.Lock()
        self._dedup_saved_count = 0
        logger.info(
            f"ResponseCache: route_ttls={ {k: v for k, v in _ROUTE_TTL.items()} }"
        )

    @property
    def backend_name(self) -> str:
        """Return the storage backend name for debug metadata."""
        return type(self._backend).__name__

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> dict | None:
        """Return cached result or None (on miss or expiry)."""
        result = self._backend.get(key)
        if result is None:
            return None
        # Add fresh age metadata
        cached_at = result.get("_cached_at_ts", 0.0)
        result["cache_age_seconds"] = round(time.monotonic() - cached_at, 1) if cached_at else 0
        return result

    def set(self, key: str, result: dict) -> None:
        """Store a result in cache if it is cacheable (checks _is_cacheable).

        Args:
            key: Cache key from _cache_key().
            result: The full result dict from chain.ask() to cache.
        """
        if not _is_cacheable(result):
            return
        strategy = result.get("answer_strategy", "")
        ttl = _route_ttl(strategy)
        if ttl <= 0:
            return

        now = datetime.now(UTC)
        # Store cache metadata on the result
        result["_cached_at"] = now.isoformat()
        result["_cached_at_ts"] = time.monotonic()
        result["_cache_ttl_seconds"] = ttl
        result["_original_strategy"] = strategy

        self._backend.set(key, result, ttl_seconds=ttl)
        logger.debug(f"Cache SET key={key[:12]}… strategy={strategy} ttl={ttl}s backend={self.backend_name}")

    def add_debug_metadata(self, result: dict, cache_hit: bool, key: str | None = None) -> None:
        """Augment result dict with public-facing cache debug fields.

        These are returned in the API response.
        """
        result["cache_hit"] = cache_hit
        result["cache_key"] = key
        result["cache_age_seconds"] = result.get("cache_age_seconds", 0)
        result["cache_backend"] = self.backend_name

        if cache_hit:
            result["cached_at"] = result.get("_cached_at", "")
            result["original_strategy"] = result.get("_original_strategy", "")
            result["original_confidence"] = result.get("answer_confidence", "")

    # ------------------------------------------------------------------
    # In-flight deduplication
    # ------------------------------------------------------------------

    def try_claim_inflight(self, key: str) -> bool:
        """Atomically claim a key as 'in-flight'. Returns True if caller
        should compute the response; False if another thread is already
        computing it (caller must wait on the event).
        """
        self._lock.acquire()
        try:
            if key in self._inflight:
                return False  # another thread is already computing
            self._inflight[key] = threading.Event()
            return True
        finally:
            self._lock.release()

    def signal_inflight_done(self, key: str) -> None:
        """Signal that in-flight computation for key is complete."""
        self._lock.acquire()
        try:
            event = self._inflight.pop(key, None)
        finally:
            self._lock.release()
        if event:
            event.set()
            self._dedup_saved_count += 1

    def wait_inflight(self, key: str, timeout: float = 30.0) -> bool:
        """Wait for another thread to finish computing key.

        Returns True if the event was set (data available), False on timeout.
        """
        self._lock.acquire()
        try:
            event = self._inflight.get(key)
        finally:
            self._lock.release()
        if event is None:
            return False
        return event.wait(timeout=timeout)

    # ------------------------------------------------------------------
    # Stats & admin
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict:
        backend_stats = self._backend.stats
        self._lock.acquire()
        try:
            total = backend_stats.get("hit_count", 0) + backend_stats.get("miss_count", 0) + self._dedup_saved_count
            return {
                **backend_stats,
                "dedup_saved_count": self._dedup_saved_count,
                "hit_rate": round(backend_stats.get("hit_count", 0) / max(total, 1), 4),
                "inflight_count": len(self._inflight),
            }
        finally:
            self._lock.release()

    def clear(self) -> None:
        self._backend.clear()
        self._lock.acquire()
        try:
            for ev in self._inflight.values():
                ev.set()
            self._inflight.clear()
            self._dedup_saved_count = 0
        finally:
            self._lock.release()
        logger.info("ResponseCache: cleared")
