"""
Health Review Scheduler Service.

Handles automated weekly health reviews for all services.
Runs as a background task in the worker, checking hourly for due reviews.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import (
    ReviewSchedule,
    ReviewStatus,
    ReviewTriggeredBy,
    Service,
    ServiceReview,
)
from app.workers.health_review_worker import publish_health_review_job

logger = logging.getLogger(__name__)


class HealthReviewScheduler:
    """
    Scheduler that triggers weekly health reviews for all services.

    Runs in background, checks periodically for due reviews based on
    ReviewSchedule.next_scheduled_at.
    """

    async def check_and_trigger_reviews(self) -> Dict[str, int]:
        """
        Main scheduler entry point.

        Checks for all due reviews and triggers them.

        Returns:
            Dict with counts: {"triggered": N, "failed": N, "skipped": N}
        """
        logger.info("Health Review Scheduler: Checking for due reviews...")

        async with AsyncSessionLocal() as db:
            # Find all due schedules
            due_schedules = await self._get_due_schedules(db)

            if not due_schedules:
                logger.info("Health Review Scheduler: No reviews due")
                return {"triggered": 0, "failed": 0, "skipped": 0}

            logger.info(f"Health Review Scheduler: Found {len(due_schedules)} due reviews")

            # Group by workspace for efficient processing
            workspace_schedules: Dict[str, List[ReviewSchedule]] = {}
            for schedule in due_schedules:
                if schedule.workspace_id not in workspace_schedules:
                    workspace_schedules[schedule.workspace_id] = []
                workspace_schedules[schedule.workspace_id].append(schedule)

            # Process each workspace
            results = {"triggered": 0, "failed": 0, "skipped": 0}

            for workspace_id, schedules in workspace_schedules.items():
                workspace_results = await self._trigger_workspace_reviews(
                    db, workspace_id, schedules
                )
                results["triggered"] += workspace_results["triggered"]
                results["failed"] += workspace_results["failed"]
                results["skipped"] += workspace_results["skipped"]

            logger.info(
                f"Health Review Scheduler: Completed - "
                f"{results['triggered']} triggered, "
                f"{results['skipped']} skipped, "
                f"{results['failed']} failed"
            )

            return results

    async def _get_due_schedules(self, db: AsyncSession) -> List[ReviewSchedule]:
        """Get all schedules that are due for review."""
        now = datetime.now(timezone.utc)

        stmt = (
            select(ReviewSchedule)
            .where(ReviewSchedule.enabled)
            .where(ReviewSchedule.next_scheduled_at <= now)
        )

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def _trigger_workspace_reviews(
        self,
        db: AsyncSession,
        workspace_id: str,
        schedules: List[ReviewSchedule],
    ) -> Dict[str, int]:
        """
        Trigger reviews for all due services in a workspace.

        Args:
            db: Database session
            workspace_id: Workspace ID
            schedules: List of due schedules for this workspace

        Returns:
            Dict with counts for this workspace
        """
        results = {"triggered": 0, "failed": 0, "skipped": 0}

        # Calculate review period (last 7 days)
        now = datetime.now(timezone.utc)
        week_end = now
        week_start = now - timedelta(days=7)

        for schedule in schedules:
            try:
                # Check if service still exists
                service = await db.get(Service, schedule.service_id)
                if not service:
                    logger.warning(
                        f"Service {schedule.service_id} not found, skipping schedule"
                    )
                    results["skipped"] += 1
                    await self._update_schedule_next_run(db, schedule, success=False)
                    continue

                # Check for existing in-progress review
                existing = await self._check_existing_review(
                    db, schedule.service_id, week_start, week_end
                )
                if existing:
                    logger.info(
                        f"Service {service.name} already has in-progress review, skipping"
                    )
                    results["skipped"] += 1
                    continue

                # Create review record
                review_id = str(uuid.uuid4())
                review = ServiceReview(
                    id=review_id,
                    service_id=schedule.service_id,
                    workspace_id=workspace_id,
                    status=ReviewStatus.QUEUED,
                    triggered_by=ReviewTriggeredBy.SCHEDULER,
                    review_week_start=week_start,
                    review_week_end=week_end,
                )
                db.add(review)
                await db.flush()

                # Publish to SQS
                published = await publish_health_review_job(
                    review_id=review_id,
                    workspace_id=workspace_id,
                    service_id=schedule.service_id,
                )

                if published:
                    logger.info(f"Triggered review for service {service.name}")
                    results["triggered"] += 1
                    await self._update_schedule_next_run(
                        db, schedule, success=True, review_id=review_id
                    )
                else:
                    logger.error(f"Failed to publish review for service {service.name}")
                    results["failed"] += 1
                    await self._update_schedule_next_run(
                        db, schedule, success=False, error="Failed to publish to SQS"
                    )

            except Exception as e:
                logger.exception(f"Error triggering review for schedule {schedule.id}: {e}")
                results["failed"] += 1
                await self._update_schedule_next_run(
                    db, schedule, success=False, error=str(e)
                )

        await db.commit()
        return results

    async def _check_existing_review(
        self,
        db: AsyncSession,
        service_id: str,
        week_start: datetime,
        week_end: datetime,
    ) -> ServiceReview | None:
        """Check for existing in-progress review."""
        stmt = (
            select(ServiceReview)
            .where(ServiceReview.service_id == service_id)
            .where(ServiceReview.status.in_([ReviewStatus.QUEUED, ReviewStatus.GENERATING]))
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _update_schedule_next_run(
        self,
        db: AsyncSession,
        schedule: ReviewSchedule,
        success: bool,
        review_id: str = None,
        error: str = None,
    ):
        """
        Update schedule after triggering (or failing to trigger) a review.

        Calculates next_scheduled_at based on:
        - generation_day_of_week (0=Monday, 6=Sunday)
        - generation_hour_utc (0-23)
        """
        now = datetime.now(timezone.utc)

        # Calculate next scheduled time
        next_run = self._calculate_next_scheduled_at(
            schedule.generation_day_of_week,
            schedule.generation_hour_utc,
        )

        # Update schedule
        schedule.next_scheduled_at = next_run

        if success:
            schedule.last_review_id = review_id
            schedule.last_review_generated_at = now
            schedule.last_review_status = ReviewStatus.QUEUED.value
            schedule.consecutive_failures = 0
            schedule.last_error = None
        else:
            schedule.consecutive_failures += 1
            schedule.last_error = error

        await db.flush()

    def _calculate_next_scheduled_at(
        self,
        day_of_week: int,
        hour_utc: int,
    ) -> datetime:
        """
        Calculate the next scheduled datetime.

        Args:
            day_of_week: 0=Monday, 6=Sunday
            hour_utc: Hour in UTC (0-23)

        Returns:
            Next scheduled datetime (always in the future)
        """
        now = datetime.now(timezone.utc)

        # Find next occurrence of the target day
        days_ahead = day_of_week - now.weekday()
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7

        next_date = now.date() + timedelta(days=days_ahead)
        next_run = datetime(
            next_date.year,
            next_date.month,
            next_date.day,
            hour_utc,
            0,
            0,
            tzinfo=timezone.utc,
        )

        # If the calculated time is in the past (same day, earlier hour), add a week
        if next_run <= now:
            next_run += timedelta(days=7)

        return next_run


# Singleton instance
health_review_scheduler = HealthReviewScheduler()
