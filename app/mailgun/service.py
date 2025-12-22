"""
Mailgun service for sending emails.
"""
import uuid
import logging
import html
import httpx
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException, status, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.utils.retry_decorator import retry_external_api
from app.models import MailgunEmail, User

logger = logging.getLogger(__name__)

# Get the templates directory path
TEMPLATES_DIR = Path(__file__).parent / "templates"


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


class MailgunService:
    """Service for sending emails via Mailgun API"""

    def __init__(self):
        self.api_key = settings.MAILGUN_API_KEY
        self.domain = settings.MAILGUN_DOMAIN_NAME
        self.base_url = f"https://api.mailgun.net/v3/{self.domain}/messages"
        logger.info(f"MailgunService initialized - Domain: {self.domain}, From: {settings.MAILGUN_FROM_EMAIL}")

    async def send_email(
        self,
        to_email: str,
        subject: str,
        text: str,
        html: str = None,
        from_email: str = None,
        from_name: str = None,
    ) -> dict:
        """
        Send an email using Mailgun API.

        Args:
            to_email: Recipient email address
            subject: Email subject
            text: Plain text content
            html: HTML content (optional)
            from_email: Custom from email address (optional)
            from_name: Custom from name (optional)

        Returns:
            dict: Response from Mailgun API
        """
        if not self.api_key or not self.domain:
            raise ValueError("Mailgun API key and domain must be configured")

        # Use custom from address if provided, otherwise use default
        if from_email:
            if from_name:
                from_address = f"{from_name} <{from_email}>"
            else:
                from_address = from_email
        else:
            from_address = f"VibeMonitor <noreply@{self.domain}>"

        data = {
            "from": from_address,
            "to": to_email,
            "subject": subject,
            "text": text,
        }

        if html:
            data["html"] = html

        logger.info(f"Sending email - From: {data['from']}, To: {to_email}, URL: {self.base_url}")

        try:
            async with httpx.AsyncClient() as client:
                async for attempt in retry_external_api("Mailgun"):
                    with attempt:
                        # Mailgun requires multipart/form-data format
                        files = {key: (None, value) for key, value in data.items()}
                        response = await client.post(
                            self.base_url,
                            auth=("api", self.api_key),
                            files=files,
                            timeout=10.0,
                        )
                        response.raise_for_status()
                        return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to send email via Mailgun: {str(e)}")
            logger.error(f"Request details - URL: {self.base_url}, From: {data.get('from')}, API Key prefix: {self.api_key[:10]}...")
            logger.error(f"Response status: {e.response.status_code if hasattr(e, 'response') else 'N/A'}")
            logger.error(f"Response body: {e.response.text if hasattr(e, 'response') else 'N/A'}")
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
        html = self._render_template(
            template,
            user_name=user.name,
            app_url=settings.WEB_APP_URL or "https://vibemonitor.ai",
            api_base_url=settings.API_BASE_URL,
        )

        try:
            # Send email via Mailgun (auto-generates plain text from HTML)
            response = await self.send_email(
                to_email=user.email,
                subject=subject,
                text="",
                html=html,
            )

            # Store email record in database
            email_record = MailgunEmail(
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
            email_record = MailgunEmail(
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
        html = self._render_template(
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
                html=html,
            )

            # Store email record
            email_record = MailgunEmail(
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
            email_record = MailgunEmail(
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
        html = self._render_template(
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
                html=html,
            )

            # Store email record
            email_record = MailgunEmail(
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
            email_record = MailgunEmail(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=subject,
                status="failed",
            )
            db.add(email_record)
            await db.commit()

            raise

    async def send_slack_integration_email(self, user_id: str, db: AsyncSession) -> dict:
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
        html = self._render_template(
            template,
            user_name=user.name,
            app_url=settings.WEB_APP_URL or "https://vibemonitor.ai",
            api_base_url=settings.API_BASE_URL,
        )

        try:
            # Send email via Mailgun (auto-generates plain text from HTML)
            response = await self.send_email(
                to_email=user.email,
                subject=subject,
                text="",  # Mailgun auto-generates from HTML
                html=html,
            )

            # Store email record in database
            email_record = MailgunEmail(
                id=str(uuid.uuid4()),
                user_id=user_id,
                sent_at=datetime.now(timezone.utc),
                subject=subject,
                message_id=response.get("id"),
                status="sent",
            )
            db.add(email_record)
            await db.commit()

            logger.info(f"Slack integration email sent to user {user_id} ({user.email})")

            return {
                "success": True,
                "message": "Slack integration email sent successfully",
                "email": user.email,
                "message_id": response.get("id"),
            }

        except Exception as e:
            logger.error(f"Failed to send slack integration email to user {user_id}: {str(e)}")

            # Store failed email record
            email_record = MailgunEmail(
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
        html = self._render_template(
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
            # Send email via Mailgun from verified domain
            response = await self.send_email(
                to_email=support_email,
                subject=subject,
                text=text,
                html=html,
            )

            logger.info(f"Contact form email sent from {work_email} to {support_email}")

            return {
                "success": True,
                "message": "Contact form submitted successfully",
                "email": support_email,
                "message_id": response.get("id"),
            }

        except Exception as e:
            logger.error(f"Failed to send contact form email from {work_email}: {str(e)}")
            raise


# Singleton instance
mailgun_service = MailgunService()
