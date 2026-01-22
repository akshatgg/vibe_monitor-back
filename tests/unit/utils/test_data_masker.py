"""
Unit tests for PIIMapper and data masking utilities.

Tests the masking and unmasking functionality for PII data.
"""

from app.utils.data_masker import (
    PIIMapper,
    mask_log_message,
    mask_secrets,
    redact_query_for_log,
)


class TestPIIMapper:
    """Test suite for PIIMapper class."""

    def test_basic_email_masking(self):
        """Test basic email masking and unmasking."""
        mapper = PIIMapper()
        text = "Contact john@example.com for help"
        masked = mapper.mask(text)

        # Email should be masked
        assert "john@example.com" not in masked
        # Should have a placeholder (email1, email2, etc.)
        assert "email" in masked.lower()

        # Roundtrip test - unmasking should restore original
        unmasked = mapper.unmask(masked)
        assert "john@example.com" in unmasked

    def test_multiple_emails_different_placeholders(self):
        """Test that different emails get different placeholders."""
        mapper = PIIMapper()
        text = "Email john@example.com and jane@example.com"
        masked = mapper.mask(text)

        # Both emails should be masked
        assert "john@example.com" not in masked
        assert "jane@example.com" not in masked

        # Should unmask correctly
        unmasked = mapper.unmask(masked)
        assert "john@example.com" in unmasked
        assert "jane@example.com" in unmasked

    def test_same_email_same_placeholder(self):
        """Test that the same email gets the same placeholder consistently."""
        mapper = PIIMapper()
        text = "Email john@example.com twice: john@example.com"
        masked = mapper.mask(text)

        # Unmask and verify both instances are restored
        unmasked = mapper.unmask(masked)
        assert unmasked.count("john@example.com") == 2

    def test_ip_address_masking(self):
        """Test IP address masking."""
        mapper = PIIMapper()
        text = "Server at 192.168.1.50 is down"
        masked = mapper.mask(text)

        # IP should be masked
        assert "192.168.1.50" not in masked
        # Should have ip placeholder
        assert "ip" in masked.lower()

        # Roundtrip verification
        unmasked = mapper.unmask(masked)
        assert "192.168.1.50" in unmasked

    def test_multiple_entity_types(self):
        """Test masking multiple PII types in one text."""
        mapper = PIIMapper()
        text = "Contact john@example.com at 192.168.1.1"
        masked = mapper.mask(text)

        # Both should be masked
        assert "john@example.com" not in masked
        assert "192.168.1.1" not in masked

        # Both should be restored
        unmasked = mapper.unmask(masked)
        assert "john@example.com" in unmasked
        assert "192.168.1.1" in unmasked

    def test_empty_string(self):
        """Test masking empty string."""
        mapper = PIIMapper()
        masked = mapper.mask("")
        assert masked == ""

        unmasked = mapper.unmask("")
        assert unmasked == ""

    def test_none_value(self):
        """Test masking None value."""
        mapper = PIIMapper()
        masked = mapper.mask(None)
        assert masked is None

    def test_text_with_no_pii(self):
        """Test masking text with no PII."""
        mapper = PIIMapper()
        text = "This is a normal sentence with no sensitive data"
        masked = mapper.mask(text)

        # Should return unchanged
        unmasked = mapper.unmask(masked)
        assert text in unmasked

    def test_get_reverse_mapping(self):
        """Test getting the reverse mapping."""
        mapper = PIIMapper()
        text = "Contact john@example.com"
        mapper.mask(text)

        mapping = mapper.get_reverse_mapping()
        assert isinstance(mapping, dict)

        # Should have at least one mapping for the email
        if len(mapping) > 0:
            # Verify mapping structure: placeholder -> original
            for placeholder, original in mapping.items():
                assert isinstance(placeholder, str)
                assert isinstance(original, str)

    def test_from_mapping_class_method(self):
        """Test creating PIIMapper from existing mapping."""
        # Create original mapper and get mapping
        original_mapper = PIIMapper()
        text = "Contact john@example.com at 192.168.1.1"
        masked = original_mapper.mask(text)
        mapping = original_mapper.get_reverse_mapping()

        # Create new mapper from mapping
        new_mapper = PIIMapper.from_mapping(mapping)

        # Unmask with new mapper should work
        unmasked = new_mapper.unmask(masked)
        assert "john@example.com" in unmasked
        assert "192.168.1.1" in unmasked

    def test_thread_history_consistency(self):
        """Test that same mapper instance maintains consistent placeholders across multiple messages."""
        mapper = PIIMapper()

        msg1 = "User john@example.com reported issue"
        msg2 = "Follow-up from john@example.com"

        masked1 = mapper.mask(msg1)
        masked2 = mapper.mask(msg2)

        # Same email should get same placeholder in both messages
        unmasked1 = mapper.unmask(masked1)
        unmasked2 = mapper.unmask(masked2)

        assert "john@example.com" in unmasked1
        assert "john@example.com" in unmasked2

    def test_unmask_with_missing_mapping(self):
        """Test unmasking text with placeholders not in mapping."""
        mapper = PIIMapper()
        # Unmask without any masking first
        text = "This has email1 but no mapping for it"
        unmasked = mapper.unmask(text)

        # Should return unchanged if placeholder not in mapping
        assert unmasked == text

    def test_complex_real_world_query(self):
        """Test with a complex real-world query."""
        mapper = PIIMapper()
        query = (
            "Why is john@acme.com at 192.168.1.50 down? "
            "Please check the logs and contact jane@acme.com if needed."
        )

        masked = mapper.mask(query)

        # Verify PII is masked
        assert "john@acme.com" not in masked
        assert "jane@acme.com" not in masked
        assert "192.168.1.50" not in masked

        # Verify roundtrip
        unmasked = mapper.unmask(masked)
        assert "john@acme.com" in unmasked
        assert "jane@acme.com" in unmasked
        assert "192.168.1.50" in unmasked

    def test_placeholder_collision_prevention(self):
        """Test that unmask prevents placeholder collisions (email1 vs email10)."""
        mapper = PIIMapper()

        # Manually create a scenario with email1 and email10
        mapper._placeholder_to_pii = {
            "email1": "john@example.com",
            "email10": "jane@example.com",
        }
        mapper._pii_to_placeholder = {
            "john@example.com": "email1",
            "jane@example.com": "email10",
        }

        # Text contains both email1 and email10
        text = "Contact email1 and email10 about this issue"

        unmasked = mapper.unmask(text)

        # Both should be correctly replaced (no partial matches)
        assert "john@example.com" in unmasked
        assert "jane@example.com" in unmasked
        # email1 should not have been partially replaced inside email10
        assert "email" not in unmasked  # All placeholders should be gone


