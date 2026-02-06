"""
Simple TTL cache with optional maxsize (LRU eviction).

Uses time.monotonic for clock and OrderedDict for insertion-order tracking.
Lazy eviction: expired entries are removed on access, not in the background.
"""

import time
from collections import OrderedDict
from typing import Any

_MISSING = object()
"""Sentinel for distinguishing 'key not found' from a cached ``None`` value."""


class TTLCache:
    """Dict-like cache with per-entry TTL and optional LRU eviction."""

    def __init__(self, ttl_seconds: float, maxsize: int = 128):
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        # Stores (value, expiry_monotonic)
        self._data: OrderedDict[Any, tuple[Any, float]] = OrderedDict()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: Any, default: Any = None) -> Any:
        """Return value for *key* if present and not expired, else *default*."""
        entry = self._data.get(key)
        if entry is None:
            return default
        value, expiry = entry
        if time.monotonic() >= expiry:
            self._data.pop(key, None)
            return default
        # Move to end (most-recently used)
        self._data.move_to_end(key)
        return value

    def set(self, key: Any, value: Any) -> None:
        """Store *value* under *key*, evicting the oldest entry if at capacity."""
        if key in self._data:
            del self._data[key]
        elif len(self._data) >= self._maxsize:
            self._data.popitem(last=False)  # evict oldest
        self._data[key] = (value, time.monotonic() + self._ttl)

    def clear(self) -> None:
        """Remove all entries."""
        self._data.clear()

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __contains__(self, key: Any) -> bool:
        entry = self._data.get(key)
        if entry is None:
            return False
        if time.monotonic() >= entry[1]:
            self._data.pop(key, None)
            return False
        return True

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"TTLCache(ttl_seconds={self._ttl}, maxsize={self._maxsize}, size={len(self._data)})"
