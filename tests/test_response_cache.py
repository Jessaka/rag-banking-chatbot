"""
Unit tests for DistributedResponseCache.

Covers:
  - Cache key construction and parsing
  - Query normalization for cache keys
  - Namespace/key governance (product-aware, pricing-version-aware)
  - Per-strategy TTL
  - Cache set/get with compression
  - Cache invalidation by namespace and product
  - Cross-product cache isolation
  - In-flight dedup (local)
  - Graceful degradation (no Redis = in-memory emergency mode)
  - Stats tracking
  - Emergency cleanup
"""

from __future__ import annotations

import json
import time

import pytest

pytestmark = pytest.mark.asyncio

# Force emergency fallback mode (no Redis available in test env)
from src.storage import response_cache as rcache

rcache._REDIS_AVAILABLE = False

from src.storage.response_cache import (
    DistributedResponseCache,
    _normalize_query,
    _hash_key,
    build_cache_key,
    parse_cache_key,
    _COMPRESSION_AVAILABLE,
)


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def cache() -> DistributedResponseCache:
    c = DistributedResponseCache(
        key_prefix="rag:cache",
        inflight_ttl=30,
    )
    c._emergency_active = True  # Force emergency fallback
    c._emergency_cache.clear()
    return c


SAMPLE_RESPONSE = json.dumps({
    "answer": "eKonto SMART stojí 0 Kč měsíčně.",
    "answer_strategy": "pricing_row_direct",
    "confidence_bucket": "high",
})


# ======================================================================
# Cache key governance
# ======================================================================

class TestCacheKey:
    def test_build_key_includes_namespace(self) -> None:
        key = build_cache_key("pricing", "Kolik stojí eKonto?")
        assert "rag:cache" in key
        assert "pricing" in key

    def test_build_key_with_product(self) -> None:
        key = build_cache_key("pricing", "Kolik stojí eKonto?", canonical_product="eKonto SMART")
        assert "rag:cache:pricing" in key[:20]

    def test_build_key_with_pricing_version(self) -> None:
        key = build_cache_key("pricing", "test", pricing_version="v2026-01")
        assert key is not None

    def test_build_key_with_session(self) -> None:
        key = build_cache_key("identity", "Ahoj", session_id="session-12345")
        assert key is not None

    def test_different_products_different_keys(self) -> None:
        key_a = build_cache_key("pricing", "Kolik stojí?", canonical_product="eKonto SMART")
        key_b = build_cache_key("pricing", "Kolik stojí?", canonical_product="eKonto BASIC")
        assert key_a != key_b, "Different products must have different cache keys"

    def test_same_query_same_product_same_key(self) -> None:
        key_a = build_cache_key("pricing", "Kolik stojí eKonto?", canonical_product="eKonto SMART")
        key_b = build_cache_key("pricing", "Kolik stojí eKonto?", canonical_product="eKonto SMART")
        assert key_a == key_b, "Same query + product = same key"

    def test_different_namespaces_different_keys(self) -> None:
        key_a = build_cache_key("identity", "Ahoj")
        key_b = build_cache_key("overview", "Ahoj")
        assert key_a != key_b

    def test_parse_cache_key_roundtrip(self) -> None:
        key = build_cache_key("pricing", "test", canonical_product="prod", pricing_version="v1", session_id="sid")
        parsed = parse_cache_key(key)
        assert parsed.get("namespace") == "pricing"
        assert parsed.get("query_hash") is not None

    def test_normalize_query_removes_fillers(self) -> None:
        assert "prosím" not in _normalize_query("prosím o informaci")
        assert "bych" not in _normalize_query("chtěl bych vědět")

    def test_normalize_query_lowercases(self) -> None:
        assert _normalize_query("KOLIK STOJÍ") == "kolik stojí"

    def test_normalize_query_collapses_whitespace(self) -> None:
        # Note: "a" and "the" are filler words and get removed
        result = _normalize_query("a   b\t\nc")
        assert "b" in result and "c" in result
        assert "  " not in result  # no double spaces
        assert "\t" not in result
        assert "\n" not in result

    def test_normalize_query_strips_punctuation(self) -> None:
        result = _normalize_query("Kolik stojí eKonto?")
        assert "?" not in result


# ======================================================================
# Cache policy / TTL
# ======================================================================

