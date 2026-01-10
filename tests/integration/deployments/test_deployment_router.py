"""
Integration tests for deployments router endpoints.

Tests cover:
- POST   /api/v1/deployments/webhook - Create deployment via webhook
- POST   /api/v1/deployments/workspaces/{workspace_id}/environments/{env_id} - Create deployment
- GET    /api/v1/deployments/workspaces/{workspace_id}/environments/{env_id} - List deployments
- GET    /api/v1/deployments/workspaces/{workspace_id}/environments/{env_id}/repos/{repo}/latest - Latest
- POST   /api/v1/deployments/workspaces/{workspace_id}/api-keys - Create API key
- GET    /api/v1/deployments/workspaces/{workspace_id}/api-keys - List API keys
- DELETE /api/v1/deployments/workspaces/{workspace_id}/api-keys/{key_id} - Delete API key
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

import pytest

from tests.integration.conftest import API_PREFIX


@pytest.mark.asyncio
async def test_create_deployment(
    auth_client, test_user, test_workspace, test_environment
):
    """Test creating a deployment record."""
    response = await auth_client.post(
        f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/environments/{test_environment.id}",
        json={
            "repo_full_name": "owner/my-repo",
            "branch": "main",
            "commit_sha": "abc123def456789",
            "status": "success",
            "source": "manual",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["repo_full_name"] == "owner/my-repo"
    assert data["branch"] == "main"
    assert data["commit_sha"] == "abc123def456789"
    assert data["status"] == "success"
    assert data["environment_id"] == test_environment.id


@pytest.mark.asyncio
async def test_create_deployment_minimal(
    auth_client, test_user, test_workspace, test_environment
):
    """Test creating a deployment with minimal data."""
    response = await auth_client.post(
        f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/environments/{test_environment.id}",
        json={
            "repo_full_name": "owner/minimal-repo",
            "commit_sha": "abc1234def5678",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["repo_full_name"] == "owner/minimal-repo"
    assert data["status"] == "success"  # Default
    assert data["source"] == "manual"  # Default


@pytest.mark.asyncio
async def test_create_deployment_with_metadata(
    auth_client, test_user, test_workspace, test_environment
):
    """Test creating a deployment with extra metadata."""
    response = await auth_client.post(
        f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/environments/{test_environment.id}",
        json={
            "repo_full_name": "owner/meta-repo",
            "commit_sha": "xyz9876abc1234",
            "branch": "release",
            "extra_data": {
                "ci_run_id": "12345",
                "triggered_by": "merge",
            },
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["extra_data"]["ci_run_id"] == "12345"


@pytest.mark.asyncio
async def test_list_deployments(
    auth_client, test_db, test_user, test_workspace, test_environment
):
    """Test listing deployments for an environment."""
    from app.models import Deployment, DeploymentSource, DeploymentStatus

    # Create some deployments
    for i in range(3):
        deployment = Deployment(
            id=str(uuid.uuid4()),
            environment_id=test_environment.id,
            repo_full_name="owner/list-repo",
            branch="main",
            commit_sha=f"commit{i}",
            status=DeploymentStatus.SUCCESS,
            source=DeploymentSource.MANUAL,
            deployed_at=datetime.now(timezone.utc),
        )
        test_db.add(deployment)
    await test_db.commit()

    response = await auth_client.get(
        f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/environments/{test_environment.id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert "deployments" in data
    assert "total" in data
    assert data["total"] >= 3
    assert len(data["deployments"]) >= 3


@pytest.mark.asyncio
async def test_list_deployments_with_pagination(
    auth_client, test_db, test_user, test_workspace, test_environment
):
    """Test listing deployments with pagination."""
    from app.models import Deployment, DeploymentSource, DeploymentStatus

    # Create several deployments
    for i in range(10):
        deployment = Deployment(
            id=str(uuid.uuid4()),
            environment_id=test_environment.id,
            repo_full_name="owner/paginated-repo",
            branch="main",
            commit_sha=f"paginatedcommit{i}",
            status=DeploymentStatus.SUCCESS,
            source=DeploymentSource.MANUAL,
            deployed_at=datetime.now(timezone.utc),
        )
        test_db.add(deployment)
    await test_db.commit()

    # Request with limit
    response = await auth_client.get(
        f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/environments/{test_environment.id}",
        params={"limit": 5, "offset": 0},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["deployments"]) == 5
    assert data["total"] >= 10


@pytest.mark.asyncio
async def test_list_deployments_filter_by_repo(
    auth_client, test_db, test_user, test_workspace, test_environment
):
    """Test filtering deployments by repository."""
    from app.models import Deployment, DeploymentSource, DeploymentStatus

    # Create deployments for different repos
    for repo in ["owner/repo-a", "owner/repo-b"]:
        deployment = Deployment(
            id=str(uuid.uuid4()),
            environment_id=test_environment.id,
            repo_full_name=repo,
            branch="main",
            status=DeploymentStatus.SUCCESS,
            source=DeploymentSource.MANUAL,
            deployed_at=datetime.now(timezone.utc),
        )
        test_db.add(deployment)
    await test_db.commit()

    response = await auth_client.get(
        f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/environments/{test_environment.id}",
        params={"repo": "owner/repo-a"},
    )
    assert response.status_code == 200
    data = response.json()
    for d in data["deployments"]:
        assert d["repo_full_name"] == "owner/repo-a"


@pytest.mark.asyncio
async def test_get_latest_deployment(
    auth_client, test_db, test_user, test_workspace, test_environment
):
    """Test getting the latest deployment for a repository."""
    from app.models import Deployment, DeploymentSource, DeploymentStatus

    # Create deployments with different times
    older = Deployment(
        id=str(uuid.uuid4()),
        environment_id=test_environment.id,
        repo_full_name="owner/latest-repo",
        branch="main",
        commit_sha="older123",
        status=DeploymentStatus.SUCCESS,
        source=DeploymentSource.MANUAL,
        deployed_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    test_db.add(older)

    newer = Deployment(
        id=str(uuid.uuid4()),
        environment_id=test_environment.id,
        repo_full_name="owner/latest-repo",
        branch="main",
        commit_sha="newer456",
        status=DeploymentStatus.SUCCESS,
        source=DeploymentSource.MANUAL,
        deployed_at=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    test_db.add(newer)
    await test_db.commit()

    response = await auth_client.get(
        f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/environments/{test_environment.id}/repos/owner/latest-repo/latest"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["commit_sha"] == "newer456"


@pytest.mark.asyncio
async def test_get_latest_deployment_not_found(
    auth_client, test_user, test_workspace, test_environment
):
    """Test getting latest deployment for a repo with no deployments."""
    response = await auth_client.get(
        f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/environments/{test_environment.id}/repos/owner/nonexistent-repo/latest"
    )
    # Should return null/None when no deployments exist
    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.asyncio
async def test_create_api_key(auth_client, test_user, test_workspace):
    """Test creating an API key."""
    response = await auth_client.post(
        f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/api-keys",
        json={"name": "CI/CD Key"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "CI/CD Key"
    assert "key" in data  # Full key shown only on creation
    assert "key_prefix" in data
    assert len(data["key"]) > 8  # Key should be substantial


@pytest.mark.asyncio
async def test_list_api_keys(auth_client, test_db, test_user, test_workspace):
    """Test listing API keys for a workspace."""
    from app.models import WorkspaceApiKey

    # Create some API keys
    for i in range(2):
        key = secrets.token_urlsafe(32)
        api_key = WorkspaceApiKey(
            id=str(uuid.uuid4()),
            workspace_id=test_workspace.id,
            name=f"Test Key {i}",
            key_hash=hashlib.sha256(key.encode()).hexdigest(),
            key_prefix=key[:8],
        )
        test_db.add(api_key)
    await test_db.commit()

    response = await auth_client.get(
        f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/api-keys"
    )
    assert response.status_code == 200
    data = response.json()
    assert "api_keys" in data
    assert len(data["api_keys"]) >= 2
    # Full key should NOT be shown in list
    for key in data["api_keys"]:
        assert "key" not in key or key.get("key") is None


@pytest.mark.asyncio
async def test_delete_api_key(auth_client, test_db, test_user, test_workspace):
    """Test deleting an API key."""
    from app.models import WorkspaceApiKey

    key = secrets.token_urlsafe(32)
    api_key = WorkspaceApiKey(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        name="Key to Delete",
        key_hash=hashlib.sha256(key.encode()).hexdigest(),
        key_prefix=key[:8],
    )
    test_db.add(api_key)
    await test_db.commit()

    response = await auth_client.delete(
        f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/api-keys/{api_key.id}"
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_webhook_deployment_invalid_key(client, test_db, test_workspace):
    """Test that webhook endpoint rejects invalid API keys."""
    response = await client.post(
        f"{API_PREFIX}/deployments/webhook",
        json={
            "environment": "production",
            "repository": "owner/repo",
            "commit_sha": "abc1234567890",
            "branch": "main",
        },
        headers={"X-Workspace-Key": "invalid-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_webhook_deployment_with_valid_key(
    client, test_db, test_user, test_workspace, test_environment
):
    """Test creating a deployment via webhook with valid API key."""
    from app.models import WorkspaceApiKey

    # Create an API key
    raw_key = secrets.token_urlsafe(32)
    api_key = WorkspaceApiKey(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        name="Webhook Key",
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        key_prefix=raw_key[:8],
    )
    test_db.add(api_key)
    await test_db.commit()

    response = await client.post(
        f"{API_PREFIX}/deployments/webhook",
        json={
            "environment": test_environment.name,  # Use environment name
            "repository": "owner/webhook-repo",
            "branch": "main",
            "commit_sha": "webhook123456",
            "status": "success",
        },
        headers={"X-Workspace-Key": raw_key},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["repo_full_name"] == "owner/webhook-repo"
    assert data["source"] == "webhook"


@pytest.mark.asyncio
async def test_non_member_cannot_access_deployments(
    auth_client, test_db, test_user, second_user
):
    """Test that non-members cannot access deployment endpoints."""
    from app.models import Environment, Membership, Role, Workspace, WorkspaceType

    # Create a workspace owned by second_user
    other_workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Private Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(other_workspace)
    await test_db.flush()

    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=other_workspace.id,
        role=Role.OWNER,
    )
    test_db.add(membership)

    env = Environment(
        id=str(uuid.uuid4()),
        workspace_id=other_workspace.id,
        name="Private Env",
    )
    test_db.add(env)
    await test_db.commit()

    # test_user is NOT a member
    response = await auth_client.get(
        f"{API_PREFIX}/deployments/workspaces/{other_workspace.id}/environments/{env.id}"
    )
    assert response.status_code in [403, 404]


@pytest.mark.asyncio
async def test_member_can_list_deployments(
    auth_client, test_db, test_user, second_user
):
    """Test that regular members can list deployments."""
    from app.models import Environment, Membership, Role, Workspace, WorkspaceType

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Shared Deploy Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(workspace)
    await test_db.flush()

    # second_user is owner
    owner_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(owner_membership)

    # test_user is member
    member_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        workspace_id=workspace.id,
        role=Role.USER,
    )
    test_db.add(member_membership)

    env = Environment(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Shared Env",
    )
    test_db.add(env)
    await test_db.commit()

    response = await auth_client.get(
        f"{API_PREFIX}/deployments/workspaces/{workspace.id}/environments/{env.id}"
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_non_owner_cannot_create_api_key(
    auth_client, test_db, test_user, second_user
):
    """Test that non-owners cannot create API keys."""
    from app.models import Membership, Role, Workspace, WorkspaceType

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Key Restricted Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(workspace)
    await test_db.flush()

    # second_user is owner
    owner_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(owner_membership)

    # test_user is member
    member_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        workspace_id=workspace.id,
        role=Role.USER,
    )
    test_db.add(member_membership)
    await test_db.commit()

    response = await auth_client.post(
        f"{API_PREFIX}/deployments/workspaces/{workspace.id}/api-keys",
        json={"name": "Should Fail"},
    )
    assert response.status_code in [400, 403]


@pytest.mark.asyncio
async def test_deployment_statuses(
    auth_client, test_user, test_workspace, test_environment
):
    """Test creating deployments with different statuses."""
    statuses = ["pending", "in_progress", "success", "failed", "cancelled"]

    for i, status in enumerate(statuses):
        response = await auth_client.post(
            f"{API_PREFIX}/deployments/workspaces/{test_workspace.id}/environments/{test_environment.id}",
            json={
                "repo_full_name": f"owner/{status}-repo",
                "commit_sha": f"commit{i:07d}",
                "status": status,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == status
