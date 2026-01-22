"""
Unit tests for ChatService.
Focuses on pure functions and validation logic (no database operations).
"""

from unittest.mock import MagicMock


from app.chat.service import ChatService


class TestChatServiceGenerateTitle:
    """Tests for _generate_title method - XSS sanitization and truncation."""

    def setup_method(self):
        """Create a ChatService instance with a mock db session."""
        mock_db = MagicMock()
        self.service = ChatService(db=mock_db)

    def test_generate_title_basic_message(self):
        """Basic message is returned as-is when under max length."""
        result = self.service._generate_title("Hello world")
        assert result == "Hello world"

    def test_generate_title_strips_whitespace(self):
        """Leading and trailing whitespace is stripped."""
        result = self.service._generate_title("  Hello world  ")
        assert result == "Hello world"

    def test_generate_title_truncates_long_message(self):
        """Long messages are truncated with ellipsis."""
        long_message = "A" * 100
        result = self.service._generate_title(long_message, max_length=50)

        assert len(result) == 50
        assert result.endswith("...")
        assert result == "A" * 47 + "..."

    def test_generate_title_custom_max_length(self):
        """Custom max_length parameter is respected."""
        message = "This is a test message"
        result = self.service._generate_title(message, max_length=10)

        assert len(result) == 10
        assert result == "This is..."

    def test_generate_title_removes_angle_brackets(self):
        """XSS: Escapes < and > characters to HTML entities."""
        result = self.service._generate_title("<script>alert('xss')</script>")
        assert "<" not in result
        assert ">" not in result
        # HTML escaped string is 51 chars, so it gets truncated to 50 with "..."
        assert result == "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script..."

    def test_generate_title_removes_quotes(self):
        """XSS: Escapes single and double quotes to HTML entities."""
        result = self.service._generate_title("Test \"message\" with 'quotes'")
        assert '"' not in result
        assert "'" not in result
        assert result == "Test &quot;message&quot; with &#x27;quotes&#x27;"

    def test_generate_title_removes_ampersand(self):
        """XSS: Escapes & character to HTML entity."""
        result = self.service._generate_title("Tom & Jerry")
        # Note: & is present in the entity &amp; but not as a standalone character
        assert result == "Tom &amp; Jerry"

    def test_generate_title_xss_attack_vector_script_tag(self):
        """XSS: Script tag injection is neutralized."""
        malicious = '<img src="x" onerror="alert(1)">'
        result = self.service._generate_title(malicious)

        assert "<" not in result
        assert ">" not in result
        assert '"' not in result

    def test_generate_title_xss_attack_vector_event_handler(self):
        """XSS: Event handler injection is neutralized."""
        malicious = "Hello<div onmouseover='alert(1)'>World</div>"
        result = self.service._generate_title(malicious)

        assert "<" not in result
        assert ">" not in result
        assert "'" not in result

    def test_generate_title_empty_after_sanitization_returns_default(self):
        """HTML entities are escaped, not removed, so this test now checks entity encoding."""
        result = self.service._generate_title("<>\"'&")
        # With html.escape(), characters are converted to entities, not removed
        assert result == "&lt;&gt;&quot;&#x27;&amp;"

    def test_generate_title_empty_string_returns_default(self):
        """Empty string returns 'Untitled Chat'."""
        result = self.service._generate_title("")
        assert result == "Untitled Chat"

    def test_generate_title_whitespace_only_returns_default(self):
        """Whitespace-only string returns 'Untitled Chat'."""
        result = self.service._generate_title("   ")
        assert result == "Untitled Chat"

    def test_generate_title_unicode_preserved(self):
        """Unicode characters are preserved."""
        result = self.service._generate_title("Hello World!")
        assert result == "Hello World!"

    def test_generate_title_mixed_content(self):
        """Mixed content with valid and invalid characters - entities are escaped."""
        result = self.service._generate_title("Hello <World> & 'Friends'")
        assert result == "Hello &lt;World&gt; &amp; &#x27;Friends&#x27;"

    def test_generate_title_exactly_max_length(self):
        """Message exactly at max_length is not truncated."""
        message = "A" * 50
        result = self.service._generate_title(message, max_length=50)

        assert len(result) == 50
        assert "..." not in result
        assert result == message

    def test_generate_title_one_over_max_length(self):
        """Message one char over max_length is truncated."""
        message = "A" * 51
        result = self.service._generate_title(message, max_length=50)

        assert len(result) == 50
        assert result.endswith("...")

    def test_generate_title_preserves_numbers(self):
        """Numbers are preserved."""
        result = self.service._generate_title("Error 404: Not Found")
        assert result == "Error 404: Not Found"

    def test_generate_title_preserves_special_chars_not_in_blocklist(self):
        """Special characters not in XSS blocklist are preserved."""
        result = self.service._generate_title("Hello! How are you? #test @user")
        assert result == "Hello! How are you? #test @user"
