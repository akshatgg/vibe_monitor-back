"""
Integration tests for GitHub OAuth router endpoints.

Tests for:
- GET /api/v1/github/status - Check GitHub integration status
- GET /api/v1/github/repositories - List repositories
- GET /api/v1/github/install - Get GitHub App install URL
- DELETE /api/v1/github/disconnect - Disconnect GitHub App
- GET /api/v1/github/callback - GitHub OAuth callback
- GET /api/v1/github/repositories/{repo_full_name}/branches - Get repository branches

IMPORTANT: All tests use async fixtures and AsyncClient from conftest.py
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.auth.google.service import AuthService
from app.models import (
    GitHubIntegration,
    Integration,
    Membership,
    Role,
    User,
    Workspace,
    WorkspaceType,
)
from tests.integration.conftest import API_PREFIX

# Initialize auth service for creating test tokens
auth_service = AuthService()


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def test_user(test_db):
    """Create a test user"""
    user = User(
        id=str(uuid.uuid4()),
        name="Test User",
        email="testuser@example.com",
        password_hash="hashed_password",
        is_verified=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_workspace(test_db):
    """Create a test workspace"""
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Test Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(workspace)
    await test_db.commit()
    await test_db.refresh(workspace)
    return workspace


@pytest_asyncio.fixture
async def test_membership(test_db, test_user, test_workspace):
    """Create a membership linking user to workspace"""
    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        role=Role.OWNER,
    )
    test_db.add(membership)
    await test_db.commit()
    await test_db.refresh(membership)
    return membership


@pytest_asyncio.fixture
async def test_integration(test_db, test_workspace):
    """Create a test integration control plane record"""
    integration = Integration(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        provider="github",
        status="active",
    )
    test_db.add(integration)
    await test_db.commit()
    await test_db.refresh(integration)
    return integration


@pytest_asyncio.fixture
async def test_github_integration(test_db, test_workspace, test_integration):
    """Create a test GitHub integration"""
    github_integration = GitHubIntegration(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        integration_id=test_integration.id,
        github_user_id="12345",
        github_username="testuser",
        installation_id="67890",
        is_active=True,
        access_token="encrypted_token",
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    test_db.add(github_integration)
    await test_db.commit()
    await test_db.refresh(github_integration)
    return github_integration


@pytest_asyncio.fixture
def auth_headers(test_user):
    """Generate authentication headers with a valid JWT token"""
    token = auth_service.create_access_token(data={"sub": test_user.id})
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# GET /api/v1/github/status Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_github_status_connected(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test getting GitHub status when integration is connected"""
    response = await client.get(
        f"{API_PREFIX}/github/status",
        params={"workspace_id": test_workspace.id},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is True
    assert data["integration"]["github_username"] == "testuser"
    assert data["integration"]["installation_id"] == "67890"
    assert data["integration"]["is_active"] is True


@pytest.mark.asyncio
async def test_get_github_status_not_connected(
    client, test_db, test_user, test_workspace, test_membership, auth_headers
):
    """Test getting GitHub status when no integration exists"""
    response = await client.get(
        f"{API_PREFIX}/github/status",
        params={"workspace_id": test_workspace.id},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert data["integration"] is None


@pytest.mark.asyncio
async def test_get_github_status_unauthorized(client, test_workspace):
    """Test getting GitHub status without authentication"""
    response = await client.get(
        f"{API_PREFIX}/github/status",
        params={"workspace_id": test_workspace.id},
    )

    assert response.status_code == 403  # HTTPBearer returns 403 when no credentials


@pytest.mark.asyncio
async def test_get_github_status_missing_workspace_id(client, auth_headers):
    """Test getting GitHub status without workspace_id parameter"""
    response = await client.get(
        f"{API_PREFIX}/github/status",
        headers=auth_headers,
    )

    assert response.status_code == 422  # Validation error


# =============================================================================
# GET /api/v1/github/install Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_github_install_url(
    client, test_db, test_user, test_workspace, test_membership, auth_headers
):
    """Test getting GitHub App install URL"""
    with (
        patch(
            "app.core.config.settings.GITHUB_APP_INSTALL_URL", "https://github.com/apps"
        ),
        patch("app.core.config.settings.GITHUB_APP_NAME", "test-app"),
    ):
        response = await client.get(
            f"{API_PREFIX}/github/install",
            params={"workspace_id": test_workspace.id},
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert "install_url" in data
    assert "https://github.com/apps/test-app/installations/new" in data["install_url"]
    assert "state=" in data["install_url"]


@pytest.mark.asyncio
async def test_get_github_install_url_unauthorized(client, test_workspace):
    """Test getting GitHub install URL without authentication"""
    response = await client.get(
        f"{API_PREFIX}/github/install",
        params={"workspace_id": test_workspace.id},
    )

    assert response.status_code == 403


# =============================================================================
# DELETE /api/v1/github/disconnect Tests
# =============================================================================


@pytest.mark.asyncio
async def test_disconnect_github_app_success(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test successfully disconnecting GitHub App"""
    with patch(
        "app.github.oauth.router.github_app_service.uninstall_github_app",
        new_callable=AsyncMock,
    ) as mock_uninstall:
        mock_uninstall.return_value = None

        response = await client.delete(
            f"{API_PREFIX}/github/disconnect",
            params={"workspace_id": test_workspace.id},
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert (
        "disconnected" in data["message"].lower()
        or "uninstalled" in data["message"].lower()
    )


@pytest.mark.asyncio
async def test_disconnect_github_app_no_integration(
    client, test_db, test_user, test_workspace, test_membership, auth_headers
):
    """Test disconnecting when no GitHub integration exists"""
    response = await client.delete(
        f"{API_PREFIX}/github/disconnect",
        params={"workspace_id": test_workspace.id},
        headers=auth_headers,
    )

    assert response.status_code == 404
    detail = response.json()["detail"].lower()
    assert "integration" in detail or "not found" in detail


@pytest.mark.asyncio
async def test_disconnect_github_app_unauthorized(client, test_workspace):
    """Test disconnecting GitHub App without authentication"""
    response = await client.delete(
        f"{API_PREFIX}/github/disconnect",
        params={"workspace_id": test_workspace.id},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_disconnect_github_app_no_membership(
    client, test_db, test_workspace, test_github_integration
):
    """Test disconnecting when user is not a member of workspace"""
    # Create a different user not in the workspace
    other_user = User(
        id=str(uuid.uuid4()),
        name="Other User",
        email="other@example.com",
        password_hash="hashed_password",
        is_verified=True,
    )
    test_db.add(other_user)
    await test_db.commit()

    token = auth_service.create_access_token(data={"sub": other_user.id})
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.delete(
        f"{API_PREFIX}/github/disconnect",
        params={"workspace_id": test_workspace.id},
        headers=headers,
    )

    assert response.status_code == 403
    assert "access" in response.json()["detail"].lower()


# =============================================================================
# GET /api/v1/github/callback Tests
# =============================================================================


@pytest.mark.asyncio
async def test_github_callback_with_state(
    client, test_db, test_user, test_workspace, test_membership
):
    """Test GitHub callback with state parameter"""
    # Create state with user_id|workspace_id|token format
    state = f"{test_user.id}|{test_workspace.id}|test_token"

    with (
        patch(
            "app.github.oauth.router.github_app_service.get_installation_info_by_id",
            new_callable=AsyncMock,
        ) as mock_info,
        patch(
            "app.github.oauth.router.github_app_service.create_or_update_app_integration_with_installation",
            new_callable=AsyncMock,
        ) as mock_create,
        patch(
            "app.github.oauth.router.github_app_service.get_installation_access_token",
            new_callable=AsyncMock,
        ) as mock_token,
    ):
        mock_info.return_value = {
            "id": 12345,
            "account": {"login": "testuser", "id": 67890},
        }

        # Create a mock integration object
        mock_integration = AsyncMock()
        mock_integration.id = str(uuid.uuid4())
        mock_integration.github_username = "testuser"
        mock_integration.installation_id = "12345"
        mock_integration.access_token = None
        mock_integration.token_expires_at = None
        mock_create.return_value = mock_integration

        mock_token.return_value = {
            "token": "ghs_test_token",
            "expires_at": "2024-12-31T23:59:59Z",
        }

        response = await client.get(
            f"{API_PREFIX}/github/callback",
            params={
                "installation_id": "12345",
                "setup_action": "install",
                "state": state,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "installed" in data["message"].lower()


@pytest.mark.asyncio
async def test_github_callback_missing_auth(client, test_workspace):
    """Test GitHub callback without state or JWT"""
    response = await client.get(
        f"{API_PREFIX}/github/callback",
        params={
            "installation_id": "12345",
            "setup_action": "install",
        },
    )

    assert response.status_code == 401
    assert "authentication" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_github_callback_missing_workspace(client, test_db, test_user):
    """Test GitHub callback with state that has user_id but missing workspace_id"""
    # State with user_id|workspace_id format but empty workspace_id
    # Note: state with only user_id (no pipe) causes user_id to also not be parsed
    state = f"{test_user.id}||token"  # Empty workspace_id

    response = await client.get(
        f"{API_PREFIX}/github/callback",
        params={
            "installation_id": "12345",
            "setup_action": "install",
            "state": state,
        },
    )

    # Empty workspace_id should return 400
    assert response.status_code == 400
    assert "workspace_id" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_github_callback_workspace_not_found(client, test_user):
    """Test GitHub callback with non-existent workspace"""
    fake_workspace_id = str(uuid.uuid4())
    state = f"{test_user.id}|{fake_workspace_id}|test_token"

    response = await client.get(
        f"{API_PREFIX}/github/callback",
        params={
            "installation_id": "12345",
            "setup_action": "install",
            "state": state,
        },
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_github_callback_user_not_member(client, test_db, test_workspace):
    """Test GitHub callback when user is not a workspace member"""
    # Create a user not in the workspace
    other_user = User(
        id=str(uuid.uuid4()),
        name="Other User",
        email="other@example.com",
        password_hash="hashed_password",
        is_verified=True,
    )
    test_db.add(other_user)
    await test_db.commit()

    state = f"{other_user.id}|{test_workspace.id}|test_token"

    response = await client.get(
        f"{API_PREFIX}/github/callback",
        params={
            "installation_id": "12345",
            "setup_action": "install",
            "state": state,
        },
    )

    assert response.status_code == 403
    assert "access" in response.json()["detail"].lower()


# =============================================================================
# GET /api/v1/github/repositories Tests
# =============================================================================


@pytest.mark.asyncio
async def test_list_github_repositories_success(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test listing GitHub repositories"""
    with patch(
        "app.github.oauth.router.github_app_service.list_repositories",
        new_callable=AsyncMock,
    ) as mock_list:
        mock_list.return_value = {
            "total_count": 2,
            "repositories": [
                {"name": "repo1", "full_name": "testuser/repo1"},
                {"name": "repo2", "full_name": "testuser/repo2"},
            ],
        }

        response = await client.get(
            f"{API_PREFIX}/github/repositories",
            params={"workspace_id": test_workspace.id},
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["total_count"] == 2
    assert len(data["repositories"]) == 2


@pytest.mark.asyncio
async def test_list_github_repositories_unauthorized(client, test_workspace):
    """Test listing repositories without authentication"""
    response = await client.get(
        f"{API_PREFIX}/github/repositories",
        params={"workspace_id": test_workspace.id},
    )

    assert response.status_code == 403


# =============================================================================
# GET /api/v1/github/repositories/{repo_full_name}/branches Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_repository_branches_success(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test getting repository branches"""
    with patch(
        "app.environments.service.EnvironmentService.get_repository_branches",
        new_callable=AsyncMock,
    ) as mock_branches:
        mock_branches.return_value = [
            {"name": "main", "protected": True},
            {"name": "develop", "protected": False},
        ]

        response = await client.get(
            f"{API_PREFIX}/github/repositories/testuser/repo1/branches",
            params={"workspace_id": test_workspace.id},
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert "branches" in data
    assert len(data["branches"]) == 2


@pytest.mark.asyncio
async def test_get_repository_branches_unauthorized(client, test_workspace):
    """Test getting branches without authentication"""
    response = await client.get(
        f"{API_PREFIX}/github/repositories/testuser/repo1/branches",
        params={"workspace_id": test_workspace.id},
    )

    assert response.status_code == 403