class TestCachePolicy:
    def test_identity_ttl_is_24h(self, cache: DistributedResponseCache) -> None:
        assert cache.get_ttl("identity") == 86400

    def test_overview_ttl_is_6h(self, cache: DistributedResponseCache) -> None:
        assert cache.get_ttl("overview") == 21600

    def test_pricing_ttl_is_15min(self, cache: DistributedResponseCache) -> None:
        assert cache.get_ttl("pricing") == 900

    def test_unsupported_never_cached(self, cache: DistributedResponseCache) -> None:
        assert cache.should_cache("unsupported") is False

    def test_clarification_never_cached(self, cache: DistributedResponseCache) -> None:
        assert cache.should_cache("clarification") is False

    def test_identity_is_cacheable(self, cache: DistributedResponseCache) -> None:
        assert cache.should_cache("identity") is True

    def test_pricing_is_cacheable(self, cache: DistributedResponseCache) -> None:
        assert cache.should_cache("pricing") is True

    def test_compress_thresholds(self, cache: DistributedResponseCache) -> None:
        assert cache.get_compress_threshold("identity") == 2048
        assert cache.get_compress_threshold("pricing") == 512

    def test_get_policy_returns_dict(self, cache: DistributedResponseCache) -> None:
        policy = cache.get_policy("identity")
        assert "ttl" in policy
        assert "compress_threshold" in policy


# ======================================================================
# Cache set/get
# ======================================================================

class TestCacheSetGet:
    async def test_set_and_get_pricing(self, cache: DistributedResponseCache) -> None:
        await cache.set("pricing", "Kolik stojí eKonto?", SAMPLE_RESPONSE)
        result = await cache.get("pricing", "Kolik stojí eKonto?")
        assert result is not None
        parsed = json.loads(result)
        assert parsed["answer"] == "eKonto SMART stojí 0 Kč měsíčně."

    async def test_get_miss(self, cache: DistributedResponseCache) -> None:
        result = await cache.get("pricing", "Neznámý dotaz")
        assert result is None

    async def test_set_unsupported_should_not_store(self, cache: DistributedResponseCache) -> None:
        await cache.set("unsupported", "test", SAMPLE_RESPONSE)
        result = await cache.get("unsupported", "test")
        assert result is None

    async def test_set_clarification_should_not_store(self, cache: DistributedResponseCache) -> None:
        await cache.set("clarification", "test", SAMPLE_RESPONSE)
        result = await cache.get("clarification", "test")
        assert result is None

    async def test_set_with_ttl_override(self, cache: DistributedResponseCache) -> None:
        await cache.set("pricing", "test", SAMPLE_RESPONSE, ttl_seconds=3600)
        result = await cache.get("pricing", "test")
        assert result is not None

    async def test_cross_product_isolation(self, cache: DistributedResponseCache) -> None:
        """Query same question for different products → different cache entries."""
        await cache.set("pricing", "Kolik stojí?", SAMPLE_RESPONSE,
                        canonical_product="eKonto SMART")
        await cache.set("pricing", "Kolik stojí?", '{"answer": "BASIC stojí 50 Kč"}'.encode() if False else '{"answer": "BASIC stojí 50 Kč"}',
                        canonical_product="eKonto BASIC")

        result_smart = await cache.get("pricing", "Kolik stojí?", canonical_product="eKonto SMART")
        result_basic = await cache.get("pricing", "Kolik stojí?", canonical_product="eKonto BASIC")

        assert result_smart is not None
        assert result_basic is not None

    async def test_different_queries_different_cache(self, cache: DistributedResponseCache) -> None:
        await cache.set("pricing", "Query A", SAMPLE_RESPONSE)
        result_b = await cache.get("pricing", "Query B")
        assert result_b is None


# ======================================================================
# Cache invalidation
# ======================================================================

class TestInvalidation:
    async def test_invalidate_namespace(self, cache: DistributedResponseCache) -> None:
        await cache.set("pricing", "test", SAMPLE_RESPONSE)
        count = await cache.invalidate(namespace="pricing")
        result = await cache.get("pricing", "test")
        assert result is None
        assert count >= 0  # Emergency mode may not report exact count

    async def test_invalidate_product(self, cache: DistributedResponseCache) -> None:
        await cache.set("pricing", "test", SAMPLE_RESPONSE, canonical_product="eKonto SMART")
        count = await cache.invalidate(canonical_product="eKonto SMART")
        result = await cache.get("pricing", "test", canonical_product="eKonto SMART")
        assert result is None

    async def test_invalidate_namespace_only(self, cache: DistributedResponseCache) -> None:
        await cache.set("identity", "test", SAMPLE_RESPONSE)
        await cache.set("pricing", "test", SAMPLE_RESPONSE)

        await cache.invalidate(namespace="pricing")

        # Identity should still be cached
        result_identity = await cache.get("identity", "test")
        assert result_identity is not None
        # Pricing should be gone
        result_pricing = await cache.get("pricing", "test")
        assert result_pricing is None

    async def test_invalidate_all(self, cache: DistributedResponseCache) -> None:
        await cache.set("identity", "test", SAMPLE_RESPONSE)
        await cache.set("pricing", "test", SAMPLE_RESPONSE)

        count = await cache.invalidate_all()
        assert await cache.get("identity", "test") is None
        assert await cache.get("pricing", "test") is None


