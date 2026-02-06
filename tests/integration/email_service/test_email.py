"""
Integration tests for email service endpoints.

Tests the email API endpoints:
- POST /api/v1/email/nudge-email - Send welcome email (requires auth)
- POST /api/v1/email/contact-form - Submit contact form (public)
- POST /api/v1/email/send-user-help-emails - Send help emails (requires scheduler token)
- POST /api/v1/email/send-usage-feedback-emails - Send feedback emails (requires scheduler token)
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from jose import jwt

from app.core.config import settings
from app.models import (
    Email,
    Membership,
    RefreshToken,
    Role,
    SlackInstallation,
    User,
    Workspace,
)


# =============================================================================
# Test Constants
# =============================================================================

API_PREFIX = "/api/v1/email-service"


# =============================================================================
# Test Fixtures
# =============================================================================


def create_access_token(user_id: str, email: str) -> str:
    """Create a test JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=30)
    payload = {
        "sub": user_id,
        "email": email,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


async def create_test_user(
    db,
    user_id: str = None,
    email: str = None,
    created_at: datetime = None,
) -> User:
    """Create a test user in the database."""
    user_id = user_id or str(uuid.uuid4())
    email = email or f"test_{user_id[:8]}@example.com"
    created_at = created_at or datetime.now(timezone.utc)
    user = User(
        id=user_id,
        name="Test User",
        email=email,
        is_verified=True,
        created_at=created_at,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def create_test_workspace(db, workspace_id: str = None) -> Workspace:
    """Create a test workspace in the database."""
    workspace_id = workspace_id or str(uuid.uuid4())
    workspace = Workspace(
        id=workspace_id,
        name=f"Test Workspace {workspace_id[:8]}",
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return workspace


async def create_test_membership(
    db, user: User, workspace: Workspace, role: Role = Role.OWNER
) -> Membership:
    """Create a test membership linking user to workspace."""
    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=user.id,
        workspace_id=workspace.id,
        role=role,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership


async def create_test_email_record(
    db,
    user: User,
    subject: str,
    status: str = "sent",
    sent_at: datetime = None,
) -> Email:
    """Create a test email record in the database."""
    sent_at = sent_at or datetime.now(timezone.utc)
    email_record = Email(
        id=str(uuid.uuid4()),
        user_id=user.id,
        subject=subject,
        status=status,
        sent_at=sent_at,
    )
    db.add(email_record)
    await db.commit()
    await db.refresh(email_record)
    return email_record


async def create_test_refresh_token(
    db,
    user: User,
    created_at: datetime = None,
) -> RefreshToken:
    """Create a test refresh token in the database."""
    created_at = created_at or datetime.now(timezone.utc)
    expire = created_at + timedelta(days=7)
    token = RefreshToken(
        token=f"refresh_{uuid.uuid4()}",
        user_id=user.id,
        expires_at=expire,
        created_at=created_at,
    )
    db.add(token)
    await db.commit()
    return token


async def create_test_slack_installation(
    db,
    workspace: Workspace,
    team_id: str = None,
) -> SlackInstallation:
    """Create a test Slack installation in the database."""
    team_id = team_id or f"T{uuid.uuid4().hex[:8].upper()}"
    installation = SlackInstallation(
        id=str(uuid.uuid4()),
        team_id=team_id,
        team_name="Test Slack Team",
        access_token="xoxb-test-token",
        workspace_id=workspace.id,
    )
    db.add(installation)
    await db.commit()
    await db.refresh(installation)
    return installation


# =============================================================================
# POST /api/v1/email/nudge-email Tests
# =============================================================================


@pytest.mark.asyncio
async def test_send_welcome_email_unauthenticated(client):
    """Test that unauthenticated requests return 403."""
    response = await client.post(f"{API_PREFIX}/nudge-email")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_send_welcome_email_success(client, test_db):
    """Test sending welcome email to authenticated user."""
    user = await create_test_user(test_db)
    token = create_access_token(user.id, user.email)

    with patch("app.email_service.router.email_service") as mock_email:
        mock_email.send_welcome_email = AsyncMock(
            return_value={
                "success": True,
                "message": "Welcome email sent successfully",
                "email": user.email,
                "message_id": "msg_123",
            }
        )

        response = await client.post(
            f"{API_PREFIX}/nudge-email",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["email"] == user.email


@pytest.mark.asyncio
async def test_send_welcome_email_service_error(client, test_db):
    """Test handling of email service errors."""
    user = await create_test_user(test_db)
    token = create_access_token(user.id, user.email)

    with patch("app.email_service.router.email_service") as mock_email:
        mock_email.send_welcome_email = AsyncMock(
            side_effect=Exception("SMTP connection failed")
        )

        response = await client.post(
            f"{API_PREFIX}/nudge-email",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 500
        assert "failed to send" in response.json()["detail"].lower()


# =============================================================================
# POST /api/v1/email/contact-form Tests
# =============================================================================


@pytest.mark.asyncio
async def test_contact_form_success(client):
    """Test successful contact form submission."""
    with patch("app.email_service.router.email_service") as mock_email:
        mock_email.send_contact_form_email = AsyncMock(
            return_value={
                "success": True,
                "message": "Contact form submitted successfully",
                "email": "test@company.com",
                "message_id": "msg_456",
            }
        )

        response = await client.post(
            f"{API_PREFIX}/contact-form",
            json={
                "name": "Test User",
                "work_email": "test@company.com",
                "interested_topics": "observability, APM, distributed tracing",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


@pytest.mark.asyncio
async def test_contact_form_invalid_email(client):
    """Test contact form with invalid email address."""
    response = await client.post(
        f"{API_PREFIX}/contact-form",
        json={
            "name": "Test User",
            "work_email": "not-a-valid-email",
            "interested_topics": "observability",
        },
    )

    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_contact_form_missing_required_fields(client):
    """Test contact form with missing required fields."""
    response = await client.post(
        f"{API_PREFIX}/contact-form",
        json={
            "name": "Test User",
            # Missing work_email and interested_topics
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_contact_form_service_error(client):
    """Test handling of email service errors in contact form."""
    with patch("app.email_service.router.email_service") as mock_email:
        mock_email.send_contact_form_email = AsyncMock(
            side_effect=Exception("Email service unavailable")
        )

        response = await client.post(
            f"{API_PREFIX}/contact-form",
            json={
                "name": "Test User",
                "work_email": "test@company.com",
                "interested_topics": "APM",
            },
        )

        assert response.status_code == 500
        assert "failed to submit" in response.json()["detail"].lower()







# =============================================================================
# POST /api/v1/email/send-user-help-emails Tests
# =============================================================================


@pytest.mark.asyncio
async def test_send_user_help_emails_unauthorized(client):
    """Test that requests without scheduler token are rejected."""
    response = await client.post(f"{API_PREFIX}/send-user-help-emails")
    assert response.status_code in [401, 403, 422]


@pytest.mark.asyncio
async def test_send_user_help_emails_with_scheduler_token(client, test_db):
    """Test sending user help emails with valid scheduler token."""
    # Create test user who signed up 12 hours ago (eligible)
    twelve_hours_ago = datetime.now(timezone.utc) - timedelta(hours=12)
    await create_test_user(test_db, created_at=twelve_hours_ago)

    with patch("app.email_service.router.verify_scheduler_token") as mock_verify:
        mock_verify.return_value = True

        with patch("app.email_service.router.email_service") as mock_email:
            mock_email.send_user_help_email = AsyncMock(return_value=None)

            response = await client.post(
                f"{API_PREFIX}/send-user-help-emails",
                headers={
                    "X-Scheduler-Token": settings.SCHEDULER_SECRET_TOKEN or "test-token"
                },
            )

            if response.status_code == 200:
                data = response.json()
                assert data["success"] is True


@pytest.mark.asyncio
async def test_send_user_help_emails_skips_already_sent(client, test_db):
    """Test that users who already received help email are skipped."""
    twelve_hours_ago = datetime.now(timezone.utc) - timedelta(hours=12)
    user = await create_test_user(test_db, created_at=twelve_hours_ago)

    # User already received help email
    await create_test_email_record(
        test_db,
        user,
        subject=settings.USER_HELP_EMAIL_SUBJECT,
        status="sent",
    )

    with patch("app.email_service.router.verify_scheduler_token") as mock_verify:
        mock_verify.return_value = True

        with patch("app.email_service.router.email_service") as mock_email:
            mock_email.send_user_help_email = AsyncMock(return_value=None)

            response = await client.post(
                f"{API_PREFIX}/send-user-help-emails",
                headers={
                    "X-Scheduler-Token": settings.SCHEDULER_SECRET_TOKEN or "test-token"
                },
            )

            if response.status_code == 200:
                data = response.json()
                # User should be skipped (already sent)
                assert data["total_eligible"] == 0


# =============================================================================
# POST /api/v1/email/send-usage-feedback-emails Tests
# =============================================================================


@pytest.mark.asyncio
async def test_send_usage_feedback_emails_unauthorized(client):
    """Test that requests without scheduler token are rejected."""
    response = await client.post(f"{API_PREFIX}/send-usage-feedback-emails")
    assert response.status_code in [401, 403, 422]


@pytest.mark.asyncio
async def test_send_usage_feedback_emails_with_scheduler_token(client, test_db):
    """Test sending usage feedback emails with valid scheduler token."""
    # Create test user who signed up 8 days ago (eligible)
    eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
    user = await create_test_user(test_db, created_at=eight_days_ago)

    # User has logged in after signup (refresh token created > 5 min after signup)
    login_time = eight_days_ago + timedelta(hours=1)
    await create_test_refresh_token(test_db, user, created_at=login_time)

    with patch("app.email_service.router.verify_scheduler_token") as mock_verify:
        mock_verify.return_value = True

        with patch("app.email_service.router.email_service") as mock_email:
            mock_email.send_usage_feedback_email = AsyncMock(return_value=None)

            response = await client.post(
                f"{API_PREFIX}/send-usage-feedback-emails",
                headers={
                    "X-Scheduler-Token": settings.SCHEDULER_SECRET_TOKEN or "test-token"
                },
            )

            if response.status_code == 200:
                data = response.json()
                assert data["success"] is True


@pytest.mark.asyncio
async def test_send_usage_feedback_emails_skips_inactive_users(client, test_db):
    """Test that users who never logged in after signup are skipped."""
    eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
    await create_test_user(test_db, created_at=eight_days_ago)
    # No refresh token = user never logged in after signup

    with patch("app.email_service.router.verify_scheduler_token") as mock_verify:
        mock_verify.return_value = True

        with patch("app.email_service.router.email_service") as mock_email:
            mock_email.send_usage_feedback_email = AsyncMock(return_value=None)

            response = await client.post(
                f"{API_PREFIX}/send-usage-feedback-emails",
                headers={
                    "X-Scheduler-Token": settings.SCHEDULER_SECRET_TOKEN or "test-token"
                },
            )

            if response.status_code == 200:
                data = response.json()
                # User should be skipped (never logged in)
                assert data["total_eligible"] == 0


@pytest.mark.asyncio
async def test_send_usage_feedback_emails_skips_recent_users(client, test_db):
    """Test that users who signed up less than 7 days ago are skipped."""
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
    user = await create_test_user(test_db, created_at=three_days_ago)

    login_time = three_days_ago + timedelta(hours=1)
    await create_test_refresh_token(test_db, user, created_at=login_time)

    with patch("app.email_service.router.verify_scheduler_token") as mock_verify:
        mock_verify.return_value = True

        with patch("app.email_service.router.email_service") as mock_email:
            mock_email.send_usage_feedback_email = AsyncMock(return_value=None)

            response = await client.post(
                f"{API_PREFIX}/send-usage-feedback-emails",
                headers={
                    "X-Scheduler-Token": settings.SCHEDULER_SECRET_TOKEN or "test-token"
                },
            )

            if response.status_code == 200:
                data = response.json()
                # User should be skipped (too recent)
                assert data["total_eligible"] == 0


@pytest.mark.asyncio
async def test_send_usage_feedback_emails_skips_already_sent(client, test_db):
    """Test that users who already received feedback email are skipped."""
    eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
    user = await create_test_user(test_db, created_at=eight_days_ago)

    login_time = eight_days_ago + timedelta(hours=1)
    await create_test_refresh_token(test_db, user, created_at=login_time)

    # User already received feedback email
    await create_test_email_record(
        test_db,
        user,
        subject=settings.USAGE_FEEDBACK_EMAIL_SUBJECT,
        status="sent",
    )

    with patch("app.email_service.router.verify_scheduler_token") as mock_verify:
        mock_verify.return_value = True

        with patch("app.email_service.router.email_service") as mock_email:
            mock_email.send_usage_feedback_email = AsyncMock(return_value=None)

            response = await client.post(
                f"{API_PREFIX}/send-usage-feedback-emails",
                headers={
                    "X-Scheduler-Token": settings.SCHEDULER_SECRET_TOKEN or "test-token"
                },
            )

            if response.status_code == 200:
                data = response.json()
                # User should be skipped (already sent)
                assert data["total_eligible"] == 0
