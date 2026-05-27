"""
Unit tests for the production-grade ResponseCache.

Covers:
  - Per-route TTL (pricing vs identity vs overview)
  - Cacheability rules (cacheable vs non-cacheable strategies)
  - Session-safe: clarification/LLM are never cached
  - In-flight deduplication
  - Cache metadata (cached_at, cache_age_seconds, original_strategy)
  - LRU eviction
  - Clear / stats
"""

from __future__ import annotations

import hashlib
import time

import pytest

from src.generation.cache import (
    ResponseCache,
    _cache_key,
    _is_cacheable,
    _normalize_for_cache,
    _route_ttl,
    _CACHEABLE_STRATEGIES,
    _NON_CACHEABLE_STRATEGIES,
    _SESSION_DEPENDENT_STRATEGIES,
)


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def cache() -> ResponseCache:
    return ResponseCache(max_entries=100)


@pytest.fixture
def sample_key() -> str:
    return _cache_key("Jaká je úroková sazba?")


# ======================================================================
# Helpers
# ======================================================================

def _make_result(strategy: str, **overrides: str) -> dict:
    """Build a minimal chain.ask() result dict."""
    return {
        "answer": f"Answer for {strategy}",
        "answer_strategy": strategy,
        "answer_confidence": "high",
        "sources": [],
        **overrides,
    }


# ======================================================================
# Route-specific TTL
# ======================================================================

class TestRouteTTL:
    def test_identity_ttl_is_24h(self) -> None:
        assert _route_ttl("identity_direct") == 86400

    def test_overview_ttl_is_6h(self) -> None:
        for strategy in ("card_overview_direct", "account_overview_direct",
                         "mortgage_overview_direct", "rb_key_overview_direct",
                         "product_overview_direct", "credit_card_catalog_direct"):
            assert _route_ttl(strategy) == 21600, f"{strategy} should have 6h TTL"

    def test_soft_guidance_ttl_is_1h(self) -> None:
        assert _route_ttl("soft_guidance_direct") == 3600

    def test_procedural_ttl_is_1h(self) -> None:
        for strategy in ("guided_flow_direct", "procedural_flow_direct"):
            assert _route_ttl(strategy) == 3600

    def test_pricing_ttl_is_15min(self) -> None:
        assert _route_ttl("pricing_row_direct") == 900

    def test_unknown_strategy_ttl_is_zero(self) -> None:
        assert _route_ttl("nonexistent") == 0
        assert _route_ttl("generic_llm") == 0

    def test_pricing_expires_before_identity(self) -> None:
        """Pricing should expire much faster than identity."""
        assert _route_ttl("pricing_row_direct") < _route_ttl("identity_direct")


# ======================================================================
# Cacheability rules
# ======================================================================

class TestIsCacheable:
    def test_cacheable_strategies(self) -> None:
        for strategy in _CACHEABLE_STRATEGIES:
            result = _make_result(strategy)
            assert _is_cacheable(result), f"{strategy} should be cacheable"

    def test_non_cacheable_strategies(self) -> None:
        for strategy in _NON_CACHEABLE_STRATEGIES:
            result = _make_result(strategy)
            assert not _is_cacheable(result), f"{strategy} should NOT be cacheable"

    def test_session_dependent_not_cacheable(self) -> None:
        for strategy in _SESSION_DEPENDENT_STRATEGIES:
            result = _make_result(strategy)
            assert not _is_cacheable(result), f"{strategy} should NOT be cacheable"

    def test_generic_llm_not_cacheable(self) -> None:
        result = _make_result("generic_llm")
        assert not _is_cacheable(result)

    def test_fallback_no_answer_not_cacheable(self) -> None:
        result = _make_result("fallback_no_answer")
        assert not _is_cacheable(result)

    def test_clarification_not_cacheable(self) -> None:
        result = _make_result("clarification_direct")
        assert not _is_cacheable(result)

    def test_unsupported_not_cacheable(self) -> None:
        result = _make_result("unsupported_direct")
        assert not _is_cacheable(result)

    def test_unknown_strategy_not_cacheable(self) -> None:
        result = _make_result("unknown_route")
        assert not _is_cacheable(result)

    def test_pricing_row_is_cacheable(self) -> None:
        result = _make_result("pricing_row_direct")
        assert _is_cacheable(result)


# ======================================================================
# Cache set/get with per-route TTL
# ======================================================================

