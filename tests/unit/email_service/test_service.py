"""
Unit tests for EmailService.
Focuses on pure functions and validation logic (no database operations).
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.email_service.service import EmailService, verify_scheduler_token


class TestVerifySchedulerToken:
    """Tests for verify_scheduler_token dependency."""

    @patch("app.email_service.service.settings")
    def test_valid_token_returns_true(self, mock_settings):
        """Valid token returns True."""
        mock_settings.SCHEDULER_SECRET_TOKEN = "secret-token-123"

        result = verify_scheduler_token("secret-token-123")
        assert result is True

    @patch("app.email_service.service.settings")
    def test_invalid_token_raises_401(self, mock_settings):
        """Invalid token raises HTTPException with 401."""
        mock_settings.SCHEDULER_SECRET_TOKEN = "secret-token-123"

        with pytest.raises(HTTPException) as exc_info:
            verify_scheduler_token("wrong-token")

        assert exc_info.value.status_code == 401
        assert "Invalid scheduler token" in exc_info.value.detail

    @patch("app.email_service.service.settings")
    def test_missing_server_token_raises_500(self, mock_settings):
        """Missing server token configuration raises 500."""
        mock_settings.SCHEDULER_SECRET_TOKEN = None

        with pytest.raises(HTTPException) as exc_info:
            verify_scheduler_token("any-token")

        assert exc_info.value.status_code == 500
        assert "not configured" in exc_info.value.detail

    @patch("app.email_service.service.settings")
    def test_empty_server_token_raises_500(self, mock_settings):
        """Empty server token configuration raises 500."""
        mock_settings.SCHEDULER_SECRET_TOKEN = ""

        with pytest.raises(HTTPException) as exc_info:
            verify_scheduler_token("any-token")

        assert exc_info.value.status_code == 500
        assert "not configured" in exc_info.value.detail

    @patch("app.email_service.service.settings")
    def test_empty_request_token_raises_401(self, mock_settings):
        """Empty request token raises 401."""
        mock_settings.SCHEDULER_SECRET_TOKEN = "secret-token-123"

        with pytest.raises(HTTPException) as exc_info:
            verify_scheduler_token("")

        assert exc_info.value.status_code == 401

    @patch("app.email_service.service.settings")
    def test_similar_token_raises_401(self, mock_settings):
        """Similar but not exact token raises 401."""
        mock_settings.SCHEDULER_SECRET_TOKEN = "secret-token-123"

        with pytest.raises(HTTPException) as exc_info:
            verify_scheduler_token("secret-token-1234")

        assert exc_info.value.status_code == 401


class TestEmailServiceRenderTemplate:
    """Tests for _render_template method - XSS prevention via HTML escaping."""

    def setup_method(self):
        """Create an EmailService instance."""
        with patch("app.email_service.service.settings") as mock_settings:
            mock_settings.POSTMARK_SERVER_TOKEN = "test-token"
            mock_settings.COMPANY_EMAIL_FROM_ADDRESS = "test@example.com"
            mock_settings.PERSONAL_EMAIL_FROM_ADDRESS = "personal@example.com"
            mock_settings.COMPANY_EMAIL_FROM_NAME = "Test Company"
            self.service = EmailService()

    def test_render_template_basic_substitution(self):
        """Basic variable substitution works."""
        template = "Hello, {{name}}!"
        result = self.service._render_template(template, name="World")

        assert result == "Hello, World!"

    def test_render_template_multiple_variables(self):
        """Multiple variables are substituted."""
        template = "Hello, {{first_name}} {{last_name}}!"
        result = self.service._render_template(
            template, first_name="John", last_name="Doe"
        )

        assert result == "Hello, John Doe!"

    def test_render_template_repeated_variable(self):
        """Repeated variable is substituted everywhere."""
        template = "{{name}} says hello to {{name}}"
        result = self.service._render_template(template, name="Alice")

        assert result == "Alice says hello to Alice"

    def test_render_template_escapes_html_angle_brackets(self):
        """XSS: HTML angle brackets are escaped."""
        template = "Message: {{content}}"
        result = self.service._render_template(
            template, content="<script>alert('xss')</script>"
        )

        assert "<script>" not in result
        assert "&lt;script&gt;" in result
        assert "&lt;/script&gt;" in result

    def test_render_template_escapes_html_quotes(self):
        """XSS: HTML quotes are escaped."""
        template = "Message: {{content}}"
        result = self.service._render_template(template, content='Hello "World"')

        assert '"World"' not in result
        assert "&quot;World&quot;" in result

    def test_render_template_escapes_ampersand(self):
        """XSS: Ampersand is escaped."""
        template = "Message: {{content}}"
        result = self.service._render_template(template, content="Tom & Jerry")

        assert " & " not in result
        assert "&amp;" in result

    def test_render_template_escapes_single_quotes(self):
        """XSS: Single quotes are escaped."""
        template = "Message: {{content}}"
        result = self.service._render_template(template, content="It's a test")

        assert "It's" not in result
        assert "&#x27;" in result or "It&#x27;s" in result

    def test_render_template_xss_event_handler(self):
        """XSS: Event handler injection is escaped - angle brackets and quotes neutralized."""
        template = "<div>{{user_input}}</div>"
        result = self.service._render_template(
            template, user_input='<img src="x" onerror="alert(1)">'
        )

        # The < and > should be escaped, neutralizing the tag
        assert "&lt;img" in result
        assert "&gt;" in result
        # Quotes should be escaped, neutralizing the attribute value
        assert "&quot;" in result
        # The raw unescaped tag should not exist
        assert "<img" not in result

    def test_render_template_xss_javascript_url(self):
        """XSS: JavaScript URL is escaped."""
        template = '<a href="{{url}}">Click</a>'
        result = self.service._render_template(template, url="javascript:alert('xss')")

        # Single quotes should be escaped
        assert "&#x27;" in result or "'" not in result.replace("'xss'", "")

    def test_render_template_preserves_template_html(self):
        """Template HTML (not user input) is preserved."""
        template = "<div class='container'>{{content}}</div>"
        result = self.service._render_template(template, content="Hello")

        assert "<div class='container'>" in result
        assert "</div>" in result
        assert "Hello" in result

    def test_render_template_integer_value(self):
        """Integer values are converted to string."""
        template = "Count: {{count}}"
        result = self.service._render_template(template, count=42)

        assert result == "Count: 42"

    def test_render_template_none_value(self):
        """None values are converted to 'None' string."""
        template = "Value: {{value}}"
        result = self.service._render_template(template, value=None)

        assert result == "Value: None"

    def test_render_template_empty_string(self):
        """Empty string value is handled."""
        template = "Name: {{name}}"
        result = self.service._render_template(template, name="")

        assert result == "Name: "

    def test_render_template_missing_variable_unchanged(self):
        """Missing variable placeholder remains unchanged."""
        template = "Hello, {{name}} and {{other}}!"
        result = self.service._render_template(template, name="World")

        assert result == "Hello, World and {{other}}!"

    def test_render_template_unicode_preserved(self):
        """Unicode characters are preserved."""
        template = "Greeting: {{greeting}}"
        result = self.service._render_template(template, greeting="Hello!")

        # Note: The emoji might be escaped but should be safe
        assert "Hello" in result

    def test_render_template_url_preserved(self):
        """URLs with safe characters are preserved (aside from escaping)."""
        template = "Link: {{url}}"
        result = self.service._render_template(
            template, url="https://example.com/path?query=value"
        )

        # Query string amp should be escaped
        assert "https://example.com/path" in result

    def test_render_template_complex_html_escape(self):
        """Complex HTML attack vector is fully escaped."""
        template = "{{input}}"
        malicious = '<svg onload="alert(document.cookie)">'
        result = self.service._render_template(template, input=malicious)

        assert "<svg" not in result
        assert "&lt;svg" in result
        assert "onload" in result  # The attribute name is safe, quotes are escaped


class TestEmailServiceInit:
    """Tests for EmailService initialization."""

    @patch("app.email_service.service.settings")
    def test_init_stores_server_token(self, mock_settings):
        """EmailService stores the Postmark server token."""
        mock_settings.POSTMARK_SERVER_TOKEN = "test-postmark-token"
        mock_settings.COMPANY_EMAIL_FROM_ADDRESS = "company@example.com"
        mock_settings.PERSONAL_EMAIL_FROM_ADDRESS = "personal@example.com"
        mock_settings.COMPANY_EMAIL_FROM_NAME = "Company Name"

        service = EmailService()

        assert service.server_token == "test-postmark-token"

    @patch("app.email_service.service.settings")
    def test_init_with_missing_token(self, mock_settings):
        """EmailService initializes even with missing token (validation on send)."""
        mock_settings.POSTMARK_SERVER_TOKEN = None
        mock_settings.COMPANY_EMAIL_FROM_ADDRESS = "company@example.com"
        mock_settings.PERSONAL_EMAIL_FROM_ADDRESS = "personal@example.com"
        mock_settings.COMPANY_EMAIL_FROM_NAME = "Company Name"

        service = EmailService()

        assert service.server_token is None
