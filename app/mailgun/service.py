"""
Mailgun service for sending emails.
"""
import uuid
import logging
import httpx
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException, status, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
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

    async def send_email(
        self,
        to_email: str,
        subject: str,
        text: str,
        html: str = None,
    ) -> dict:
        """
        Send an email using Mailgun API.

        Args:
            to_email: Recipient email address
            subject: Email subject
            text: Plain text content
            html: HTML content (optional)

        Returns:
            dict: Response from Mailgun API
        """
        if not self.api_key or not self.domain:
            raise ValueError("Mailgun API key and domain must be configured")

        data = {
            "from": f"VibeMonitor <noreply@{self.domain}>",
            "to": to_email,
            "subject": subject,
            "text": text,
        }

        if html:
            data["html"] = html

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    auth=("api", self.api_key),
                    data=data,
                    timeout=10.0,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to send email via Mailgun: {str(e)}")
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

        Args:
            template: Template string
            **kwargs: Variables to replace in the template

        Returns:
            str: Rendered template
        """
        rendered = template
        for key, value in kwargs.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
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


# Singleton instance
mailgun_service = MailgunService()
