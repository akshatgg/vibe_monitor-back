"""
Unit tests for deployments service.
Focuses on pure functions and validation logic (no database operations).
"""

import hashlib

import pytest

from app.deployments.service import DeploymentService
from app.models import DeploymentSource, DeploymentStatus


class TestDeploymentServiceHashKey:
    """Tests for API key hashing."""

    def test_hash_key_returns_sha256_hex(self):
        """Hash key returns SHA-256 hex digest."""
        key = "vm_test_api_key_12345"
        result = DeploymentService._hash_key(key)

        expected = hashlib.sha256(key.encode()).hexdigest()
        assert result == expected

    def test_hash_key_consistent(self):
        """Same key always produces same hash."""
        key = "vm_consistent_key"

        hash1 = DeploymentService._hash_key(key)
        hash2 = DeploymentService._hash_key(key)

        assert hash1 == hash2

    def test_hash_key_different_keys_different_hashes(self):
        """Different keys produce different hashes."""
        key1 = "vm_key_one"
        key2 = "vm_key_two"

        hash1 = DeploymentService._hash_key(key1)
        hash2 = DeploymentService._hash_key(key2)

        assert hash1 != hash2

    def test_hash_key_length(self):
        """Hash is 64 characters (SHA-256 hex)."""
        key = "vm_any_key"
        result = DeploymentService._hash_key(key)

        assert len(result) == 64

    def test_hash_key_hex_characters(self):
        """Hash contains only hex characters."""
        key = "vm_test_key"
        result = DeploymentService._hash_key(key)

        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_key_empty_string(self):
        """Empty string can be hashed."""
        result = DeploymentService._hash_key("")

        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected


class TestDeploymentServiceGenerateKey:
    """Tests for API key generation."""

    def test_generate_key_returns_tuple(self):
        """Generate key returns (full_key, prefix) tuple."""
        result = DeploymentService._generate_key()

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_generate_key_prefix_format(self):
        """Full key starts with 'vm_' prefix."""
        full_key, prefix = DeploymentService._generate_key()

        assert full_key.startswith("vm_")
        assert prefix == full_key[:8]

    def test_generate_key_prefix_length(self):
        """Prefix is first 8 characters of full key."""
        full_key, prefix = DeploymentService._generate_key()

        assert prefix == full_key[:8]
        assert len(prefix) == 8

    def test_generate_key_uniqueness(self):
        """Each call generates unique keys."""
        keys = [DeploymentService._generate_key() for _ in range(10)]

        full_keys = [k[0] for k in keys]
        prefixes = [k[1] for k in keys]

        # All full keys should be unique
        assert len(set(full_keys)) == 10
        # Prefixes might not all be unique (first 8 chars), but most should be
        assert len(set(prefixes)) >= 8

    def test_generate_key_length(self):
        """Full key has reasonable length (vm_ + 32 bytes url-safe base64)."""
        full_key, _ = DeploymentService._generate_key()

        # vm_ prefix (3) + base64 encoded 32 bytes (~43 chars)
        assert len(full_key) > 40
        assert len(full_key) < 60

    def test_generate_key_safe_characters(self):
        """Full key contains only URL-safe characters."""
        full_key, _ = DeploymentService._generate_key()

        # After vm_ prefix, should be URL-safe base64
        suffix = full_key[3:]
        assert all(c.isalnum() or c in "-_" for c in suffix)


class TestDeploymentStatusParsing:
    """Tests for DeploymentStatus enum parsing logic."""

    def test_valid_status_success(self):
        """'success' is a valid status."""
        status = DeploymentStatus("success")
        assert status == DeploymentStatus.SUCCESS

    def test_valid_status_failed(self):
        """'failed' is a valid status."""
        status = DeploymentStatus("failed")
        assert status == DeploymentStatus.FAILED

    def test_valid_status_in_progress(self):
        """'in_progress' is a valid status."""
        status = DeploymentStatus("in_progress")
        assert status == DeploymentStatus.IN_PROGRESS

    def test_valid_status_pending(self):
        """'pending' is a valid status."""
        status = DeploymentStatus("pending")
        assert status == DeploymentStatus.PENDING

    def test_invalid_status_raises(self):
        """Invalid status raises ValueError."""
        with pytest.raises(ValueError):
            DeploymentStatus("invalid_status")


class TestDeploymentSourceParsing:
    """Tests for DeploymentSource enum parsing logic."""

    def test_valid_source_manual(self):
        """'manual' is a valid source."""
        source = DeploymentSource("manual")
        assert source == DeploymentSource.MANUAL

    def test_valid_source_webhook(self):
        """'webhook' is a valid source."""
        source = DeploymentSource("webhook")
        assert source == DeploymentSource.WEBHOOK

    def test_valid_source_github_actions(self):
        """'github_actions' is a valid source."""
        source = DeploymentSource("github_actions")
        assert source == DeploymentSource.GITHUB_ACTIONS

    def test_invalid_source_raises(self):
        """Invalid source raises ValueError."""
        with pytest.raises(ValueError):
            DeploymentSource("invalid_source")