class TestCacheSetGet:
    def test_set_and_get_identity(self, cache: ResponseCache, sample_key: str) -> None:
        result = _make_result("identity_direct")
        cache.set(sample_key, result)
        cached = cache.get(sample_key)
        assert cached is not None
        assert cached["answer"] == result["answer"]

    def test_non_cacheable_not_stored(self, cache: ResponseCache, sample_key: str) -> None:
        for strategy in list(_NON_CACHEABLE_STRATEGIES) + ["generic_llm"]:
            result = _make_result(strategy)
            cache.set(sample_key, result)
            assert cache.get(sample_key) is None, f"{strategy} should not be stored"

    def test_pricing_expires_after_ttl(self) -> None:
        """Pricing TTL = 900s; we can't wait 15 min, but verify TTL metadata."""
        c = ResponseCache(max_entries=10)
        key = _cache_key("test pricing")
        result = _make_result("pricing_row_direct")
        c.set(key, result)
        cached = c.get(key)
        assert cached is not None
        # Internal TTL metadata
        assert cached.get("_cache_ttl_seconds") == 900

    def test_cache_miss_for_different_keys(self, cache: ResponseCache) -> None:
        key_a = _cache_key("Question A")
        key_b = _cache_key("Question B")
        cache.set(key_a, _make_result("identity_direct"))
        assert cache.get(key_a) is not None
        assert cache.get(key_b) is None

    def test_cache_eviction_lru(self) -> None:
        """Max entries = 3; 4th set should evict oldest."""
        c = ResponseCache(max_entries=3)
        keys = []
        for i in range(4):
            q = f"Question {i}"
            k = _cache_key(q)
            keys.append(k)
            c.set(k, _make_result("identity_direct"))

        # First key should be evicted
        assert c.get(keys[0]) is None, "Oldest entry should be evicted"
        # Last 3 should remain
        for k in keys[1:]:
            assert c.get(k) is not None, f"{k} should still be in cache"

    def test_clear_empties_cache(self, cache: ResponseCache, sample_key: str) -> None:
        cache.set(sample_key, _make_result("identity_direct"))
        assert cache.get(sample_key) is not None
        cache.clear()
        assert cache.get(sample_key) is None

    def test_stats_tracking(self, cache: ResponseCache) -> None:
        key_a = _cache_key("Q1")
        key_b = _cache_key("Q2")

        # Two misses
        cache.get(key_a)
        cache.get(key_b)

        # One set + hit
        cache.set(key_a, _make_result("identity_direct"))
        cache.get(key_a)

        stats = cache.stats
        assert stats["hit_count"] == 1
        assert stats["miss_count"] == 2
        assert stats["hit_rate"] > 0
        assert stats["entries"] == 1


# ======================================================================
# Cache metadata
# ======================================================================

class TestCacheMetadata:
    def test_cached_at_is_set_on_store(self, cache: ResponseCache, sample_key: str) -> None:
        result = _make_result("identity_direct")
        cache.set(sample_key, result)
        cached = cache.get(sample_key)
        assert cached is not None
        assert "_cached_at" in cached
        assert "cache_age_seconds" in cached

    def test_cache_age_increases(self, cache: ResponseCache, sample_key: str) -> None:
        result = _make_result("identity_direct")
        cache.set(sample_key, result)
        cached_1 = cache.get(sample_key)
        age_1 = cached_1["cache_age_seconds"]
        time.sleep(0.15)  # > 0.1s so round(..., 1) is distinguishable
        cached_2 = cache.get(sample_key)
        age_2 = cached_2["cache_age_seconds"]
        assert age_2 >= age_1, "cache_age_seconds should increase over time"
        assert age_2 > 0.0, "cache_age_seconds should be > 0 after sleep"

    def test_add_debug_metadata(self, cache: ResponseCache, sample_key: str) -> None:
        result = _make_result("identity_direct", answer_confidence="high")
        cache.set(sample_key, result)
        cached = cache.get(sample_key)
        cache.add_debug_metadata(cached, cache_hit=True, key=sample_key)
        assert cached["cache_hit"] is True
        assert cached["cache_key"] == sample_key
        assert cached["cached_at"]  # non-empty
        assert cached["original_strategy"] == "identity_direct"
        assert cached["original_confidence"] == "high"

    def test_cache_hit_false_metadata(self, cache: ResponseCache, sample_key: str) -> None:
        result = _make_result("pricing_row_direct")
        cache.set(sample_key, result)
        cached = cache.get(sample_key)
        cache.add_debug_metadata(cached, cache_hit=True, key=sample_key)
        assert cached["original_strategy"] == "pricing_row_direct"