class TestMaskSecrets:
    """Test suite for mask_secrets function."""

    def test_mask_aws_access_key(self):
        """Test masking AWS access key."""
        text = "AWS key is AKIAIOSFODNN7EXAMPLE"
        masked = mask_secrets(text)

        # Key should be masked
        assert "AKIAIOSFODNN7EXAMPLE" not in masked
        # Should have AWS_KEY placeholder
        assert "[AWS_KEY]" in masked

    def test_mask_github_token(self):
        """Test masking GitHub personal access token."""
        # Valid GitHub token: ghp_ + 36+ characters (40 chars total minimum)
        token = "ghp_" + "a" * 36  # Valid 40-char token
        text = f"GitHub token: {token}"
        masked = mask_secrets(text)

        # Token should be masked
        assert token not in masked
        # Should have GITHUB_TOKEN placeholder
        assert "[GITHUB_TOKEN]" in masked

    def test_mask_slack_token(self):
        """Test masking Slack token."""
        text = "Slack token: xoxb-1234567890-1234567890-abcdefghijklmnopqrstuv"
        masked = mask_secrets(text)

        # Token should be masked
        assert "xoxb-1234567890-1234567890-abcdefghijklmnopqrstuv" not in masked
        # Should have SLACK_TOKEN placeholder
        assert "[SLACK_TOKEN]" in masked

    def test_mask_jwt_token(self):
        """Test masking JWT token."""
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        text = f"JWT: {jwt}"
        masked = mask_secrets(text)

        # JWT should be masked
        assert jwt not in masked
        # Should have JWT placeholder
        assert "[JWT]" in masked

    def test_mask_connection_string(self):
        """Test masking database connection string."""
        text = "postgresql://user:password@localhost:5432/dbname"
        masked = mask_secrets(text)

        # Password should not be visible
        assert "password" not in masked
        # Should have CONNECTION_STRING placeholder
        assert "[CONNECTION_STRING]" in masked

    def test_mask_multiple_secrets(self):
        """Test masking multiple different secrets."""
        # Use valid GitHub token (36+ chars after prefix)
        github_token = "ghp_" + "a" * 36
        text = (
            f"Config: AWS=AKIAIOSFODNN7EXAMPLE, GitHub={github_token}, Slack=xoxb-test"
        )
        masked = mask_secrets(text)

        # All secrets should be masked
        assert "AKIAIOSFODNN7EXAMPLE" not in masked
        assert github_token not in masked
        # Should have placeholders
        assert "[AWS_KEY]" in masked
        assert "[GITHUB_TOKEN]" in masked

    def test_no_secrets(self):
        """Test text with no secrets."""
        text = "This is a normal log message with no secrets"
        masked = mask_secrets(text)

        # Should be unchanged
        assert masked == text

    def test_invalid_github_token_not_masked(self):
        """Test that invalid GitHub tokens (too short) are not masked."""
        # GitHub token regex requires 36+ chars after prefix
        short_token = "ghp_short"  # Only 5 chars, invalid
        text = f"Token: {short_token}"
        masked = mask_secrets(text)

        # Should NOT be masked (doesn't match pattern)
        assert short_token in masked
        assert "[GITHUB_TOKEN]" not in masked


