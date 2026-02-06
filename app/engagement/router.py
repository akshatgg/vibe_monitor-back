"""
Engagement API routes.

Provides endpoints for engagement reporting, triggered by external scheduler.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.email_service.service import verify_scheduler_token
from app.engagement.service import engagement_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/engagement", tags=["engagement"])


@router.post("/send-daily-report")
async def send_daily_engagement_report(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_scheduler_token),
):
    """
    Generate and send the daily engagement report to Slack.

    This endpoint is called by an external scheduler (GitHub Actions cron).
    It generates engagement metrics and posts them to the configured Slack channel.

    Authentication: Requires X-Scheduler-Token header.

    Returns:
        Dict with report summary and send status
    """
    logger.info("Daily engagement report triggered via API")

    try:
        report, slack_sent, error_msg = await engagement_service.send_daily_report(db)

        if slack_sent:
            logger.info(
                f"Daily engagement report sent. "
                f"Signups: {report.signups.last_1_day} (1d), "
                f"Active workspaces: {report.active_workspaces.last_1_day} (1d)"
            )
            return {
                "success": True,
                "slack_sent": True,
                "report": {
                    "signups_1d": report.signups.last_1_day,
                    "signups_7d": report.signups.last_7_days,
                    "active_workspaces_1d": report.active_workspaces.last_1_day,
                    "active_workspaces_7d": report.active_workspaces.last_7_days,
                },
                "message": "Engagement report sent to Slack",
            }
        else:
            logger.error(f"Failed to send engagement report: {error_msg}")
            return {
                "success": False,
                "slack_sent": False,
                "error": error_msg,
                "message": "Failed to send to Slack",
            }

    except Exception as e:
        logger.exception(f"Engagement report failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report generation failed: {str(e)}",
        )
