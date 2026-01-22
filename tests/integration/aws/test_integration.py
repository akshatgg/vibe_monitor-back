"""
Integration tests for AWS Integration API endpoints.

These tests verify the /api/v1/aws/integration/* endpoints work correctly.
AWS Integration endpoints require authentication.

Uses the auth_client and test_workspace fixtures from conftest.py for authenticated
requests.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.integration.conftest import API_PREFIX


@pytest.mark.asyncio
async def test_store_aws_integration_success(
    auth_client, test_db, test_user, test_workspace
):
    """Test storing AWS integration with valid role ARN"""
    mock_integration_response = MagicMock()
    mock_integration_response.id = str(uuid.uuid4())
    mock_integration_response.workspace_id = test_workspace.id
    mock_integration_response.role_arn = "arn:aws:iam::123456789012:role/VibeMonitor"
    mock_integration_response.has_external_id = False
    mock_integration_response.aws_region = "us-west-1"
    mock_integration_response.is_active = True
    mock_integration_response.credentials_expiration = datetime.now(
        timezone.utc
    ) + timedelta(hours=1)
    mock_integration_response.last_verified_at = datetime.now(timezone.utc)
    mock_integration_response.created_at = datetime.now(timezone.utc)
    mock_integration_response.updated_at = None

    with (
        patch(
            "app.aws.Integration.router.check_integration_permission",
            new_callable=AsyncMock,
        ),
        patch(
            "app.aws.Integration.router.aws_integration_service.create_aws_integration",
            new_callable=AsyncMock,
            return_value=mock_integration_response,
        ),
    ):
        response = await auth_client.post(
            f"{API_PREFIX}/aws/integration?workspace_id={test_workspace.id}",
            json={
                "role_arn": "arn:aws:iam::123456789012:role/VibeMonitor",
                "aws_region": "us-west-1",
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert data["role_arn"] == "arn:aws:iam::123456789012:role/VibeMonitor"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_store_aws_integration_with_external_id(
    auth_client, test_db, test_user, test_workspace
):
    """Test storing AWS integration with external ID for cross-account access"""
    mock_integration_response = MagicMock()
    mock_integration_response.id = str(uuid.uuid4())
    mock_integration_response.workspace_id = test_workspace.id
    mock_integration_response.role_arn = "arn:aws:iam::123456789012:role/VibeMonitor"
    mock_integration_response.has_external_id = True
    mock_integration_response.aws_region = "us-east-1"
    mock_integration_response.is_active = True
    mock_integration_response.credentials_expiration = datetime.now(
        timezone.utc
    ) + timedelta(hours=1)
    mock_integration_response.last_verified_at = datetime.now(timezone.utc)
    mock_integration_response.created_at = datetime.now(timezone.utc)
    mock_integration_response.updated_at = None

    with (
        patch(
            "app.aws.Integration.router.check_integration_permission",
            new_callable=AsyncMock,
        ),
        patch(
            "app.aws.Integration.router.aws_integration_service.create_aws_integration",
            new_callable=AsyncMock,
            return_value=mock_integration_response,
        ),
    ):
        response = await auth_client.post(
            f"{API_PREFIX}/aws/integration?workspace_id={test_workspace.id}",
            json={
                "role_arn": "arn:aws:iam::123456789012:role/VibeMonitor",
                "external_id": "my-external-id-12345",
                "aws_region": "us-east-1",
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert data["has_external_id"] is True


@pytest.mark.asyncio
async def test_store_aws_integration_missing_role_arn(
    auth_client, test_db, test_user, test_workspace
):
    """Test storing AWS integration without role ARN returns 422"""
    response = await auth_client.post(
        f"{API_PREFIX}/aws/integration?workspace_id={test_workspace.id}",
        json={"aws_region": "us-west-1"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_store_aws_integration_unauthorized(client, test_db):
    """Test storing AWS integration without auth token returns 401 or 403"""
    workspace_id = str(uuid.uuid4())
    response = await client.post(
        f"{API_PREFIX}/aws/integration?workspace_id={workspace_id}",
        json={"role_arn": "arn:aws:iam::123456789012:role/VibeMonitor"},
    )

    # Should be 401 (Unauthorized) or 403 (Forbidden) when no auth header
    assert response.status_code in [401, 403]


@pytest.mark.asyncio
async def test_store_aws_integration_no_workspace_access(
    auth_client, test_db, test_user
):
    """Test storing AWS integration for a workspace user doesn't have access to"""
    # Use a workspace ID that doesn't exist/user has no access to
    other_workspace_id = str(uuid.uuid4())

    response = await auth_client.post(
        f"{API_PREFIX}/aws/integration?workspace_id={other_workspace_id}",
        json={"role_arn": "arn:aws:iam::123456789012:role/VibeMonitor"},
    )

    assert response.status_code == 403
    data = response.json()
    assert "Access denied" in data["detail"]


