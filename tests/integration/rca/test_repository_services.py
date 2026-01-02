"""
Integration tests for repository services endpoints.

Tests the repository service discovery API endpoints:
- POST /api/v1/repository-services/scan - Scan repository for service names
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from jose import jwt

from app.core.config import settings
from app.models import GitHubIntegration, Integration, Membership, Role, User, Workspace


# =============================================================================
# Test Constants
# =============================================================================

API_PREFIX = "/api/v1/repository-services"


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


async def create_test_user(db, user_id: str = None, email: str = None) -> User:
    """Create a test user in the database."""
    user_id = user_id or str(uuid.uuid4())
    email = email or f"test_{user_id[:8]}@example.com"
    user = User(
        id=user_id,
        name="Test User",
        email=email,
        is_verified=True,
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


async def create_test_integration(db, workspace: Workspace) -> Integration:
    """Create a test integration record in the database."""
    integration = Integration(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        provider="github",
        status="active",
        health_status="healthy",
    )
    db.add(integration)
    await db.commit()
    await db.refresh(integration)
    return integration


async def create_test_github_integration(
    db,
    workspace: Workspace,
    integration: Integration,
    github_username: str = "testuser",
) -> GitHubIntegration:
    """Create a test GitHub integration in the database."""
    github_integration = GitHubIntegration(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        integration_id=integration.id,
        github_user_id="12345",
        github_username=github_username,
        installation_id="67890",
        is_active=True,
    )
    db.add(github_integration)
    await db.commit()
    await db.refresh(github_integration)
    return github_integration


# =============================================================================
# POST /api/v1/repository-services/scan Tests
# =============================================================================


@pytest.mark.asyncio
async def test_scan_repository_unauthenticated(client):
    """Test that unauthenticated requests return 403."""
    workspace_id = str(uuid.uuid4())
    response = await client.post(
        f"{API_PREFIX}/scan",
        params={"workspace_id": workspace_id},
        json={"repo": "test-repo"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_scan_repository_missing_workspace_id(client, test_db):
    """Test that missing workspace_id returns 422."""
    user = await create_test_user(test_db)
    token = create_access_token(user.id, user.email)

    response = await client.post(
        f"{API_PREFIX}/scan",
        headers={"Authorization": f"Bearer {token}"},
        json={"repo": "test-repo"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_scan_repository_missing_repo(client, test_db):
    """Test that missing repo in request body returns 422."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    token = create_access_token(user.id, user.email)

    response = await client.post(
        f"{API_PREFIX}/scan",
        headers={"Authorization": f"Bearer {token}"},
        params={"workspace_id": workspace.id},
        json={},  # Missing repo
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_scan_repository_no_github_integration(client, test_db):
    """Test scanning when workspace has no GitHub integration."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    token = create_access_token(user.id, user.email)

    # Mock the service to raise an exception for missing integration
    with patch(
        "app.services.rca.get_service_name.router.get_github_integration_with_token"
    ) as mock_get_integration:
        mock_get_integration.side_effect = Exception("GitHub integration not found")

        response = await client.post(
            f"{API_PREFIX}/scan",
            headers={"Authorization": f"Bearer {token}"},
            params={"workspace_id": workspace.id},
            json={"repo": "test-repo"},
        )

        assert response.status_code == 500
        assert "github" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_scan_repository_success(client, test_db):
    """Test successfully scanning a repository for services."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    integration = await create_test_integration(test_db, workspace)
    github_integration = await create_test_github_integration(
        test_db,
        workspace,
        integration,
        github_username="testowner",
    )
    token = create_access_token(user.id, user.email)

    # Mock both the integration lookup and service extraction
    with patch(
        "app.services.rca.get_service_name.router.get_github_integration_with_token"
    ) as mock_get_integration:
        mock_get_integration.return_value = (github_integration, "test-token")

        with patch(
            "app.services.rca.get_service_name.router.extract_service_names_from_repo"
        ) as mock_extract:
            mock_extract.return_value = ["api-service", "worker-service", "web-app"]

            response = await client.post(
                f"{API_PREFIX}/scan",
                headers={"Authorization": f"Bearer {token}"},
                params={"workspace_id": workspace.id},
                json={"repo": "my-repo"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["repo_name"] == "testowner/my-repo"
            assert len(data["services"]) == 3
            assert "api-service" in data["services"]


@pytest.mark.asyncio
async def test_scan_repository_no_services_found(client, test_db):
    """Test scanning a repository that has no recognizable services."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    integration = await create_test_integration(test_db, workspace)
    github_integration = await create_test_github_integration(
        test_db,
        workspace,
        integration,
        github_username="testowner",
    )
    token = create_access_token(user.id, user.email)

    with patch(
        "app.services.rca.get_service_name.router.get_github_integration_with_token"
    ) as mock_get_integration:
        mock_get_integration.return_value = (github_integration, "test-token")

        with patch(
            "app.services.rca.get_service_name.router.extract_service_names_from_repo"
        ) as mock_extract:
            mock_extract.return_value = []  # No services found

            response = await client.post(
                f"{API_PREFIX}/scan",
                headers={"Authorization": f"Bearer {token}"},
                params={"workspace_id": workspace.id},
                json={"repo": "empty-repo"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["services"] == []


@pytest.mark.asyncio
async def test_scan_repository_extraction_error(client, test_db):
    """Test handling errors during service extraction."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    integration = await create_test_integration(test_db, workspace)
    github_integration = await create_test_github_integration(
        test_db,
        workspace,
        integration,
        github_username="testowner",
    )
    token = create_access_token(user.id, user.email)

    with patch(
        "app.services.rca.get_service_name.router.get_github_integration_with_token"
    ) as mock_get_integration:
        mock_get_integration.return_value = (github_integration, "test-token")

        with patch(
            "app.services.rca.get_service_name.router.extract_service_names_from_repo"
        ) as mock_extract:
            mock_extract.side_effect = Exception("Repository not accessible")

            response = await client.post(
                f"{API_PREFIX}/scan",
                headers={"Authorization": f"Bearer {token}"},
                params={"workspace_id": workspace.id},
                json={"repo": "private-repo"},
            )

            assert response.status_code == 500
            assert "repository not accessible" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_scan_repository_with_special_characters(client, test_db):
    """Test scanning a repository with special characters in name."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    integration = await create_test_integration(test_db, workspace)
    github_integration = await create_test_github_integration(
        test_db,
        workspace,
        integration,
        github_username="test-org",
    )
    token = create_access_token(user.id, user.email)

    with patch(
        "app.services.rca.get_service_name.router.get_github_integration_with_token"
    ) as mock_get_integration:
        mock_get_integration.return_value = (github_integration, "test-token")

        with patch(
            "app.services.rca.get_service_name.router.extract_service_names_from_repo"
        ) as mock_extract:
            mock_extract.return_value = ["my-service-v2"]

            response = await client.post(
                f"{API_PREFIX}/scan",
                headers={"Authorization": f"Bearer {token}"},
                params={"workspace_id": workspace.id},
                json={"repo": "my-repo-v2"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["repo_name"] == "test-org/my-repo-v2"


# =============================================================================
# Input Validation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_scan_repository_empty_repo_name(client, test_db):
    """Test that empty repo name is rejected."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    token = create_access_token(user.id, user.email)

    response = await client.post(
        f"{API_PREFIX}/scan",
        headers={"Authorization": f"Bearer {token}"},
        params={"workspace_id": workspace.id},
        json={"repo": ""},
    )
    # Empty string may pass validation but fail during extraction
    assert response.status_code in [422, 500]


@pytest.mark.asyncio
async def test_scan_repository_invalid_workspace_id_format(client, test_db):
    """Test that invalid workspace_id format is handled."""
    user = await create_test_user(test_db)
    token = create_access_token(user.id, user.email)

    with patch(
        "app.services.rca.get_service_name.router.get_github_integration_with_token"
    ) as mock_get_integration:
        mock_get_integration.side_effect = Exception("GitHub integration not found")

        response = await client.post(
            f"{API_PREFIX}/scan",
            headers={"Authorization": f"Bearer {token}"},
            params={"workspace_id": "invalid-id-format"},
            json={"repo": "test-repo"},
        )
        # Should handle gracefully - likely 500 as integration won't be found
        assert response.status_code in [400, 404, 500]
