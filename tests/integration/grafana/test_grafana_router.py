"""
Integration tests for Grafana API endpoints.

Tests the grafana router endpoints:
- POST /api/v1/workspaces/{workspace_id}/grafana/connect
- GET /api/v1/workspaces/{workspace_id}/grafana/status
- DELETE /api/v1/workspaces/{workspace_id}/grafana/disconnect
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.grafana import router as grafana_router
from app.grafana.service import GrafanaService
from app.models import (
    GrafanaIntegration,
    Integration,
    Membership,
    Role,
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

    # Create team workspace (allows Grafana integration)
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
    """Create a personal workspace (Grafana not allowed)."""
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


class TestGrafanaConnect:
    """Tests for POST /workspaces/{workspace_id}/grafana/connect"""

    @pytest.mark.asyncio
    async def test_connect_grafana_success(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test successful Grafana connection."""
        from app.main import app

        app.dependency_overrides[grafana_router.auth_service.get_current_user] = (
            auth_override
        )

        with patch.object(
            GrafanaService, "validate_credentials", new_callable=AsyncMock
        ) as mock_validate:
            mock_validate.return_value = True

            # Mock the health check to avoid external calls
            with patch(
                "app.grafana.service.check_grafana_health", new_callable=AsyncMock
            ) as mock_health:
                mock_health.return_value = ("healthy", None)

                response = await client.post(
                    f"{API_PREFIX}/workspaces/{test_workspace.id}/grafana/connect",
                    json={
                        "grafana_url": "https://grafana.example.com",
                        "api_token": "test-token-123",
                    },
                )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert data["workspace_id"] == test_workspace.id
        assert data["grafana_url"] == "https://grafana.example.com"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_connect_grafana_invalid_credentials(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test Grafana connection with invalid credentials."""
        from app.main import app

        app.dependency_overrides[grafana_router.auth_service.get_current_user] = (
            auth_override
        )

        with patch.object(
            GrafanaService, "validate_credentials", new_callable=AsyncMock
        ) as mock_validate:
            mock_validate.return_value = False

            response = await client.post(
                f"{API_PREFIX}/workspaces/{test_workspace.id}/grafana/connect",
                json={
                    "grafana_url": "https://grafana.example.com",
                    "api_token": "invalid-token",
                },
            )

        app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "Invalid Grafana credentials" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_connect_grafana_personal_workspace_blocked(
        self, client, test_db, personal_workspace, mock_user, auth_override
    ):
        """Test that Grafana connection is blocked for personal workspaces."""
        from app.main import app

        app.dependency_overrides[grafana_router.auth_service.get_current_user] = (
            auth_override
        )

        response = await client.post(
            f"{API_PREFIX}/workspaces/{personal_workspace.id}/grafana/connect",
            json={
                "grafana_url": "https://grafana.example.com",
                "api_token": "test-token",
            },
        )

        app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "not available for personal workspaces" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_connect_grafana_workspace_not_found(
        self, client, test_db, mock_user, auth_override
    ):
        """Test Grafana connection with non-existent workspace."""
        from app.main import app

        # Add mock_user to database since auth requires it
        test_db.add(mock_user)
        await test_db.commit()

        app.dependency_overrides[grafana_router.auth_service.get_current_user] = (
            auth_override
        )

        fake_workspace_id = str(uuid.uuid4())
        response = await client.post(
            f"{API_PREFIX}/workspaces/{fake_workspace_id}/grafana/connect",
            json={
                "grafana_url": "https://grafana.example.com",
                "api_token": "test-token",
            },
        )

        app.dependency_overrides.clear()

        assert response.status_code == 404
        assert "Workspace not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_connect_grafana_already_exists(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test Grafana connection when integration already exists."""
        from app.main import app

        # Create existing integration
        integration = Integration(
            id=str(uuid.uuid4()),
            workspace_id=test_workspace.id,
            provider="grafana",
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db.add(integration)
        await test_db.commit()

        grafana_integration = GrafanaIntegration(
            id=str(uuid.uuid4()),
            vm_workspace_id=test_workspace.id,
            integration_id=integration.id,
            grafana_url="https://existing.grafana.com",
            api_token="encrypted-token",
        )
        test_db.add(grafana_integration)
        await test_db.commit()

        app.dependency_overrides[grafana_router.auth_service.get_current_user] = (
            auth_override
        )

        with patch.object(
            GrafanaService, "validate_credentials", new_callable=AsyncMock
        ) as mock_validate:
            mock_validate.return_value = True

            response = await client.post(
                f"{API_PREFIX}/workspaces/{test_workspace.id}/grafana/connect",
                json={
                    "grafana_url": "https://new.grafana.com",
                    "api_token": "new-token",
                },
            )

        app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_connect_grafana_unauthenticated(
        self, client, test_db, test_workspace
    ):
        """Test Grafana connection without authentication."""
        response = await client.post(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/grafana/connect",
            json={
                "grafana_url": "https://grafana.example.com",
                "api_token": "test-token",
            },
        )

        assert response.status_code == 403


class TestGrafanaStatus:
    """Tests for GET /workspaces/{workspace_id}/grafana/status"""

    @pytest.mark.asyncio
    async def test_get_status_connected(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test getting status when Grafana is connected."""
        from app.main import app

        # Create existing Grafana integration
        integration = Integration(
            id=str(uuid.uuid4()),
            workspace_id=test_workspace.id,
            provider="grafana",
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db.add(integration)
        await test_db.commit()

        grafana_integration = GrafanaIntegration(
            id=str(uuid.uuid4()),
            vm_workspace_id=test_workspace.id,
            integration_id=integration.id,
            grafana_url="https://grafana.example.com",
            api_token="encrypted-token",
        )
        test_db.add(grafana_integration)
        await test_db.commit()

        app.dependency_overrides[grafana_router.auth_service.get_current_user] = (
            auth_override
        )

        response = await client.get(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/grafana/status"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert data["integration"]["grafana_url"] == "https://grafana.example.com"
        assert data["integration"]["workspace_id"] == test_workspace.id

    @pytest.mark.asyncio
    async def test_get_status_not_connected(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test getting status when Grafana is not connected."""
        from app.main import app

        app.dependency_overrides[grafana_router.auth_service.get_current_user] = (
            auth_override
        )

        response = await client.get(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/grafana/status"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is False
        assert data["integration"] is None

    @pytest.mark.asyncio
    async def test_get_status_unauthenticated(self, client, test_db, test_workspace):
        """Test getting status without authentication."""
        response = await client.get(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/grafana/status"
        )

        assert response.status_code == 403


class TestGrafanaDisconnect:
    """Tests for DELETE /workspaces/{workspace_id}/grafana/disconnect"""

    @pytest.mark.asyncio
    async def test_disconnect_grafana_success(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test successful Grafana disconnection."""
        from app.main import app

        # Create existing Grafana integration
        integration = Integration(
            id=str(uuid.uuid4()),
            workspace_id=test_workspace.id,
            provider="grafana",
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db.add(integration)
        await test_db.commit()

        grafana_integration = GrafanaIntegration(
            id=str(uuid.uuid4()),
            vm_workspace_id=test_workspace.id,
            integration_id=integration.id,
            grafana_url="https://grafana.example.com",
            api_token="encrypted-token",
        )
        test_db.add(grafana_integration)
        await test_db.commit()

        app.dependency_overrides[grafana_router.auth_service.get_current_user] = (
            auth_override
        )

        response = await client.delete(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/grafana/disconnect"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Grafana integration disconnected successfully"
        assert data["workspace_id"] == test_workspace.id

    @pytest.mark.asyncio
    async def test_disconnect_grafana_not_found(
        self, client, test_db, test_workspace, mock_user, auth_override
    ):
        """Test disconnecting when no integration exists."""
        from app.main import app

        app.dependency_overrides[grafana_router.auth_service.get_current_user] = (
            auth_override
        )

        response = await client.delete(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/grafana/disconnect"
        )

        app.dependency_overrides.clear()

        assert response.status_code == 404
        assert "No Grafana integration found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_disconnect_grafana_unauthenticated(
        self, client, test_db, test_workspace
    ):
        """Test disconnecting without authentication."""
        response = await client.delete(
            f"{API_PREFIX}/workspaces/{test_workspace.id}/grafana/disconnect"
        )

        assert response.status_code == 403