@pytest.mark.asyncio
async def test_store_aws_integration_invalid_role(
    auth_client, test_db, test_user, test_workspace
):
    """Test storing AWS integration with invalid role ARN"""
    with (
        patch(
            "app.aws.Integration.router.check_integration_permission",
            new_callable=AsyncMock,
        ),
        patch(
            "app.aws.Integration.router.aws_integration_service.create_aws_integration",
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid AWS role: Access denied to assume role"),
        ),
    ):
        response = await auth_client.post(
            f"{API_PREFIX}/aws/integration?workspace_id={test_workspace.id}",
            json={"role_arn": "arn:aws:iam::123456789012:role/InvalidRole"},
        )

    assert response.status_code == 400
    data = response.json()
    assert "Invalid AWS role" in data["detail"]


@pytest.mark.asyncio
async def test_store_aws_integration_already_exists(
    auth_client, test_db, test_user, test_workspace
):
    """Test storing AWS integration when one already exists"""
    with (
        patch(
            "app.aws.Integration.router.check_integration_permission",
            new_callable=AsyncMock,
        ),
        patch(
            "app.aws.Integration.router.aws_integration_service.create_aws_integration",
            new_callable=AsyncMock,
            side_effect=ValueError(
                "An active AWS integration already exists for this workspace"
            ),
        ),
    ):
        response = await auth_client.post(
            f"{API_PREFIX}/aws/integration?workspace_id={test_workspace.id}",
            json={"role_arn": "arn:aws:iam::123456789012:role/VibeMonitor"},
        )

    assert response.status_code == 400
    data = response.json()
    assert "already exists" in data["detail"]


@pytest.mark.asyncio
async def test_get_aws_integration_status_connected(
    auth_client, test_db, test_user, test_workspace
):
    """Test getting AWS integration status when connected"""
    mock_integration_response = MagicMock()
    mock_integration_response.id = str(uuid.uuid4())
    mock_integration_response.workspace_id = test_workspace.id
    mock_integration_response.role_arn = "arn:aws:iam::123456789012:role/VibeMonitor"
    mock_integration_response.has_external_id = False
    mock_integration_response.aws_region = "us-west-1"
    mock_integration_response.is_active = True
    mock_integration_response.credentials_expiration = datetime.now(
        timezone.utc
    ) + timedelta(hours=1)
    mock_integration_response.last_verified_at = datetime.now(timezone.utc)
    mock_integration_response.created_at = datetime.now(timezone.utc)
    mock_integration_response.updated_at = None

    with patch(
        "app.aws.Integration.router.aws_integration_service.get_aws_integration",
        new_callable=AsyncMock,
        return_value=mock_integration_response,
    ):
        response = await auth_client.get(
            f"{API_PREFIX}/aws/integration/status?workspace_id={test_workspace.id}",
        )

    assert response.status_code == 200
    data = response.json()
    assert data["is_connected"] is True
    assert data["integration"] is not None
    assert (
        data["integration"]["role_arn"] == "arn:aws:iam::123456789012:role/VibeMonitor"
    )


