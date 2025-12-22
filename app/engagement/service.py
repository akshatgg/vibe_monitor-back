"""
Engagement service for daily metrics reporting.

Provides:
- User signup metrics (1 day, 7 days, 30 days, total)
- Active workspace metrics (workspaces with jobs in period)
- Slack notification for daily reports
"""

import httpx
import logging
from datetime import datetime, timezone, timedelta
from typing import Tuple

from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import User, Workspace, RefreshToken, Membership
from app.engagement.schemas import (
    MetricPeriod,
    EngagementReport,
)

logger = logging.getLogger(__name__)


class EngagementService:
    """Service for engagement metrics and reporting."""

    async def get_signup_metrics(self, db: AsyncSession) -> MetricPeriod:
        """
        Get user signup metrics for different time periods.

        Args:
            db: Async database session

        Returns:
            MetricPeriod with signup counts for 1 day, 7 days, 30 days, and total
        """
        now = datetime.now(timezone.utc)
        one_day_ago = now - timedelta(days=1)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        # Get counts for each period
        last_1_day = await self._count_users_since(db, one_day_ago)
        last_7_days = await self._count_users_since(db, seven_days_ago)
        last_30_days = await self._count_users_since(db, thirty_days_ago)
        total = await self._count_users_since(db, None)

        return MetricPeriod(
            last_1_day=last_1_day,
            last_7_days=last_7_days,
            last_30_days=last_30_days,
            total=total,
        )

    async def _count_users_since(self, db: AsyncSession, since: datetime | None) -> int:
        """Count users created since a given datetime."""
        query = select(func.count(User.id))
        if since:
            query = query.where(User.created_at >= since)

        result = await db.execute(query)
        return result.scalar() or 0

    async def get_active_workspace_metrics(self, db: AsyncSession) -> MetricPeriod:
        """
        Get active workspace metrics for different time periods.

        A workspace is considered "active" if at least one of its members
        has logged in during the given time period (based on RefreshToken creation).

        Args:
            db: Async database session

        Returns:
            MetricPeriod with active workspace counts for 1 day, 7 days, 30 days, and total
        """
        now = datetime.now(timezone.utc)
        one_day_ago = now - timedelta(days=1)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        # Get counts for each period
        last_1_day = await self._count_active_workspaces_since(db, one_day_ago)
        last_7_days = await self._count_active_workspaces_since(db, seven_days_ago)
        last_30_days = await self._count_active_workspaces_since(db, thirty_days_ago)
        total = await self._count_total_workspaces(db)

        return MetricPeriod(
            last_1_day=last_1_day,
            last_7_days=last_7_days,
            last_30_days=last_30_days,
            total=total,
        )

    async def _count_active_workspaces_since(
        self, db: AsyncSession, since: datetime
    ) -> int:
        """
        Count workspaces where at least one member has logged in since a given datetime.

        Login activity is tracked via RefreshToken creation.
        """
        # Subquery: get user_ids who have logged in since the given time
        logged_in_users = (
            select(distinct(RefreshToken.user_id))
            .where(RefreshToken.created_at >= since)
            .subquery()
        )

        # Count distinct workspaces where any member has logged in
        query = select(func.count(distinct(Membership.workspace_id))).where(
            Membership.user_id.in_(select(logged_in_users))
        )
        result = await db.execute(query)
        return result.scalar() or 0

    async def _count_total_workspaces(self, db: AsyncSession) -> int:
        """Count total workspaces."""
        query = select(func.count(Workspace.id))
        result = await db.execute(query)
        return result.scalar() or 0

    async def generate_engagement_report(self, db: AsyncSession) -> EngagementReport:
        """
        Generate a complete engagement report.

        Args:
            db: Async database session

        Returns:
            EngagementReport with signup and active workspace metrics
        """
        signup_metrics = await self.get_signup_metrics(db)
        active_workspace_metrics = await self.get_active_workspace_metrics(db)

        return EngagementReport(
            report_date=datetime.now(timezone.utc),
            signups=signup_metrics,
            active_workspaces=active_workspace_metrics,
        )

    def format_slack_message(self, report: EngagementReport) -> str:
        report_date = report.report_date.strftime("%B %d, %Y")
        return f"""
    📊 *Daily Engagement Report*  
    🗓️ _{report_date}_

    ━━━━━━━━━━━━━━━━━━━━━━
    👤 *User Signups*
    • *Last 24h:* `{report.signups.last_1_day}`
    • *Last 7 days:* `{report.signups.last_7_days}`
    • *Last 30 days:* `{report.signups.last_30_days}`
    • *Total:* `{report.signups.total}`

    ━━━━━━━━━━━━━━━━━━━━━━
    🏢 *Active Workspaces*
    • *Last 24h:* `{report.active_workspaces.last_1_day}`
    • *Last 7 days:* `{report.active_workspaces.last_7_days}`
    • *Last 30 days:* `{report.active_workspaces.last_30_days}`
    • *Total:* `{report.active_workspaces.total}`

    ━━━━━━━━━━━━━━━━━━━━━━
    """.strip()

    async def send_to_slack(self, message: str) -> Tuple[bool, str]:
        """
        Send a message to Slack via webhook.

        Args:
            message: Message text to send

        Returns:
            Tuple of (success: bool, error_message: str)
        """
        webhook_url = settings.ENGAGEMENT_SLACK_WEBHOOK_URL

        if not webhook_url:
            logger.warning("ENGAGEMENT_SLACK_WEBHOOK_URL not configured")
            return False, "Slack webhook URL not configured"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    webhook_url,
                    json={"text": message},
                    timeout=settings.ENGAGEMENT_SLACK_TIMEOUT,
                )
                response.raise_for_status()

                logger.info("Engagement report sent to Slack successfully")
                return True, ""

        except httpx.HTTPStatusError as e:
            error_msg = f"Slack webhook returned error: {e.response.status_code}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Failed to send to Slack: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    async def send_daily_report(
        self, db: AsyncSession
    ) -> Tuple[EngagementReport, bool, str]:
        """
        Generate and send the daily engagement report to Slack.

        Args:
            db: Async database session

        Returns:
            Tuple of (report, slack_sent, error_message)
        """
        # Generate the report
        report = await self.generate_engagement_report(db)

        # Format and send to Slack
        message = self.format_slack_message(report)
        slack_sent, error_msg = await self.send_to_slack(message)

        return report, slack_sent, error_msg


# Singleton instance
engagement_service = EngagementService()
