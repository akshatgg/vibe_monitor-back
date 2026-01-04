"""
Tests for RCA callbacks utility functions
"""

from app.services.rca.callbacks import markdown_to_slack


class TestMarkdownToSlack:
    """Tests for markdown_to_slack conversion function"""

    def test_converts_bold_syntax(self):
        """Double asterisks should convert to single asterisks"""
        assert markdown_to_slack("**bold**") == "*bold*"

    def test_converts_multiple_bold_words(self):
        """Multiple bold sections should all be converted"""
        text = "This is **bold** and this is also **bold**"
        expected = "This is *bold* and this is also *bold*"
        assert markdown_to_slack(text) == expected

    def test_preserves_single_asterisks(self):
        """Single asterisks (already Slack format) should not be changed"""
        assert markdown_to_slack("*already bold*") == "*already bold*"

    def test_preserves_backticks(self):
        """Code backticks should not be affected"""
        text = "Check the `service-name` logs"
        assert markdown_to_slack(text) == text

    def test_handles_mixed_formatting(self):
        """Mixed formatting should be handled correctly"""
        text = "**What's going on**\n\n`service-name` is failing"
        expected = "*What's going on*\n\n`service-name` is failing"
        assert markdown_to_slack(text) == expected

    def test_handles_bold_with_special_chars(self):
        """Bold text with special characters should work"""
        assert markdown_to_slack("**What's going on**") == "*What's going on*"
        assert markdown_to_slack("**Root cause**") == "*Root cause*"

    def test_handles_empty_string(self):
        """Empty string should return empty string"""
        assert markdown_to_slack("") == ""

    def test_handles_no_markdown(self):
        """Plain text without markdown should be unchanged"""
        text = "Just plain text here"
        assert markdown_to_slack(text) == text

    def test_real_world_rca_output(self):
        """Test with realistic RCA output format"""
        text = """✅ Investigation complete

**What's going on**

Users are unable to view tickets. `desk-service` is returning 404 errors.

**Root cause**

`marketplace-service` changed from POST to GET on the /verify endpoint.

**Next steps**

• Revert the change in `marketplace-service`
• Deploy and monitor"""

        expected = """✅ Investigation complete

*What's going on*

Users are unable to view tickets. `desk-service` is returning 404 errors.

*Root cause*

`marketplace-service` changed from POST to GET on the /verify endpoint.

*Next steps*

• Revert the change in `marketplace-service`
• Deploy and monitor"""

        assert markdown_to_slack(text) == expected