# ======================================================================
# Session safety
# ======================================================================

class TestSessionSafety:
    def test_clarification_not_cached(self, cache: ResponseCache) -> None:
        """Clarification responses must never enter the cache."""
        key = _cache_key("Chci účet")
        result = _make_result("clarification_direct")
        cache.set(key, result)
        assert cache.get(key) is None, "clarification should not be cached"

    def test_generic_llm_not_cached(self, cache: ResponseCache) -> None:
        """LLM-generated responses vary by context — never cache."""
        key = _cache_key("Co je inflace?")
        result = _make_result("generic_llm")
        cache.set(key, result)
        assert cache.get(key) is None, "generic_llm should not be cached"

    def test_cache_key_does_not_include_session_state(self) -> None:
        """Cache key is derived from question text ONLY — no intent/product."""
        key1 = _cache_key("Jaká je úroková sazba?")
        key2 = _cache_key("Jaká je úroková sazba?")
        assert key1 == key2, "Same question = same cache key regardless of session"

        key3 = _cache_key("Jaká je úroková sazba?")
        key4 = _cache_key("jaká je úroková sazba")
        assert key3 == key4, "Normalization should produce same key"

    def test_different_questions_different_keys(self) -> None:
        key1 = _cache_key("Chci účet")
        key2 = _cache_key("Chci kartu")
        assert key1 != key2


# ======================================================================
# In-flight deduplication
# ======================================================================

class TestInFlightDedup:
    def test_claim_first_wins(self, cache: ResponseCache) -> None:
        key = _cache_key("test dedup")
        # First claim succeeds
        assert cache.try_claim_inflight(key) is True
        # Second claim fails
        assert cache.try_claim_inflight(key) is False

    def test_claim_after_signal_succeeds(self, cache: ResponseCache) -> None:
        key = _cache_key("test dedup 2")
        cache.try_claim_inflight(key)
        cache.signal_inflight_done(key)
        # After done, new claim should succeed
        assert cache.try_claim_inflight(key) is True
        cache.signal_inflight_done(key)

    def test_wait_inflight_returns(self, cache: ResponseCache) -> None:
        """Simulate two threads: one computes, one waits."""
        import threading

        key = _cache_key("test dedup wait")
        computed_result = _make_result("identity_direct")
        results: list[dict | None] = [None]

        def computer() -> None:
            """Thread 1: claims, computes, signals."""
            cache.try_claim_inflight(key)
            time.sleep(0.05)  # simulate work
            cache.set(key, computed_result)
            cache.signal_inflight_done(key)

        def waiter() -> None:
            """Thread 2: waits for computer to finish."""
            cache.wait_inflight(key)
            results[0] = cache.get(key)

        t1 = threading.Thread(target=computer)
        t2 = threading.Thread(target=waiter)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results[0] is not None
        assert results[0]["answer"] == computed_result["answer"]

    def test_dedup_stats(self, cache: ResponseCache) -> None:
        key = _cache_key("test dedup stats")
        cache.try_claim_inflight(key)
        cache.signal_inflight_done(key)
        stats = cache.stats
        assert "dedup_saved_count" in stats

    def test_clear_signals_inflight(self, cache: ResponseCache) -> None:
        """Clearing the cache should signal all in-flight waiters."""
        import threading

        key = _cache_key("test dedup clear")
        waited = threading.Event()

        def waiter() -> None:
            cache.wait_inflight(key, timeout=5.0)
            waited.set()

        cache.try_claim_inflight(key)
        t = threading.Thread(target=waiter)
        t.start()
        cache.clear()
        t.join()
        assert waited.is_set(), "Waiter should be unblocked by clear"


# ======================================================================
# Cache key normalization
# ======================================================================

class TestCacheKey:
    def test_normalize_removes_diacritics(self) -> None:
        norm = _normalize_for_cache("Úroková sazba")
        assert "U" in norm or "u" in norm
        assert "´" not in norm

    def test_normalize_lowercases(self) -> None:
        assert _normalize_for_cache("Hello World") == "hello world"

    def test_normalize_collapses_whitespace(self) -> None:
        assert _normalize_for_cache("a   b\t\nc") == "a b c"

    def test_cache_key_length(self) -> None:
        key = _cache_key("test")
        assert len(key) == 32

    def test_cache_key_deterministic(self) -> None:
        assert _cache_key("Ahoj") == _cache_key("ahoj")

    def test_cache_key_different_for_different_inputs(self) -> None:
        assert _cache_key("Karta") != _cache_key("Účet")
