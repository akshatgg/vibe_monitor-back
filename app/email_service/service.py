"""
Email service for sending emails via Postmark.
"""

import html
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Email, User
from app.utils.retry_decorator import retry_external_api

logger = logging.getLogger(__name__)

# Get the templates directory path
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Postmark API endpoint
POSTMARK_API_URL = "https://api.postmarkapp.com/email"


def verify_scheduler_token(x_scheduler_token: str = Header(...)):
    """
    Verify the scheduler secret token from request header.

    Args:
        x_scheduler_token: Token from X-Scheduler-Token header

    Raises:
        HTTPException: If token is invalid or missing

    Returns:
        bool: True if token is valid
    """
    if not settings.SCHEDULER_SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scheduler token not configured on server",
        )

    if x_scheduler_token != settings.SCHEDULER_SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid scheduler token",
        )

    return True


class EmailService:
    """Service for sending emails via Postmark API"""

    def __init__(self):
        self.server_token = settings.POSTMARK_SERVER_TOKEN
        logger.info(
            f"EmailService initialized - Company: {settings.COMPANY_EMAIL_FROM_ADDRESS}, "
            f"Personal: {settings.PERSONAL_EMAIL_FROM_ADDRESS}"
        )

    async def send_email(
        self,
        to_email: str,
        subject: str,
        text: str,
        html_body: str = None,
        from_email: str = None,
        from_name: str = None,
    ) -> dict:
        """
        Send an email using Postmark API.

        Args:
            to_email: Recipient email address
            subject: Email subject
            text: Plain text content
            html_body: HTML content (optional)
            from_email: Custom from email address (optional)
            from_name: Custom from name (optional)

        Returns:
            dict: Response from Postmark API
        """
        if not self.server_token:
            raise ValueError("Postmark server token must be configured")

        # Use custom from address if provided, otherwise use company default
        if from_email:
            if from_name:
                from_address = f"{from_name} <{from_email}>"
            else:
                from_address = from_email
        else:
            from_address = f"{settings.COMPANY_EMAIL_FROM_NAME} <{settings.COMPANY_EMAIL_FROM_ADDRESS}>"

        # Build Postmark request payload
        payload = {
            "From": from_address,
            "To": to_email,
            "Subject": subject,
            "MessageStream": "outbound",
        }

        if text:
            payload["TextBody"] = text

        if html_body:
            payload["HtmlBody"] = html_body

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Postmark-Server-Token": self.server_token,
        }

        logger.info(f"Sending email - From: {from_address}, To: {to_email}")

        try:
            async with httpx.AsyncClient() as client:
                async for attempt in retry_external_api("Postmark"):
                    with attempt:
                        response = await client.post(
                            POSTMARK_API_URL,
                            json=payload,
                            headers=headers,
                            timeout=10.0,
                        )
                        response.raise_for_status()
                        result = response.json()
                        # Postmark returns MessageID in the response
                        return {"id": result.get("MessageID"), **result}
        except httpx.HTTPError as e:
            logger.error(f"Failed to send email via Postmark: {str(e)}")
            logger.error(f"Request details - From: {from_address}, To: {to_email}")
            logger.error(
                f"Response status: {e.response.status_code if hasattr(e, 'response') else 'N/A'}"
            )
            logger.error(
                f"Response body: {e.response.text if hasattr(e, 'response') else 'N/A'}"
            )
            raise

    def _load_template(self, template_name: str) -> str:
        """
        Load an email template from the templates directory.

        Args:
            template_name: Name of the template file (e.g., 'welcome.html')

        Returns:
            str: Template content
        """
        template_path = TEMPLATES_DIR / template_name
        if not template_path.exists():
            raise FileNotFoundError(f"Template {template_name} not found")

        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()

    def _render_template(self, template: str, **kwargs) -> str:
        """
        Render a template with the given variables.
        All values are HTML-escaped to prevent XSS attacks.

        Args:
            template: Template string
            **kwargs: Variables to replace in the template

        Returns:
            str: Rendered template with HTML-escaped values
        """
        rendered = template
        for key, value in kwargs.items():
            # HTML-escape all values to prevent XSS attacks
            escaped_value = html.escape(str(value))
            rendered = rendered.replace(f"{{{{{key}}}}}", escaped_value)
        return rendered

    async def send_welcome_email(self, user_id: str, db: AsyncSession) -> dict:
        """
        Send a welcome email to a user.

        Args:
            user_id: User ID to send welcome email to
            db: Async database session

        Returns:
            dict: Response containing email status and details
        """
        # Get user from database using async query
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError(f"User with id {user_id} not found")

        # Email content
        subject = "Welcome to VibeMonitor!"

        # Load and render HTML template
        template = self._load_template("welcome.html")
        html_content = self._render_template(
            template,
            user_name=user.name,
            app_url=settings.WEB_APP_URL or "https://vibemonitor.ai",
            api_base_url=settings.API_BASE_URL,
        )

        try:
            response = await self.send_email(
                to_email=user.email,
                subject=subject,
                text="",
                html_body=html_content,
            )

            # Store email record in database
            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=subject,
                message_id=response.get("id"),
                status="sent",
            )
            db.add(email_record)
            await db.commit()

            logger.info(f"Welcome email sent to user {user_id} ({user.email})")

            return {
                "success": True,
                "message": "Welcome email sent successfully",
                "email": user.email,
                "message_id": response.get("id"),
            }

        except Exception as e:
            logger.error(f"Failed to send welcome email to user {user_id}: {str(e)}")

            # Store failed email record
            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=subject,
                status="failed",
            )
            db.add(email_record)
            await db.commit()

            raise

    async def send_verification_email(
        self, user_id: str, verification_url: str, db: AsyncSession
    ) -> dict:
        """
        Send email verification link to user.

        Args:
            user_id: User ID
            verification_url: Full URL with verification token
            db: Database session

        Returns:
            dict: Email send status
        """
        # Get user from database
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError(f"User with id {user_id} not found")

        subject = "Verify your email - VibeMonitor"

        # Load and render HTML template
        template = self._load_template("email_verification.html")
        html_content = self._render_template(
            template,
            user_name=user.name,
            verification_url=verification_url,
            app_url=settings.WEB_APP_URL or "https://vibemonitor.ai",
        )

        try:
            response = await self.send_email(
                to_email=user.email,
                subject=subject,
                text="",
                html_body=html_content,
            )

            # Store email record
            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=subject,
                message_id=response.get("id"),
                status="sent",
            )
            db.add(email_record)
            await db.commit()

            logger.info(f"Verification email sent to {user.email}")

            return {
                "success": True,
                "message": "Verification email sent",
                "email": user.email,
                "message_id": response.get("id"),
            }

        except Exception as e:
            logger.error(f"Failed to send verification email: {str(e)}")

            # Store failed record
            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=subject,
                status="failed",
            )
            db.add(email_record)
            await db.commit()

            raise

    async def send_password_reset_email(
        self, user_id: str, reset_url: str, db: AsyncSession
    ) -> dict:
        """
        Send password reset link to user.

        Args:
            user_id: User ID
            reset_url: Full URL with reset token
            db: Database session

        Returns:
            dict: Email send status
        """
        # Get user from database
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError(f"User with id {user_id} not found")

        subject = "Reset your password - VibeMonitor"

        # Load and render HTML template
        template = self._load_template("password_reset.html")
        html_content = self._render_template(
            template,
            user_name=user.name,
            reset_url=reset_url,
            app_url=settings.WEB_APP_URL or "https://vibemonitor.ai",
        )

        try:
            response = await self.send_email(
                to_email=user.email,
                subject=subject,
                text="",
                html_body=html_content,
            )

            # Store email record
            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=subject,
                message_id=response.get("id"),
                status="sent",
            )
            db.add(email_record)
            await db.commit()

            logger.info(f"Password reset email sent to {user.email}")

            return {
                "success": True,
                "message": "Password reset email sent",
                "email": user.email,
                "message_id": response.get("id"),
            }

        except Exception as e:
            logger.error(f"Failed to send password reset email: {str(e)}")

            # Store failed record
            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=subject,
                status="failed",
            )
            db.add(email_record)
            await db.commit()

            raise

    async def send_slack_integration_email(
        self, user_id: str, db: AsyncSession
    ) -> dict:
        """
        Send a Slack integration nudge email to a user.

        Args:
            user_id: User ID to send email to
            db: Async database session

        Returns:
            dict: Response containing email status and details
        """
        # Get user from database using async query
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError(f"User with id {user_id} not found")

        # Email content
        subject = "Don't Miss Critical Server Alerts - Integrate Slack & Grafana!"

        # Load and render HTML template
        template = self._load_template("slack_integration.html")
        html_content = self._render_template(
            template,
            user_name=user.name,
            app_url=settings.WEB_APP_URL or "https://vibemonitor.ai",
            api_base_url=settings.API_BASE_URL,
        )

        try:
            response = await self.send_email(
                to_email=user.email,
                subject=subject,
                text="",
                html_body=html_content,
            )

            # Store email record in database
            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=subject,
                message_id=response.get("id"),
                status="sent",
            )
            db.add(email_record)
            await db.commit()

            logger.info(
                f"Slack integration email sent to user {user_id} ({user.email})"
            )

            return {
                "success": True,
                "message": "Slack integration email sent successfully",
                "email": user.email,
                "message_id": response.get("id"),
            }

        except Exception as e:
            logger.error(
                f"Failed to send slack integration email to user {user_id}: {str(e)}"
            )

            # Store failed email record
            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=subject,
                status="failed",
            )
            db.add(email_record)
            await db.commit()

            raise

    async def send_contact_form_email(
        self,
        name: str,
        work_email: str,
        interested_topics: str,
    ) -> dict:
        """
        Send a contact form submission email to support@vibemonitor.ai.

        Note: This function does NOT store any data in the database for privacy reasons.
        It only sends the email to the configured recipient.

        Args:
            name: Name of the person submitting the form
            work_email: Work email of the person
            interested_topics: Topics they're interested in

        Returns:
            dict: Response containing email status and details
        """
        # Email content
        subject = f"New Contact Form Submission from {name}"
        support_email = settings.CONTACT_FORM_RECIPIENT_EMAIL

        # Load and render HTML template
        template = self._load_template("contact_form.html")
        html_content = self._render_template(
            template,
            name=name,
            work_email=work_email,
            interested_topics=interested_topics,
            timestamp=datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC"),
            api_base_url=settings.API_BASE_URL,
        )

        # Plain text version
        text = f"""
New Contact Form Submission

Contact Name: {name}
Work Email: {work_email}
Interested Topics: {interested_topics}

Submitted on: {datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")}
        """

        try:
            response = await self.send_email(
                to_email=support_email,
                subject=subject,
                text=text,
                html_body=html_content,
            )

            logger.info(f"Contact form email sent from {work_email} to {support_email}")

            return {
                "success": True,
                "message": "Contact form submitted successfully",
                "email": support_email,
                "message_id": response.get("id"),
            }

        except Exception as e:
            logger.error(
                f"Failed to send contact form email from {work_email}: {str(e)}"
            )
            raise

    async def send_user_help_email(self, user_id: str, db: AsyncSession) -> dict:
        """
        Send an email to users offering help with setup and understanding their needs.

        Args:
            user_id: User ID to send email to
            db: Async database session

        Returns:
            dict: Response containing email status and details
        """
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError(f"User with id {user_id} not found")

        email_subject = settings.USER_HELP_EMAIL_SUBJECT
        # Load text template from file
        text_template = self._load_template("text_body/user_help.txt")
        email_text_body = self._render_template(
            text_template, sender_name=settings.PERSONAL_EMAIL_FROM_NAME
        )

        try:
            # Use personal email settings for personalized outreach
            response = await self.send_email(
                to_email=user.email,
                subject=email_subject,
                text=email_text_body,
                from_email=settings.PERSONAL_EMAIL_FROM_ADDRESS,
                from_name=settings.PERSONAL_EMAIL_FROM_NAME,
            )

            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=email_subject,
                message_id=response.get("id"),
                status="sent",
            )
            db.add(email_record)
            await db.commit()

            logger.info(f"User help email sent to user {user_id} ({user.email})")

            return {
                "success": True,
                "message": f"User help email sent to {user_id} successfully",
                "email": user.email,
                "message_id": response.get("id"),
            }

        except Exception as e:
            logger.error(f"Failed to send user help email to user {user_id}: {str(e)}")

            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=email_subject,
                status="failed",
            )
            db.add(email_record)
            await db.commit()
            raise

    async def send_usage_feedback_email(self, user_id: str, db: AsyncSession) -> dict:
        """
        Send usage feedback email to active users after 7+ days on platform.

        Args:
            user_id: User ID to send email to
            db: Async database session

        Returns:
            dict: Response containing email status and details
        """
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError(f"User with id {user_id} not found")

        email_subject = settings.USAGE_FEEDBACK_EMAIL_SUBJECT
        # Load text template from file
        text_template = self._load_template("text_body/usage_feedback.txt")
        email_text_body = self._render_template(
            text_template, sender_name=settings.PERSONAL_EMAIL_FROM_NAME
        )

        try:
            # Use personal email settings for personalized outreach
            response = await self.send_email(
                to_email=user.email,
                subject=email_subject,
                text=email_text_body,
                from_email=settings.PERSONAL_EMAIL_FROM_ADDRESS,
                from_name=settings.PERSONAL_EMAIL_FROM_NAME,
            )

            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=email_subject,
                message_id=response.get("id"),
                status="sent",
            )
            db.add(email_record)
            await db.commit()

            logger.info(f"Usage feedback email sent to user {user_id}")

            return {
                "success": True,
                "message": "Usage feedback email sent successfully",
                "email": user.email,
                "message_id": response.get("id"),
            }

        except Exception as e:
            logger.error(
                f"Failed to send usage feedback email to user {user_id}: {str(e)}"
            )

            email_record = Email(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=email_subject,
                status="failed",
            )
            db.add(email_record)
            await db.commit()
            raise

    async def send_invitation_email(
        self,
        invitee_email: str,
        workspace_name: str,
        inviter_name: str,
        role: str,
        token: str,
    ) -> dict:
        """
        Send workspace invitation email to invitee.

        Args:
            invitee_email: Email address of the person being invited
            workspace_name: Name of the workspace
            inviter_name: Name of the person who sent the invitation
            role: Role being assigned (e.g., "User", "Owner")
            token: Invitation token for accepting

        Returns:
            dict: Email send status
        """
        subject = f"You're invited to join {workspace_name} on VibeMonitor"

        # Build accept URL
        accept_url = f"{settings.WEB_APP_URL}/invite/accept?token={token}"

        # Load and render HTML template
        template = self._load_template("workspace_invitation.html")
        html_content = self._render_template(
            template,
            inviter_name=inviter_name,
            workspace_name=workspace_name,
            role=role.capitalize(),
            accept_url=accept_url,
        )

        try:
            response = await self.send_email(
                to_email=invitee_email,
                subject=subject,
                text="",
                html_body=html_content,
            )

            logger.info(
                f"Invitation email sent to {invitee_email} for workspace {workspace_name}"
            )

            return {
                "success": True,
                "message": "Invitation email sent",
                "email": invitee_email,
                "message_id": response.get("id"),
            }

        except Exception as e:
            logger.error(
                f"Failed to send invitation email to {invitee_email}: {str(e)}"
            )
            raise


# Singleton instance
email_service = EmailService()
