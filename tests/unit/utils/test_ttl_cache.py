"""Unit tests for TTLCache utility."""

from unittest.mock import patch

import pytest

from app.utils.ttl_cache import TTLCache, _MISSING


@pytest.fixture
def cache():
    return TTLCache(ttl_seconds=60, maxsize=128)


@pytest.fixture
def small_cache():
    return TTLCache(ttl_seconds=60, maxsize=3)


class TestTTLCache:
    def test_set_and_get(self, cache: TTLCache):
        cache.set("key", "value")
        assert cache.get("key") == "value"

    def test_get_default_on_missing_key(self, cache: TTLCache):
        assert cache.get("missing") is None
        assert cache.get("missing", "fallback") == "fallback"

    def test_get_returns_default_after_expiry(self, cache: TTLCache):
        with patch("app.utils.ttl_cache.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            cache.set("key", "value")

            # Advance past TTL
            mock_time.monotonic.return_value = 1061.0
            assert cache.get("key") is None
            assert cache.get("key", "expired") == "expired"

    def test_contains_true_before_expiry(self, cache: TTLCache):
        with patch("app.utils.ttl_cache.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            cache.set("key", "value")

            mock_time.monotonic.return_value = 1030.0
            assert "key" in cache

    def test_contains_false_after_expiry(self, cache: TTLCache):
        with patch("app.utils.ttl_cache.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            cache.set("key", "value")

            mock_time.monotonic.return_value = 1061.0
            assert "key" not in cache

    def test_set_overwrites_existing_key(self, cache: TTLCache):
        cache.set("key", "first")
        cache.set("key", "second")
        assert cache.get("key") == "second"
        assert len(cache) == 1

    def test_lru_eviction_at_maxsize(self, small_cache: TTLCache):
        small_cache.set("a", 1)
        small_cache.set("b", 2)
        small_cache.set("c", 3)
        assert len(small_cache) == 3

        # Adding a 4th entry should evict the oldest ("a")
        small_cache.set("d", 4)
        assert len(small_cache) == 3
        assert small_cache.get("a") is None
        assert small_cache.get("b") == 2
        assert small_cache.get("d") == 4

    def test_clear(self, cache: TTLCache):
        cache.set("a", 1)
        cache.set("b", 2)
        assert len(cache) == 2

        cache.clear()
        assert len(cache) == 0
        assert cache.get("a") is None

    def test_len(self, cache: TTLCache):
        assert len(cache) == 0
        cache.set("a", 1)
        assert len(cache) == 1
        cache.set("b", 2)
        assert len(cache) == 2
        cache.set("a", 3)  # overwrite
        assert len(cache) == 2

    def test_none_value_stored_and_retrieved(self, cache: TTLCache):
        cache.set("key", None)
        # get() with _MISSING sentinel proves None is stored, not a miss
        result = cache.get("key", _MISSING)
        assert result is None
        assert result is not _MISSING

    def test_move_to_end_on_get(self, small_cache: TTLCache):
        small_cache.set("a", 1)
        small_cache.set("b", 2)
        small_cache.set("c", 3)

        # Access "a" to make it most-recently used
        small_cache.get("a")

        # Adding "d" should now evict "b" (oldest unused), not "a"
        small_cache.set("d", 4)
        assert small_cache.get("a") == 1  # still present
        assert small_cache.get("b") is None  # evicted
        assert small_cache.get("c") == 3
        assert small_cache.get("d") == 4

    def test_concurrent_expiry_no_keyerror(self, cache: TTLCache):
        """Simulate two callers expiring the same key — must not raise KeyError.

        In asyncio, two coroutines can both read the expired entry before either
        deletes it. pop(key, None) ensures the second delete is a no-op.
        """
        with patch("app.utils.ttl_cache.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            cache.set("key", "val")

            mock_time.monotonic.return_value = 1061.0

            # First caller expires and removes it
            assert cache.get("key") is None
            # Entry is already gone — second caller must not crash
            assert cache.get("key") is None
            assert "key" not in cache