@pytest.mark.asyncio
async def test_get_aws_integration_status_not_connected(
    auth_client, test_db, test_user, test_workspace
):
    """Test getting AWS integration status when not connected"""
    with patch(
        "app.aws.Integration.router.aws_integration_service.get_aws_integration",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = await auth_client.get(
            f"{API_PREFIX}/aws/integration/status?workspace_id={test_workspace.id}",
        )

    assert response.status_code == 200
    data = response.json()
    assert data["is_connected"] is False
    assert data["integration"] is None


@pytest.mark.asyncio
async def test_get_aws_integration_status_unauthorized(client, test_db):
    """Test getting AWS integration status without auth token returns 401 or 403"""
    workspace_id = str(uuid.uuid4())
    response = await client.get(
        f"{API_PREFIX}/aws/integration/status?workspace_id={workspace_id}",
    )

    # Should be 401 (Unauthorized) or 403 (Forbidden) when no auth header
    assert response.status_code in [401, 403]


@pytest.mark.asyncio
async def test_get_aws_integration_status_no_workspace_access(
    auth_client, test_db, test_user
):
    """Test getting AWS integration status for a workspace user doesn't have access to"""
    other_workspace_id = str(uuid.uuid4())

    response = await auth_client.get(
        f"{API_PREFIX}/aws/integration/status?workspace_id={other_workspace_id}",
    )

    assert response.status_code == 403
    data = response.json()
    assert "Access denied" in data["detail"]


@pytest.mark.asyncio
async def test_get_aws_integration_status_service_error(
    auth_client, test_db, test_user, test_workspace
):
    """Test getting AWS integration status handles service errors correctly"""
    with patch(
        "app.aws.Integration.router.aws_integration_service.get_aws_integration",
        new_callable=AsyncMock,
        side_effect=Exception("Database connection failed"),
    ):
        response = await auth_client.get(
            f"{API_PREFIX}/aws/integration/status?workspace_id={test_workspace.id}",
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to get AWS integration status" in data["detail"]


@pytest.mark.asyncio
async def test_delete_aws_integration_success(
    auth_client, test_db, test_user, test_workspace
):
    """Test deleting AWS integration successfully"""
    with patch(
        "app.aws.Integration.router.aws_integration_service.delete_aws_integration",
        new_callable=AsyncMock,
        return_value=True,
    ):
        response = await auth_client.delete(
            f"{API_PREFIX}/aws/integration?workspace_id={test_workspace.id}",
        )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "AWS integration deleted successfully"
    assert data["workspace_id"] == test_workspace.id


@pytest.mark.asyncio
async def test_delete_aws_integration_not_found(
    auth_client, test_db, test_user, test_workspace
):
    """Test deleting AWS integration when it doesn't exist"""
    with patch(
        "app.aws.Integration.router.aws_integration_service.delete_aws_integration",
        new_callable=AsyncMock,
        return_value=False,
    ):
        response = await auth_client.delete(
            f"{API_PREFIX}/aws/integration?workspace_id={test_workspace.id}",
        )

    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"]


@pytest.mark.asyncio
async def test_delete_aws_integration_unauthorized(client, test_db):
    """Test deleting AWS integration without auth token returns 401 or 403"""
    workspace_id = str(uuid.uuid4())
    response = await client.delete(
        f"{API_PREFIX}/aws/integration?workspace_id={workspace_id}",
    )

    # Should be 401 (Unauthorized) or 403 (Forbidden) when no auth header
    assert response.status_code in [401, 403]


@pytest.mark.asyncio
async def test_delete_aws_integration_no_workspace_access(
    auth_client, test_db, test_user
):
    """Test deleting AWS integration for a workspace user doesn't have access to"""
    other_workspace_id = str(uuid.uuid4())

    response = await auth_client.delete(
        f"{API_PREFIX}/aws/integration?workspace_id={other_workspace_id}",
    )

    assert response.status_code == 403
    data = response.json()
    assert "Access denied" in data["detail"]


@pytest.mark.asyncio
async def test_delete_aws_integration_service_error(
    auth_client, test_db, test_user, test_workspace
):
    """Test deleting AWS integration handles service errors correctly"""
    with patch(
        "app.aws.Integration.router.aws_integration_service.delete_aws_integration",
        new_callable=AsyncMock,
        side_effect=Exception("Database error during deletion"),
    ):
        response = await auth_client.delete(
            f"{API_PREFIX}/aws/integration?workspace_id={test_workspace.id}",
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to delete AWS integration" in data["detail"]


@pytest.mark.asyncio
async def test_store_aws_integration_default_region(
    auth_client, test_db, test_user, test_workspace
):
    """Test storing AWS integration uses default region when not specified"""
    mock_integration_response = MagicMock()
    mock_integration_response.id = str(uuid.uuid4())
    mock_integration_response.workspace_id = test_workspace.id
    mock_integration_response.role_arn = "arn:aws:iam::123456789012:role/VibeMonitor"
    mock_integration_response.has_external_id = False
    mock_integration_response.aws_region = "us-west-1"  # Default region
    mock_integration_response.is_active = True
    mock_integration_response.credentials_expiration = datetime.now(
        timezone.utc
    ) + timedelta(hours=1)
    mock_integration_response.last_verified_at = datetime.now(timezone.utc)
    mock_integration_response.created_at = datetime.now(timezone.utc)
    mock_integration_response.updated_at = None

    with (
        patch(
            "app.aws.Integration.router.check_integration_permission",
            new_callable=AsyncMock,
        ),
        patch(
            "app.aws.Integration.router.aws_integration_service.create_aws_integration",
            new_callable=AsyncMock,
            return_value=mock_integration_response,
        ),
    ):
        response = await auth_client.post(
            f"{API_PREFIX}/aws/integration?workspace_id={test_workspace.id}",
            json={"role_arn": "arn:aws:iam::123456789012:role/VibeMonitor"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["aws_region"] == "us-west-1"