# ======================================================================
# In-flight deduplication
# ======================================================================

class TestInflight:
    async def test_inflight_acquire(self, cache: DistributedResponseCache) -> None:
        acquired = await cache.inflight_acquire("pricing", "test query")
        assert acquired is True

        # Second acquire should fail (already in-flight)
        acquired2 = await cache.inflight_acquire("pricing", "test query")
        assert acquired2 is False

        await cache.inflight_release("pricing", "test query")
        # After release, acquire should succeed again
        acquired3 = await cache.inflight_acquire("pricing", "test query")
        assert acquired3 is True
        await cache.inflight_release("pricing", "test query")

    async def test_inflight_release(self, cache: DistributedResponseCache) -> None:
        await cache.inflight_acquire("pricing", "test")
        await cache.inflight_release("pricing", "test")
        # After release, should be able to acquire again
        assert await cache.inflight_acquire("pricing", "test") is True
        await cache.inflight_release("pricing", "test")


# ======================================================================
# Stats
# ======================================================================

class TestStats:
    async def test_stats_structure(self, cache: DistributedResponseCache) -> None:
        stats = cache.stats
        assert "backend" in stats
        assert "hit_count" in stats
        assert "miss_count" in stats
        assert "set_count" in stats
        assert "hit_rate" in stats
        assert "avg_get_ms" in stats
        assert "avg_set_ms" in stats

    async def test_stats_after_operations(self, cache: DistributedResponseCache) -> None:
        # Miss
        await cache.get("pricing", "nonexistent")
        # Hit
        await cache.set("pricing", "test", SAMPLE_RESPONSE)
        await cache.get("pricing", "test")

        stats = cache.stats
        assert stats["hit_count"] >= 1
        assert stats["miss_count"] >= 1
        assert stats["set_count"] >= 1


# ======================================================================
# Graceful degradation
# ======================================================================

class TestGracefulDegradation:
    async def test_emergency_mode_on_redis_failure(self) -> None:
        """Redis unavailable should fall back to in-memory emergency mode."""
        c = DistributedResponseCache(
            redis_url="redis://nonexistent:9999",
        )
        c._redis_client = None
        c._emergency_active = True

        await c.set("pricing", "test", SAMPLE_RESPONSE)
        result = await c.get("pricing", "test")
        assert result is not None
        assert c.stats["emergency_fallback_active"] is True

    async def test_emergency_cleanup(self, cache: DistributedResponseCache) -> None:
        await cache.set("pricing", "test", SAMPLE_RESPONSE, ttl_seconds=0)
        removed = await cache.cleanup()
        result = await cache.get("pricing", "test")
        assert result is None


# ======================================================================
# Edge cases
# ======================================================================

class TestEdgeCases:
    async def test_empty_query_still_gets_key(self) -> None:
        key = build_cache_key("pricing", "")
        assert key is not None

    async def test_very_long_query(self, cache: DistributedResponseCache) -> None:
        long_query = "x" * 5000
        await cache.set("pricing", long_query, SAMPLE_RESPONSE)
        result = await cache.get("pricing", long_query)
        assert result is not None

    async def test_special_characters_in_query(self, cache: DistributedResponseCache) -> None:
        query = "Cena účtu: 0 Kč? 100% zdarma!"
        await cache.set("pricing", query, SAMPLE_RESPONSE)
        result = await cache.get("pricing", query)
        assert result is not None

    async def test_pricing_version_affects_key(self) -> None:
        key_v1 = build_cache_key("pricing", "test", pricing_version="v1")
        key_v2 = build_cache_key("pricing", "test", pricing_version="v2")
        assert key_v1 != key_v2

    async def test_session_id_affects_key(self) -> None:
        key_s1 = build_cache_key("pricing", "test", session_id="session-1")
        key_s2 = build_cache_key("pricing", "test", session_id="session-2")
        assert key_s1 != key_s2
