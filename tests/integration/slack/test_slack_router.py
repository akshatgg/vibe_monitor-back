"""
Integration tests for Slack API endpoints.

Tests the slack router endpoints:
- GET /api/v1/workspaces/{workspace_id}/slack/install
- GET /api/v1/workspaces/{workspace_id}/slack/status
- DELETE /api/v1/workspaces/{workspace_id}/slack/disconnect

Note: Webhook endpoints (/slack/events, /slack/interactivity, /slack/oauth/callback)
are tested separately as they don't require user authentication.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.slack import router as slack_router
from app.models import (
    Integration,
    Membership,
    Role,
    SlackInstallation,
    User,
    Workspace,
    WorkspaceType,
)
from tests.integration.conftest import API_PREFIX


@pytest.fixture
def mock_user():
    """Create a mock user for testing."""
    return User(
        id=str(uuid.uuid4()),
        name="Test User",
        email="test@example.com",
        is_verified=True,
    )


@pytest_asyncio.fixture
async def test_workspace(test_db, mock_user):
    """Create a test workspace with membership."""
    # Add user to database
    test_db.add(mock_user)
    await test_db.commit()

    # Create team workspace (allows Slack integration)
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Test Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(workspace)
    await test_db.commit()

    # Create membership
    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=mock_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(membership)
    await test_db.commit()

    return workspace


@pytest_asyncio.fixture
async def personal_workspace(test_db, mock_user):
    """Create a personal workspace (Slack not allowed)."""
    from sqlalchemy import select

    # Ensure user is in database
    result = await test_db.execute(select(User).where(User.id == mock_user.id))
    if not result.scalar_one_or_none():
        test_db.add(mock_user)
        await test_db.commit()

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Personal Workspace",
        type=WorkspaceType.PERSONAL,
    )
    test_db.add(workspace)
    await test_db.commit()

    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=mock_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(membership)
    await test_db.commit()

    return workspace


@pytest.fixture
def auth_override(mock_user):
    """Override auth dependency to return mock user."""

    async def override_get_current_user():
        return mock_user

    return override_get_current_user


class TestSlackInstall:
    """Tests for GET /workspaces/{workspace_id}/slack/install"""

    @pytest.mark.asyncio
    async def test_initiate_slack_install_success(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test successful Slack OAuth URL generation."""
        from app.main import app

        app.dependency_overrides[slack_router.auth_service.get_current_user] = (
            auth_override
        )

        # Mock settings to provide Slack OAuth config
        with patch("app.slack.router.settings") as mock_settings:
            mock_settings.SLACK_OAUTH_AUTHORIZE_URL = (
                "https://slack.com/oauth/v2/authorize"
            )
            mock_settings.SLACK_CLIENT_ID = "test-client-id"

            response = await client.get(
                f"{API_PREFIX}/workspaces/{test_workspace.id}/slack/install"
            )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert "oauth_url" in data
        assert "slack.com/oauth" in data["oauth_url"]
        assert f"state={mock_user.id}|{test_workspace.id}" in data["oauth_url"]

    @pytest.mark.asyncio
    async def test_initiate_slack_install_workspace_not_found(
        self, client, test_db, mock_user, auth_override
    ):
        """Test Slack install with non-existent workspace."""
        from app.main import app

        # Add mock_user to database
        test_db.add(mock_user)
        await test_db.commit()

        app.dependency_overrides[slack_router.auth_service.get_current_user] = (
            auth_override
        )

        fake_workspace_id = str(uuid.uuid4())
        response = await client.get(
            f"{API_PREFIX}/workspaces/{fake_workspace_id}/slack/install"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 404
        assert "Workspace not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_initiate_slack_install_personal_workspace_blocked(
        self, client, test_db, personal_workspace, mock_user, auth_override
    ):
        """Test that Slack install is blocked for personal workspaces."""
        from app.main import app

        app.dependency_overrides[slack_router.auth_service.get_current_user] = (
            auth_override
        )

        response = await client.get(
            f"{API_PREFIX}/workspaces/{personal_workspace.id}/slack/install"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "not available for personal workspaces" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_initiate_slack_install_unauthenticated(
        self, client, test_db, test_workspace
    ):
        """Test Slack install without authentication."""
        response = await client.get(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/slack/install"
        )

        assert response.status_code == 403


class TestSlackStatus:
    """Tests for GET /workspaces/{workspace_id}/slack/status"""

    @pytest.mark.asyncio
    async def test_get_status_connected(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test getting status when Slack is connected."""
        from app.main import app

        # Create existing Slack installation
        integration = Integration(
            id=str(uuid.uuid4()),
            workspace_id=test_workspace.id,
            provider="slack",
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db.add(integration)
        await test_db.commit()

        slack_installation = SlackInstallation(
            id=str(uuid.uuid4()),
            team_id="T12345678",
            team_name="Test Slack Workspace",
            access_token="xoxb-test-token",
            bot_user_id="U12345678",
            scope="app_mentions:read,chat:write",
            workspace_id=test_workspace.id,
            integration_id=integration.id,
            installed_at=datetime.now(timezone.utc),
        )
        test_db.add(slack_installation)
        await test_db.commit()

        app.dependency_overrides[slack_router.auth_service.get_current_user] = (
            auth_override
        )

        response = await client.get(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/slack/status"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert data["data"]["team_id"] == "T12345678"
        assert data["data"]["team_name"] == "Test Slack Workspace"
        assert data["data"]["workspace_id"] == test_workspace.id

    @pytest.mark.asyncio
    async def test_get_status_not_connected(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test getting status when Slack is not connected."""
        from app.main import app

        app.dependency_overrides[slack_router.auth_service.get_current_user] = (
            auth_override
        )

        response = await client.get(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/slack/status"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is False
        assert data["message"] == "Slack workspace not connected"

    @pytest.mark.asyncio
    async def test_get_status_no_membership(
        self, client, test_db, test_workspace, auth_override
    ):
        """Test getting status when user has no membership to workspace."""
        from app.main import app

        # Create a different user without membership
        other_user = User(
            id=str(uuid.uuid4()),
            name="Other User",
            email="other@example.com",
            is_verified=True,
        )
        test_db.add(other_user)
        await test_db.commit()

        async def override_get_current_user():
            return other_user

        app.dependency_overrides[slack_router.auth_service.get_current_user] = (
            override_get_current_user
        )

        response = await client.get(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/slack/status"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 403
        assert "does not have access" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_status_unauthenticated(self, client, test_db, test_workspace):
        """Test getting status without authentication."""
        response = await client.get(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/slack/status"
        )

        assert response.status_code == 403


class TestSlackDisconnect:
    """Tests for DELETE /workspaces/{workspace_id}/slack/disconnect"""

    @pytest.mark.asyncio
    async def test_disconnect_slack_success(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test successful Slack disconnection."""
        from app.main import app

        # Create existing Slack installation
        integration = Integration(
            id=str(uuid.uuid4()),
            workspace_id=test_workspace.id,
            provider="slack",
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db.add(integration)
        await test_db.commit()

        slack_installation = SlackInstallation(
            id=str(uuid.uuid4()),
            team_id="T12345678",
            team_name="Test Slack Workspace",
            access_token="xoxb-test-token",
            bot_user_id="U12345678",
            scope="app_mentions:read,chat:write",
            workspace_id=test_workspace.id,
            integration_id=integration.id,
            installed_at=datetime.now(timezone.utc),
        )
        test_db.add(slack_installation)
        await test_db.commit()

        app.dependency_overrides[slack_router.auth_service.get_current_user] = (
            auth_override
        )

        response = await client.delete(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/slack/disconnect"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "disconnected successfully" in data["message"]
        assert data["data"]["workspace_id"] == test_workspace.id
        assert data["data"]["disconnected_team_id"] == "T12345678"

    @pytest.mark.asyncio
    async def test_disconnect_slack_not_found(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test disconnecting when no Slack integration exists."""
        from app.main import app

        app.dependency_overrides[slack_router.auth_service.get_current_user] = (
            auth_override
        )

        response = await client.delete(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/slack/disconnect"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 404
        assert "No Slack integration found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_disconnect_slack_no_membership(
        self, client, test_db, test_workspace, auth_override
    ):
        """Test disconnecting when user has no membership to workspace."""
        from app.main import app

        # Create a different user without membership
        other_user = User(
            id=str(uuid.uuid4()),
            name="Other User",
            email="other@example.com",
            is_verified=True,
        )
        test_db.add(other_user)
        await test_db.commit()

        async def override_get_current_user():
            return other_user

        app.dependency_overrides[slack_router.auth_service.get_current_user] = (
            override_get_current_user
        )

        response = await client.delete(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/slack/disconnect"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 403
        assert "does not have access" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_disconnect_slack_unauthenticated(
        self, client, test_db, test_workspace
    ):
        """Test disconnecting without authentication."""
        response = await client.delete(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/slack/disconnect"
        )

        assert response.status_code == 403


class TestSlackWebhooks:
    """Tests for Slack webhook endpoints (no auth required, called by Slack)."""

    @pytest.mark.asyncio
    async def test_slack_url_verification(self, client, test_db):
        """Test Slack URL verification challenge."""
        with patch(
            "app.slack.router.slack_event_service.verify_slack_request",
            new_callable=AsyncMock,
        ) as mock_verify:
            mock_verify.return_value = True

            response = await client.post(
                f"{API_PREFIX}/slack/events",
                json={
                    "type": "url_verification",
                    "challenge": "test-challenge-12345",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["challenge"] == "test-challenge-12345"

    @pytest.mark.asyncio
    async def test_slack_events_invalid_signature(self, client, test_db):
        """Test Slack events endpoint with invalid signature."""
        with patch(
            "app.slack.router.slack_event_service.verify_slack_request",
            new_callable=AsyncMock,
        ) as mock_verify:
            mock_verify.return_value = False

            response = await client.post(
                f"{API_PREFIX}/slack/events",
                json={
                    "type": "event_callback",
                    "token": "fake-token",
                    "team_id": "T12345",
                    "api_app_id": "A12345",
                    "event": {
                        "type": "app_mention",
                        "ts": "123456.789",
                        "channel": "C12345",
                        "text": "Hello",
                        "user": "U12345",
                    },
                    "event_id": "Ev12345",
                    "event_time": 1234567890,
                },
                headers={
                    "X-Slack-Signature": "invalid",
                    "X-Slack-Request-Timestamp": "1234567890",
                },
            )

        assert response.status_code == 403
        assert "Invalid request signature" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_slack_oauth_callback_missing_code(self, client, test_db):
        """Test OAuth callback with missing authorization code."""
        response = await client.get(f"{API_PREFIX}/slack/oauth/callback")

        assert response.status_code == 400
        assert "Missing authorization code" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_slack_oauth_callback_error_from_slack(self, client, test_db):
        """Test OAuth callback when Slack returns an error."""
        response = await client.get(
            f"{API_PREFIX}/slack/oauth/callback",
            params={"error": "access_denied"},
        )

        assert response.status_code == 400
        assert "Installation was cancelled" in response.json()["message"]
