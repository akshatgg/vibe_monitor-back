"""
Unit tests for engagement service.

Focuses on pure functions and validation logic (no DB).
"""

from datetime import datetime, timezone

import pytest

from app.engagement.schemas import EngagementReport, MetricPeriod
from app.engagement.service import EngagementService


class TestFormatSlackMessage:
    """Tests for EngagementService.format_slack_message()"""

    def setup_method(self):
        self.service = EngagementService()

    def test_format_slack_message_basic(self):
        """Test basic message formatting with typical values."""
        report = EngagementReport(
            report_date=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            signups=MetricPeriod(last_1_day=5, last_7_days=20, last_30_days=100, total=500),
            active_workspaces=MetricPeriod(
                last_1_day=10, last_7_days=50, last_30_days=150, total=300
            ),
        )

        message = self.service.format_slack_message(report)

        # Verify header
        assert "Daily Engagement Report" in message
        assert "January 15, 2024" in message

        # Verify signup metrics
        assert "`5`" in message  # last_1_day signups
        assert "`20`" in message  # last_7_days signups
        assert "`100`" in message  # last_30_days signups
        assert "`500`" in message  # total signups

        # Verify active workspace metrics
        assert "`10`" in message  # last_1_day active
        assert "`50`" in message  # last_7_days active
        assert "`150`" in message  # last_30_days active
        assert "`300`" in message  # total workspaces

    def test_format_slack_message_zero_values(self):
        """Test formatting when all metrics are zero."""
        report = EngagementReport(
            report_date=datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
            signups=MetricPeriod(last_1_day=0, last_7_days=0, last_30_days=0, total=0),
            active_workspaces=MetricPeriod(
                last_1_day=0, last_7_days=0, last_30_days=0, total=0
            ),
        )

        message = self.service.format_slack_message(report)

        # Should contain proper formatting even with zeros
        assert "June 01, 2024" in message
        assert "`0`" in message

    def test_format_slack_message_large_numbers(self):
        """Test formatting with large numbers."""
        report = EngagementReport(
            report_date=datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
            signups=MetricPeriod(
                last_1_day=1000, last_7_days=10000, last_30_days=100000, total=1000000
            ),
            active_workspaces=MetricPeriod(
                last_1_day=500, last_7_days=5000, last_30_days=50000, total=500000
            ),
        )

        message = self.service.format_slack_message(report)

        # Verify large numbers are formatted
        assert "`1000`" in message
        assert "`1000000`" in message
        assert "`500000`" in message

    def test_format_slack_message_contains_sections(self):
        """Test that message contains expected sections."""
        report = EngagementReport(
            report_date=datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc),
            signups=MetricPeriod(last_1_day=1, last_7_days=2, last_30_days=3, total=4),
            active_workspaces=MetricPeriod(last_1_day=5, last_7_days=6, last_30_days=7, total=8),
        )

        message = self.service.format_slack_message(report)

        # Verify section headers
        assert "User Signups" in message
        assert "Active Workspaces" in message
        assert "Last 24h" in message
        assert "Last 7 days" in message
        assert "Last 30 days" in message
        assert "Total" in message

    def test_format_slack_message_different_months(self):
        """Test date formatting for different months."""
        test_cases = [
            (datetime(2024, 1, 1, tzinfo=timezone.utc), "January 01, 2024"),
            (datetime(2024, 6, 15, tzinfo=timezone.utc), "June 15, 2024"),
            (datetime(2024, 12, 31, tzinfo=timezone.utc), "December 31, 2024"),
        ]

        for report_date, expected_date in test_cases:
            report = EngagementReport(
                report_date=report_date,
                signups=MetricPeriod(last_1_day=0, last_7_days=0, last_30_days=0, total=0),
                active_workspaces=MetricPeriod(
                    last_1_day=0, last_7_days=0, last_30_days=0, total=0
                ),
            )

            message = self.service.format_slack_message(report)
            assert expected_date in message


class TestMetricPeriodSchema:
    """Tests for MetricPeriod schema validation."""

    def test_metric_period_valid(self):
        """Test valid MetricPeriod creation."""
        metric = MetricPeriod(last_1_day=1, last_7_days=7, last_30_days=30, total=100)
        assert metric.last_1_day == 1
        assert metric.last_7_days == 7
        assert metric.last_30_days == 30
        assert metric.total == 100

    def test_metric_period_zero_values(self):
        """Test MetricPeriod with zero values."""
        metric = MetricPeriod(last_1_day=0, last_7_days=0, last_30_days=0, total=0)
        assert metric.last_1_day == 0
        assert metric.total == 0

    def test_metric_period_requires_all_fields(self):
        """Test that all fields are required."""
        with pytest.raises(Exception):  # Pydantic validation error
            MetricPeriod(last_1_day=1)  # Missing other fields


class TestEngagementReportSchema:
    """Tests for EngagementReport schema validation."""

    def test_engagement_report_valid(self):
        """Test valid EngagementReport creation."""
        report = EngagementReport(
            report_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            signups=MetricPeriod(last_1_day=1, last_7_days=2, last_30_days=3, total=4),
            active_workspaces=MetricPeriod(last_1_day=5, last_7_days=6, last_30_days=7, total=8),
        )
        assert report.signups.last_1_day == 1
        assert report.active_workspaces.total == 8

    def test_engagement_report_requires_all_fields(self):
        """Test that all fields are required."""
        with pytest.raises(Exception):
            EngagementReport(
                report_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                signups=MetricPeriod(last_1_day=1, last_7_days=2, last_30_days=3, total=4),
                # Missing active_workspaces
            )
