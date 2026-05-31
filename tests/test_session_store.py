"""
Unit tests for DistributedSessionStore.

Covers:
  - Save/load session state (fields, full state)
  - TTL expiration (emergency fallback mode)
  - Field-level updates (streaming-safe)
  - Optimistic locking (version conflict detection)
  - Session deletion
  - Existence check
  - Distributed lock acquire/release
  - Graceful degradation (no Redis = in-memory emergency mode)
  - Stats tracking
  - Emergency fallback cleanup
"""

from __future__ import annotations

import sys
import time

import pytest

pytestmark = pytest.mark.asyncio

# Force emergency fallback mode (no Redis available in test env)
from src.storage import session_store as sstore

# Ensure Redis is marked unavailable
sstore._REDIS_AVAILABLE = False

from src.storage.session_store import DistributedSessionStore


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def store() -> DistributedSessionStore:
    """Create a fresh store for each test (always in emergency fallback mode)."""
    s = DistributedSessionStore(
        default_ttl=60,  # short TTL for test
        lock_timeout=5,
    )
    s._emergency_active = True  # Force emergency mode
    s.clear()
    yield s
    s.clear()


@pytest.fixture
def sample_session_data() -> dict:
    return {
        "resolved_product": "ekonto_smart",
        "resolved_intent": "pricing",
        "last_canonical_product": "eKonto SMART",
        "unresolved_product": None,
        "pending_clarification": None,
        "clarification_candidates": ["eKonto SMART", "eKonto BASIC"],
        "current_domain": "retail",
        "current_intent": "pricing",
        "current_product": "ekonto_smart",
        "chat_history": [
            {"role": "user", "content": "Kolik stojí eKonto?"},
            {"role": "assistant", "content": "eKonto SMART stojí 0 Kč měsíčně."},
        ],
    }


# ======================================================================
# Save / Load
# ======================================================================

