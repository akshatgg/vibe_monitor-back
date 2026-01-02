"""
Integration tests for Datadog Integration endpoints.

Tests the following endpoints:
- POST /api/v1/datadog/integration - Create Datadog integration
- GET /api/v1/datadog/integration/status - Get integration status
- DELETE /api/v1/datadog/integration - Delete integration
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.models import Membership, User, Workspace, WorkspaceType
from tests.integration.conftest import get_auth_headers

API_PREFIX = "/api/v1"


# =============================================================================
# Helper Functions
# =============================================================================


async def create_test_user(db, user_id: str = None, email: str = None) -> User:
    """Create a test user in the database."""
    user = User(
        id=user_id or str(uuid.uuid4()),
        name="Test User",
        email=email or f"test_{uuid.uuid4().hex[:8]}@example.com",
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


async def create_test_workspace(
    db, workspace_id: str = None, workspace_type: WorkspaceType = WorkspaceType.TEAM
) -> Workspace:
    """Create a test workspace in the database."""
    workspace = Workspace(
        id=workspace_id or str(uuid.uuid4()),
        name="Test Workspace",
        type=workspace_type,
    )
    db.add(workspace)
    await db.flush()
    return workspace


async def create_test_membership(db, user: User, workspace: Workspace) -> Membership:
    """Create a membership linking user to workspace."""
    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=user.id,
        workspace_id=workspace.id,
    )
    db.add(membership)
    await db.flush()
    return membership


# =============================================================================
# Test: Create Datadog Integration
# =============================================================================


@pytest.mark.asyncio
async def test_create_datadog_integration_success(client, test_db):
    """Test successful creation of Datadog integration."""
    # Setup test data
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace)
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    # Mock external API calls
    with (
        patch(
            "app.datadog.integration.service.verify_datadog_credentials",
            new_callable=AsyncMock,
            return_value=(True, ""),
        ),
        patch(
            "app.datadog.integration.service.check_datadog_health",
            new_callable=AsyncMock,
            return_value=("healthy", None),
        ),
    ):
        response = await client.post(
            f"{API_PREFIX}/datadog/integration",
            params={"workspace_id": workspace.id},
            json={
                "api_key": "a" * 32,  # Valid length API key
                "app_key": "b" * 40,  # Valid length App key
                "region": "us1",
            },
            headers=auth_headers,
        )

    assert response.status_code == 201
    data = response.json()
    assert data["workspace_id"] == workspace.id
    assert data["region"] == "us1"
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_create_datadog_integration_invalid_credentials(client, test_db):
    """Test creation fails with invalid Datadog credentials."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace)
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    with patch(
        "app.datadog.integration.service.verify_datadog_credentials",
        new_callable=AsyncMock,
        return_value=(False, "Invalid API key"),
    ):
        response = await client.post(
            f"{API_PREFIX}/datadog/integration",
            params={"workspace_id": workspace.id},
            json={
                "api_key": "a" * 32,
                "app_key": "b" * 40,
                "region": "us1",
            },
            headers=auth_headers,
        )

    assert response.status_code == 400
    assert "Invalid Datadog credentials" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_datadog_integration_invalid_region(client, test_db):
    """Test creation fails with invalid region."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace)
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    response = await client.post(
        f"{API_PREFIX}/datadog/integration",
        params={"workspace_id": workspace.id},
        json={
            "api_key": "a" * 32,
            "app_key": "b" * 40,
            "region": "invalid_region",
        },
        headers=auth_headers,
    )

    assert response.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_create_datadog_integration_short_api_key(client, test_db):
    """Test creation fails with API key that's too short."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace)
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    response = await client.post(
        f"{API_PREFIX}/datadog/integration",
        params={"workspace_id": workspace.id},
        json={
            "api_key": "short",  # Too short
            "app_key": "b" * 40,
            "region": "us1",
        },
        headers=auth_headers,
    )

    assert response.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_create_datadog_integration_no_workspace_access(client, test_db):
    """Test creation fails when user has no access to workspace."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    # No membership created
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    response = await client.post(
        f"{API_PREFIX}/datadog/integration",
        params={"workspace_id": workspace.id},
        json={
            "api_key": "a" * 32,
            "app_key": "b" * 40,
            "region": "us1",
        },
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_datadog_integration_personal_workspace_blocked(client, test_db):
    """Test that Datadog integration is blocked for personal workspaces."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(
        test_db, workspace_type=WorkspaceType.PERSONAL
    )
    await create_test_membership(test_db, user, workspace)
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    response = await client.post(
        f"{API_PREFIX}/datadog/integration",
        params={"workspace_id": workspace.id},
        json={
            "api_key": "a" * 32,
            "app_key": "b" * 40,
            "region": "us1",
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "not available for personal workspaces" in response.json()["detail"]


# =============================================================================
# Test: Get Datadog Integration Status
# =============================================================================


@pytest.mark.asyncio
async def test_get_datadog_integration_status_not_connected(client, test_db):
    """Test status check when no integration exists."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace)
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    response = await client.get(
        f"{API_PREFIX}/datadog/integration/status",
        params={"workspace_id": workspace.id},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_connected"] is False
    assert data["integration"] is None


@pytest.mark.asyncio
async def test_get_datadog_integration_status_connected(client, test_db):
    """Test status check when integration exists."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace)
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    # First create an integration
    with (
        patch(
            "app.datadog.integration.service.verify_datadog_credentials",
            new_callable=AsyncMock,
            return_value=(True, ""),
        ),
        patch(
            "app.datadog.integration.service.check_datadog_health",
            new_callable=AsyncMock,
            return_value=("healthy", None),
        ),
    ):
        await client.post(
            f"{API_PREFIX}/datadog/integration",
            params={"workspace_id": workspace.id},
            json={
                "api_key": "a" * 32,
                "app_key": "b" * 40,
                "region": "us1",
            },
            headers=auth_headers,
        )

    # Now check status
    response = await client.get(
        f"{API_PREFIX}/datadog/integration/status",
        params={"workspace_id": workspace.id},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_connected"] is True
    assert data["integration"]["workspace_id"] == workspace.id
    assert data["integration"]["region"] == "us1"


@pytest.mark.asyncio
async def test_get_datadog_integration_status_no_access(client, test_db):
    """Test status check fails without workspace access."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    # No membership
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    response = await client.get(
        f"{API_PREFIX}/datadog/integration/status",
        params={"workspace_id": workspace.id},
        headers=auth_headers,
    )

    assert response.status_code == 403


# =============================================================================
# Test: Delete Datadog Integration
# =============================================================================


@pytest.mark.asyncio
async def test_delete_datadog_integration_success(client, test_db):
    """Test successful deletion of Datadog integration."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace)
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    # First create an integration
    with (
        patch(
            "app.datadog.integration.service.verify_datadog_credentials",
            new_callable=AsyncMock,
            return_value=(True, ""),
        ),
        patch(
            "app.datadog.integration.service.check_datadog_health",
            new_callable=AsyncMock,
            return_value=("healthy", None),
        ),
    ):
        await client.post(
            f"{API_PREFIX}/datadog/integration",
            params={"workspace_id": workspace.id},
            json={
                "api_key": "a" * 32,
                "app_key": "b" * 40,
                "region": "us1",
            },
            headers=auth_headers,
        )

    # Delete the integration
    response = await client.delete(
        f"{API_PREFIX}/datadog/integration",
        params={"workspace_id": workspace.id},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Datadog integration deleted successfully"
    assert data["workspace_id"] == workspace.id


@pytest.mark.asyncio
async def test_delete_datadog_integration_not_found(client, test_db):
    """Test deletion fails when integration doesn't exist."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace)
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    response = await client.delete(
        f"{API_PREFIX}/datadog/integration",
        params={"workspace_id": workspace.id},
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_datadog_integration_no_access(client, test_db):
    """Test deletion fails without workspace access."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    # No membership
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    response = await client.delete(
        f"{API_PREFIX}/datadog/integration",
        params={"workspace_id": workspace.id},
        headers=auth_headers,
    )

    assert response.status_code == 403


# =============================================================================
# Test: Duplicate Integration Prevention
# =============================================================================


@pytest.mark.asyncio
async def test_create_datadog_integration_duplicate(client, test_db):
    """Test that creating a second integration for the same workspace fails."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace)
    await test_db.commit()

    auth_headers = get_auth_headers(user)

    # Create first integration
    with (
        patch(
            "app.datadog.integration.service.verify_datadog_credentials",
            new_callable=AsyncMock,
            return_value=(True, ""),
        ),
        patch(
            "app.datadog.integration.service.check_datadog_health",
            new_callable=AsyncMock,
            return_value=("healthy", None),
        ),
    ):
        response1 = await client.post(
            f"{API_PREFIX}/datadog/integration",
            params={"workspace_id": workspace.id},
            json={
                "api_key": "a" * 32,
                "app_key": "b" * 40,
                "region": "us1",
            },
            headers=auth_headers,
        )

    assert response1.status_code == 201

    # Try to create second integration
    with patch(
        "app.datadog.integration.service.verify_datadog_credentials",
        new_callable=AsyncMock,
        return_value=(True, ""),
    ):
        response2 = await client.post(
            f"{API_PREFIX}/datadog/integration",
            params={"workspace_id": workspace.id},
            json={
                "api_key": "c" * 32,
                "app_key": "d" * 40,
                "region": "eu1",
            },
            headers=auth_headers,
        )

    assert response2.status_code == 400
    assert "already exists" in response2.json()["detail"]
