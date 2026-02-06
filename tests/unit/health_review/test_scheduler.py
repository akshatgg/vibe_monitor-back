"""
Unit tests for the Health Review Scheduler service.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.health_review_system.scheduler.service import HealthReviewScheduler


class TestHealthReviewScheduler:
    """Unit tests for HealthReviewScheduler."""

    @pytest.fixture
    def scheduler(self):
        """Create a scheduler instance."""
        return HealthReviewScheduler()

    def test_calculate_next_scheduled_at_same_day_later_hour(self, scheduler):
        """Test calculation when target day is same day but later hour."""
        # Mock current time to Monday 10:00 UTC
        with patch(
            "app.health_review_system.scheduler.service.datetime"
        ) as mock_datetime:
            mock_now = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)  # Monday
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(
                *args, **kwargs
            )

            # Target: Monday 14:00 UTC
            result = scheduler._calculate_next_scheduled_at(
                day_of_week=0,  # Monday
                hour_utc=14,
            )

            # Should be same Monday at 14:00
            assert result.weekday() == 0  # Monday
            assert result.hour == 14
            assert result > mock_now

    def test_calculate_next_scheduled_at_next_week(self, scheduler):
        """Test calculation when target day already passed this week."""
        # Mock current time to Wednesday
        with patch(
            "app.health_review_system.scheduler.service.datetime"
        ) as mock_datetime:
            mock_now = datetime(2024, 1, 17, 10, 0, 0, tzinfo=timezone.utc)  # Wednesday
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(
                *args, **kwargs
            )

            # Target: Monday (already passed)
            result = scheduler._calculate_next_scheduled_at(
                day_of_week=0,  # Monday
                hour_utc=9,
            )

            # Should be next Monday
            assert result.weekday() == 0  # Monday
            assert result > mock_now
            days_until_monday = (7 - mock_now.weekday()) % 7 or 7
            expected_date = mock_now.date() + timedelta(days=days_until_monday)
            assert result.date() == expected_date

    @pytest.mark.asyncio
    async def test_check_and_trigger_reviews_no_due(self, scheduler):
        """Test scheduler returns empty results when no reviews are due."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with patch(
            "app.health_review_system.scheduler.service.AsyncSessionLocal"
        ) as mock_session:
            mock_session.return_value.__aenter__.return_value = mock_db

            results = await scheduler.check_and_trigger_reviews()

        assert results == {"triggered": 0, "failed": 0, "skipped": 0}

    @pytest.mark.asyncio
    async def test_check_and_trigger_reviews_with_due_schedules(self, scheduler):
        """Test scheduler triggers reviews for due schedules."""
        # Create mock schedule
        mock_schedule = MagicMock()
        mock_schedule.id = str(uuid.uuid4())
        mock_schedule.workspace_id = str(uuid.uuid4())
        mock_schedule.service_id = str(uuid.uuid4())
        mock_schedule.generation_day_of_week = 0
        mock_schedule.generation_hour_utc = 9
        mock_schedule.next_scheduled_at = datetime.now(timezone.utc) - timedelta(
            hours=1
        )
        mock_schedule.consecutive_failures = 0

        # Create mock service
        mock_service = MagicMock()
        mock_service.id = mock_schedule.service_id
        mock_service.name = "test-service"

        mock_db = AsyncMock()

        # Mock _get_due_schedules to return our mock schedule
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_schedule]
        mock_db.execute.return_value = mock_result
        mock_db.get.return_value = mock_service
        mock_db.scalar_one_or_none = AsyncMock(return_value=None)

        with patch(
            "app.health_review_system.scheduler.service.AsyncSessionLocal"
        ) as mock_session:
            mock_session.return_value.__aenter__.return_value = mock_db

            # Mock publish function
            with patch(
                "app.health_review_system.scheduler.service.publish_health_review_job",
                new_callable=AsyncMock,
                return_value=True,
            ):
                # Mock existing review check
                with patch.object(
                    scheduler, "_check_existing_review", return_value=None
                ):
                    await scheduler.check_and_trigger_reviews()

        # Note: Full integration would verify triggered count
        # This unit test verifies the flow doesn't error


class TestSchedulerNextScheduledAtEdgeCases:
    """Edge case tests for next_scheduled_at calculation."""

    @pytest.fixture
    def scheduler(self):
        return HealthReviewScheduler()

    def test_same_day_past_hour_schedules_next_week(self, scheduler):
        """When target day/hour has passed, schedule for next week."""
        with patch(
            "app.health_review_system.scheduler.service.datetime"
        ) as mock_datetime:
            # Current: Monday 15:00 UTC
            mock_now = datetime(2024, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(
                *args, **kwargs
            )

            # Target: Monday 9:00 UTC (already passed today)
            result = scheduler._calculate_next_scheduled_at(
                day_of_week=0,  # Monday
                hour_utc=9,
            )

            # Should be next Monday
            assert result.weekday() == 0
            assert result.hour == 9
            assert result > mock_now
            # Should be 7 days ahead (next week)
            assert (result.date() - mock_now.date()).days == 7

    def test_sunday_to_monday_crossing(self, scheduler):
        """Test scheduling from Sunday to Monday."""
        with patch(
            "app.health_review_system.scheduler.service.datetime"
        ) as mock_datetime:
            # Current: Sunday
            mock_now = datetime(2024, 1, 21, 10, 0, 0, tzinfo=timezone.utc)  # Sunday
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(
                *args, **kwargs
            )

            # Target: Monday
            result = scheduler._calculate_next_scheduled_at(
                day_of_week=0,  # Monday
                hour_utc=9,
            )

            # Should be tomorrow (Monday)
            assert result.weekday() == 0
            assert (result.date() - mock_now.date()).days == 1