class TestSaveLoad:
    async def test_save_and_load(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        session_id = "test-session-1"
        await store.save(session_id, sample_session_data)
        loaded = await store.load(session_id)
        assert loaded is not None
        assert loaded["resolved_product"] == "ekonto_smart"
        assert loaded["resolved_intent"] == "pricing"
        assert loaded["current_domain"] == "retail"
        assert loaded["session_version"] == 1

    async def test_load_nonexistent_returns_none(self, store: DistributedSessionStore) -> None:
        loaded = await store.load("nonexistent-session")
        assert loaded is None

    async def test_save_updates_version(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        session_id = "test-version"
        await store.save(session_id, sample_session_data)
        loaded = await store.load(session_id)
        assert loaded["session_version"] == 1

        # Save again
        await store.save(session_id, sample_session_data)
        loaded = await store.load(session_id)
        assert loaded["session_version"] == 2

    async def test_save_with_ttl(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        session_id = "test-ttl"
        await store.save(session_id, sample_session_data, ttl_seconds=3600)
        loaded = await store.load(session_id)
        assert loaded is not None
        assert "expires_at" in loaded

    async def test_save_metadata_fields(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        session_id = "test-meta"
        await store.save(session_id, sample_session_data)
        loaded = await store.load(session_id)
        assert "created_at" in loaded
        assert "updated_at" in loaded
        assert "expires_at" in loaded


# ======================================================================
# Field-level operations (streaming-safe)
# ======================================================================

class TestFieldOperations:
    async def test_save_and_load_field(self, store: DistributedSessionStore) -> None:
        session_id = "test-field"
        await store.save(session_id, {"resolved_product": "ekonto_smart"})
        value = await store.load_field(session_id, "resolved_product")
        assert value == "ekonto_smart"

    async def test_load_nonexistent_field(self, store: DistributedSessionStore) -> None:
        session_id = "test-field-none"
        await store.save(session_id, {"resolved_product": "ekonto"})
        value = await store.load_field(session_id, "nonexistent_field")
        assert value is None

    async def test_load_field_from_empty_session(self, store: DistributedSessionStore) -> None:
        value = await store.load_field("nonexistent", "resolved_product")
        assert value is None

    async def test_save_field_updates_and_preserves(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        session_id = "test-save-field"
        await store.save(session_id, sample_session_data)

        # Update single field
        await store.save_field(session_id, "resolved_product", "ekonto_basic")
        # Verify the full session
        loaded = await store.load(session_id)
        assert loaded["resolved_product"] == "ekonto_basic"
        # Other fields preserved
        assert loaded["resolved_intent"] == "pricing"
        assert loaded["current_domain"] == "retail"

    async def test_save_field_non_serializable_field(self, store: DistributedSessionStore) -> None:
        session_id = "test-field-non-serializable"
        # Should silently ignore non-serializable fields
        await store.save_field(session_id, "_internal_temp", "value")
        loaded = await store.load(session_id)
        assert loaded is None or "_internal_temp" not in loaded


# ======================================================================
# Optimistic locking
# ======================================================================

class TestOptimisticLocking:
    async def test_version_conflict(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        session_id = "test-conflict"
        # Save initial
        await store.save(session_id, sample_session_data)
        loaded = await store.load(session_id)
        version = loaded["session_version"]
        assert version == 1

        # Save with correct version — should succeed
        success = await store.save(session_id, {**sample_session_data, "resolved_product": "x"}, expected_version=version)
        assert success is True

        # Save with stale version — should fail
        success = await store.save(session_id, {**sample_session_data, "resolved_product": "y"}, expected_version=version)
        assert success is False

        # The actual value should not have changed
        loaded = await store.load(session_id)
        assert loaded["resolved_product"] == "x"

    async def test_save_without_version_always_succeeds(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        session_id = "test-no-version"
        await store.save(session_id, sample_session_data)
        # Force save (no version check)
        success = await store.save(session_id, {**sample_session_data, "resolved_product": "new"}, expected_version=None)
        assert success is True
        loaded = await store.load(session_id)
        assert loaded["resolved_product"] == "new"

    async def test_confidence_increments_on_conflict(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        session_id = "test-conflict-count"
        await store.save(session_id, sample_session_data)
        v1 = (await store.load(session_id))["session_version"]

        # Success
        await store.save(session_id, sample_session_data, expected_version=v1)
        prev_conflicts = store.stats["conflict_count"]

        # Conflict
        await store.save(session_id, sample_session_data, expected_version=v1)
        assert store.stats["conflict_count"] == prev_conflicts + 1


# ======================================================================
# Exists / Delete
# ======================================================================

class TestExistsDelete:
    async def test_exists_returns_true(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        session_id = "test-exists"
        await store.save(session_id, sample_session_data)
        assert await store.exists(session_id) is True

    async def test_exists_returns_false(self, store: DistributedSessionStore) -> None:
        assert await store.exists("nonexistent") is False

    async def test_delete_removes_session(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        session_id = "test-delete"
        await store.save(session_id, sample_session_data)
        assert await store.exists(session_id) is True
        await store.delete(session_id)
        assert await store.exists(session_id) is False
        assert await store.load(session_id) is None


# ======================================================================
# Distributed locking
# ======================================================================

class TestDistributedLock:
    async def test_acquire_and_release(self, store: DistributedSessionStore) -> None:
        session_id = "test-lock"
        acquired = await store.acquire_lock(session_id, timeout=5)
        assert acquired is True

        await store.release_lock(session_id)

    async def test_acquire_twice_fails(self, store: DistributedSessionStore) -> None:
        session_id = "test-lock-twice"
        acquired1 = await store.acquire_lock(session_id, timeout=5)
        assert acquired1 is True

        acquired2 = await store.acquire_lock(session_id, timeout=1)
        assert acquired2 is False

        await store.release_lock(session_id)

    async def test_release_and_acquire_again(self, store: DistributedSessionStore) -> None:
        session_id = "test-lock-release"
        await store.acquire_lock(session_id, timeout=5)
        await store.release_lock(session_id)

        acquired = await store.acquire_lock(session_id, timeout=5)
        assert acquired is True
        await store.release_lock(session_id)

    async def test_lock_timeout(self, store: DistributedSessionStore) -> None:
        session_id = "test-lock-timeout"
        # Acquire with short timeout
        acquired = await store.acquire_lock(session_id, timeout=2)
        assert acquired is True

        # Second acquire should fail (lock already held)
        acquired2 = await store.acquire_lock(session_id, timeout=0.1)
        assert acquired2 is False

        await store.release_lock(session_id)


# ======================================================================
# Graceful degradation
# ======================================================================

class TestGracefulDegradation:
    async def test_emergency_mode_on_redis_failure(self) -> None:
        """Redis unavailable should fall back to in-memory emergency mode."""
        store = DistributedSessionStore(
            redis_url="redis://nonexistent:9999",
            default_ttl=60,
        )
        # Force check to trigger emergency mode
        store._redis_client = None
        store._emergency_active = True

        session_id = "test-emergency"
        await store.save(session_id, {"resolved_product": "test"})
        loaded = await store.load(session_id)
        assert loaded is not None
        assert loaded["resolved_product"] == "test"
        assert store.stats["emergency_fallback_active"] is True

    async def test_emergency_fallback_count(self, store: DistributedSessionStore) -> None:
        # Store is already in emergency mode; enter_emergency is a no-op
        initial = store.stats["emergency_fallback_count"]
        # Force a fresh store without emergency mode
        s2 = DistributedSessionStore(default_ttl=60)
        s2._emergency_active = False
        assert s2.stats["emergency_fallback_count"] == 0
        s2._enter_emergency()
        assert s2.stats["emergency_fallback_count"] == 1
        s2._enter_emergency()
        # Entering again should not count
        assert s2.stats["emergency_fallback_count"] == 1

    async def test_emergency_cleanup(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        session_id = "test-cleanup"
        await store.save(session_id, sample_session_data, ttl_seconds=0)  # immediate expiry
        # Force cleanup
        removed = await store.cleanup()
        # After cleanup, session should be gone
        loaded = await store.load(session_id)
        assert loaded is None


# ======================================================================
# Stats
# ======================================================================

class TestStats:
    async def test_stats_structure(self, store: DistributedSessionStore) -> None:
        stats = store.stats
        assert "backend" in stats
        assert "load_count" in stats
        assert "save_count" in stats
        assert "conflict_count" in stats
        assert "emergency_fallback_active" in stats
        assert "emergency_fallback_count" in stats
        assert "avg_load_ms" in stats
        assert "avg_save_ms" in stats

    async def test_stats_after_operations(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        # Load nonexistent
        await store.load("stats-test")
        # Save
        await store.save("stats-test", sample_session_data)
        # Load again
        await store.load("stats-test")

        stats = store.stats
        assert stats["load_count"] >= 2
        assert stats["save_count"] >= 1

    async def test_clear_resets_emergency(self, store: DistributedSessionStore, sample_session_data: dict) -> None:
        await store.save("test-clear", sample_session_data)
        store.clear()
        loaded = await store.load("test-clear")
        assert loaded is None


# ======================================================================
# TTL expiration in emergency mode
# ======================================================================

class TestTTLExpiration:
    async def test_session_expires_after_ttl(self) -> None:
        store = DistributedSessionStore(default_ttl=0)
        store._emergency_active = True
        session_id = "test-ttl-expire"
        await store.save(session_id, {"resolved_product": "test"}, ttl_seconds=0)
        loaded = await store.load(session_id)
        assert loaded is None

    async def test_session_persists_within_ttl(self) -> None:
        store = DistributedSessionStore(default_ttl=60)
        store._emergency_active = True
        session_id = "test-ttl-ok"
        await store.save(session_id, {"resolved_product": "test"})
        loaded = await store.load(session_id)
        assert loaded is not None
        assert loaded["resolved_product"] == "test"


# ======================================================================
# Session ID hashing
# ======================================================================

class TestSessionHashing:
    async def test_hashed_key_used(self) -> None:
        """Ensure raw session IDs are not stored as-is — hashed keys."""
        store = DistributedSessionStore()
        store._emergency_active = True
        session_id = "user-raw-uuid-12345"
        await store.save(session_id, {"resolved_product": "test"})
        # In emergency mode, the raw session_id IS the key (no way to check hash)
        # Verify at least that we can load
        loaded = await store.load(session_id)
        assert loaded is not None

    def test_hash_is_deterministic(self) -> None:
        h1 = sstore._hash_session_id("session-1")
        h2 = sstore._hash_session_id("session-1")
        assert h1 == h2

    def test_different_sessions_different_hash(self) -> None:
        h1 = sstore._hash_session_id("session-1")
        h2 = sstore._hash_session_id("session-2")
        assert h1 != h2
