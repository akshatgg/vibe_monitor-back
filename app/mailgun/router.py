"""
Mailgun API routes.
"""

import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.auth.services.google_auth_service import AuthService
from app.models import User, MailgunEmail, SlackInstallation, Membership
from app.mailgun.service import mailgun_service, verify_scheduler_token
from app.mailgun.schemas import EmailResponse, ContactFormRequest

logger = logging.getLogger(__name__)
auth_service = AuthService()

router = APIRouter(prefix="/mailgun", tags=["mailgun"])


@router.post("/nudge-email", response_model=EmailResponse)
async def send_welcome_email(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Send a welcome email to the currently authenticated user.

    This endpoint sends a beautifully formatted welcome email using the
    welcome.html template from the templates folder.

    Args:
        db: Async database session
        current_user: Currently authenticated user

    Returns:
        EmailResponse with email sending status
    """
    try:
        result = await mailgun_service.send_welcome_email(
            user_id=current_user.id,
            db=db,
        )
        return EmailResponse(**result)

    except Exception as e:
        logger.error(f"Failed to send welcome email: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send welcome email",
        )


@router.post("/send-slack-nudge-emails")
async def send_slack_nudge_emails(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_scheduler_token),
):
    """
    Send Slack integration nudge emails to eligible users.

    Eligibility criteria:
    - User created account 5+ days ago (for first email)
    - OR last email sent 5+ days ago (for follow-up emails)
    - User has NOT integrated Slack yet
    - User has received less than 5 emails (max limit)

    Returns:
        Summary of emails sent
    """
    try:
        # Subject for Slack integration emails (must match exactly with service.py)
        slack_email_subject = (
            "Don't Miss Critical Server Alerts - Integrate Slack & Grafana!"
        )

        # Calculate 5 days ago
        five_days_ago = datetime.now(timezone.utc) - timedelta(days=5)

        # Get all users
        users_result = await db.execute(select(User))
        all_users = users_result.scalars().all()

        eligible_users = []

        for user in all_users:
            # Check if user has Slack integration in any of their workspaces
            # Get all workspace IDs for this user
            user_workspaces = await db.execute(
                select(Membership.workspace_id).where(Membership.user_id == user.id)
            )
            workspace_ids = [ws_id for (ws_id,) in user_workspaces.all()]

            if not workspace_ids:
                # User has no workspaces, skip
                continue

            # Check if any of the user's workspaces have Slack integrated
            slack_check = await db.execute(
                select(SlackInstallation).where(
                    SlackInstallation.workspace_id.in_(workspace_ids)
                )
            )
            has_slack = slack_check.scalar_one_or_none() is not None

            if has_slack:
                # User already integrated Slack in  workspace, skip
                continue

            # Count how many SUCCESSFULLY sent Slack nudge emails this user has received
            email_count_result = await db.execute(
                select(func.count(MailgunEmail.id))
                .where(MailgunEmail.user_id == user.id)
                .where(MailgunEmail.subject == slack_email_subject)
                .where(MailgunEmail.status == "sent")  # Only count successful emails
            )
            email_count = email_count_result.scalar()

            if email_count >= 5:
                # User already received 5 emails, skip
                continue

            # Get last SUCCESSFULLY sent email to this user
            last_email_result = await db.execute(
                select(MailgunEmail)
                .where(MailgunEmail.user_id == user.id)
                .where(MailgunEmail.subject == slack_email_subject)
                .where(MailgunEmail.status == "sent")  # Only check successful emails
                .order_by(MailgunEmail.sent_at.desc())
                .limit(1)
            )
            last_email = last_email_result.scalar_one_or_none()

            # Determine if user is eligible
            if last_email:
                # User has received email before, check if it's been MORE THAN 5 days
                # last_email.sent_at should be OLDER than five_days_ago
                if last_email.sent_at < five_days_ago:
                    eligible_users.append(user)
                # else: Email sent within last 5 days, skip
            else:
                # User never received this email, check if account is MORE THAN 5 days old
                if user.created_at < five_days_ago:
                    eligible_users.append(user)

        # Send emails to eligible users
        sent_count = 0
        failed_count = 0

        for user in eligible_users:
            try:
                await mailgun_service.send_slack_integration_email(
                    user_id=user.id,
                    db=db,
                )
                sent_count += 1
            except Exception as e:
                logger.error(
                    f"Failed to send slack nudge email to user {user.id}: {str(e)}"
                )
                failed_count += 1

        return {
            "success": True,
            "message": "Slack nudge emails processed",
            "sent": sent_count,
            "failed": failed_count,
            "total_eligible": len(eligible_users),
        }

    except Exception as e:
        logger.error(f"Failed to process slack nudge emails: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process slack nudge emails: {str(e)}",
        )


@router.post("/contact-form", response_model=EmailResponse)
async def submit_contact_form(
    request: ContactFormRequest,
):
    """
    Submit a contact form to reach support@vibemonitor.ai.

    This is a public endpoint (no authentication required) that allows
    potential customers or users to contact the VibeMonitor team.

    Note: This endpoint does NOT store contact form data in the database.
    It only sends an email to the configured recipient.

    Args:
        request: Contact form data (name, work_email, interested_topics)

    Returns:
        EmailResponse with email submission status
    """
    try:
        result = await mailgun_service.send_contact_form_email(
            name=request.name,
            work_email=request.work_email,
            interested_topics=request.interested_topics,
        )
        return EmailResponse(**result)

    except Exception as e:
        logger.error(f"Failed to send contact form email: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit contact form. Please try again later.",
        )