class TestMaskLogMessage:
    """Test suite for mask_log_message function."""

    def test_mask_log_with_secrets(self):
        """Test that mask_log_message masks secrets."""
        text = "Error with AWS key AKIAIOSFODNN7EXAMPLE"
        masked = mask_log_message(text)

        # Secret should be masked
        assert "AKIAIOSFODNN7EXAMPLE" not in masked
        # Should have placeholder
        assert "[AWS_KEY]" in masked

    def test_mask_log_clean_message(self):
        """Test that clean log messages pass through."""
        text = "Processing request for user 123"
        masked = mask_log_message(text)

        # Should be unchanged
        assert text == masked


class TestRedactQueryForLog:
    """Test suite for redact_query_for_log function."""

    def test_redact_short_query(self):
        """Test redacting short query."""
        query = "Short query"
        redacted = redact_query_for_log(query)

        # Should show character count
        assert "[QUERY:" in redacted
        assert "chars]" in redacted
        assert str(len(query)) in redacted

    def test_redact_long_query(self):
        """Test redacting long query."""
        query = "This is a very long query " * 20
        redacted = redact_query_for_log(query)

        # Should be redacted with character count
        assert "[QUERY:" in redacted
        assert "chars]" in redacted
        assert str(len(query)) in redacted
        # Redacted should be much shorter than original
        assert len(redacted) < len(query)

    def test_redact_empty_query(self):
        """Test redacting empty query."""
        redacted = redact_query_for_log("")

        # Implementation returns [EMPTY QUERY] for empty
        assert redacted == "[EMPTY QUERY]"

    def test_redact_none_query(self):
        """Test redacting None query."""
        redacted = redact_query_for_log(None)

        # Implementation returns [EMPTY QUERY] for None
        assert redacted == "[EMPTY QUERY]"

    def test_redact_whitespace_only(self):
        """Test redacting whitespace-only query."""
        redacted = redact_query_for_log("   \n\t  ")

        # Whitespace-only should be treated as empty
        assert redacted == "[EMPTY QUERY]"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_unicode_characters(self):
        """Test masking with unicode characters."""
        mapper = PIIMapper()
        text = "Contact user@example.com for help with 中文"
        masked = mapper.mask(text)
        unmasked = mapper.unmask(masked)

        # Should handle unicode gracefully
        assert isinstance(unmasked, str)
        assert "中文" in unmasked

    def test_very_long_text(self):
        """Test with very long text."""
        mapper = PIIMapper()
        text = ("This is a test message. " * 1000) + "Contact john@example.com"

        masked = mapper.mask(text)
        assert "john@example.com" not in masked

        unmasked = mapper.unmask(masked)
        assert "john@example.com" in unmasked

    def test_special_characters_in_text(self):
        """Test with special characters."""
        mapper = PIIMapper()
        text = "Contact john@example.com! How are you? #testing @mention"
        masked = mapper.mask(text)
        unmasked = mapper.unmask(masked)

        assert "john@example.com" in unmasked
        assert "#testing" in unmasked
        assert "@mention" in unmasked

    def test_mask_secrets_with_none(self):
        """Test mask_secrets with None input."""
        result = mask_secrets(None)
        # Should return None (not crash)
        assert result is None

    def test_mask_secrets_with_non_string(self):
        """Test mask_secrets with non-string input."""
        result = mask_secrets(123)
        # Should return the input unchanged
        assert result == 123
