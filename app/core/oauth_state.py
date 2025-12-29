"""
OAuth state management for CSRF protection.

For production with multiple instances, replace in-memory cache with Redis.
"""

import time
from threading import Lock
from typing import Dict


class OAuthStateManager:
    """Thread-safe in-memory state manager with TTL support."""

    def __init__(self):
        self._states: Dict[str, float] = {}  # {state: expiration_timestamp}
        self._lock = Lock()

    def store_state(self, state: str, ttl_seconds: int = 300) -> None:
        """
        Store OAuth state with expiration.

        Args:
            state: The state value to store
            ttl_seconds: Time to live in seconds (default: 300 = 5 minutes)
        """
        expires_at = time.time() + ttl_seconds
        with self._lock:
            self._states[state] = expires_at

    def validate_and_consume_state(self, state: str) -> bool:
        """
        Validate OAuth state and delete it (one-time use).

        Args:
            state: The state value to validate

        Returns:
            True if state is valid and not expired, False otherwise
        """
        if not state:
            return False

        with self._lock:
            if state not in self._states:
                return False

            expires_at = self._states[state]

            # Check if expired
            if time.time() > expires_at:
                del self._states[state]
                return False

            # Valid state - delete to prevent replay attacks
            del self._states[state]
            return True

    def cleanup_expired(self) -> int:
        """
        Remove all expired states.

        Returns:
            Number of states removed
        """
        current_time = time.time()
        with self._lock:
            expired = [
                state
                for state, expires_at in self._states.items()
                if current_time > expires_at
            ]
            for state in expired:
                del self._states[state]
            return len(expired)


# Global instance
oauth_state_manager = OAuthStateManager()
