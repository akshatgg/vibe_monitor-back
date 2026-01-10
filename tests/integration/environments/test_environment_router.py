"""
Integration tests for environments router endpoints.

Tests cover:
- GET    /api/v1/workspaces/{workspace_id}/environments - List environments
- GET    /api/v1/workspaces/{workspace_id}/environments/{id} - Get environment
- POST   /api/v1/workspaces/{workspace_id}/environments - Create environment
- PATCH  /api/v1/workspaces/{workspace_id}/environments/{id} - Update environment
- DELETE /api/v1/workspaces/{workspace_id}/environments/{id} - Delete environment
- POST   /api/v1/workspaces/{workspace_id}/environments/{id}/set-default - Set default
- GET    /api/v1/workspaces/{workspace_id}/environments/{id}/repositories - List repos
- POST   /api/v1/workspaces/{workspace_id}/environments/{id}/repositories - Add repo
- PATCH  /api/v1/workspaces/{workspace_id}/environments/{id}/repositories/{repo_id} - Update
- DELETE /api/v1/workspaces/{workspace_id}/environments/{id}/repositories/{repo_id} - Remove
"""

import uuid

import pytest

from tests.integration.conftest import API_PREFIX


@pytest.mark.asyncio
async def test_list_environments(
    auth_client, test_user, test_workspace, test_environment
):
    """Test listing environments for a workspace."""
    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments"
    )
    assert response.status_code == 200
    data = response.json()
    assert "environments" in data
    assert isinstance(data["environments"], list)
    assert len(data["environments"]) >= 1
    env_ids = [e["id"] for e in data["environments"]]
    assert test_environment.id in env_ids


@pytest.mark.asyncio
async def test_list_environments_empty(auth_client, test_db, test_user):
    """Test listing environments for a workspace with no environments."""
    from app.models import Membership, Role, Workspace, WorkspaceType

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Empty Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(workspace)
    await test_db.flush()

    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(membership)
    await test_db.commit()

    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{workspace.id}/environments"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["environments"] == []


@pytest.mark.asyncio
async def test_get_environment(
    auth_client, test_user, test_workspace, test_environment
):
    """Test getting a single environment by ID."""
    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{test_environment.id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_environment.id
    assert data["name"] == test_environment.name
    assert data["workspace_id"] == test_workspace.id
    assert "repository_configs" in data


@pytest.mark.asyncio
async def test_get_environment_not_found(auth_client, test_user, test_workspace):
    """Test getting a non-existent environment."""
    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/nonexistent-id"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_environment(auth_client, test_user, test_workspace):
    """Test creating a new environment."""
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments",
        json={
            "name": "Staging",
            "is_default": False,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Staging"
    assert data["is_default"] is False
    assert data["workspace_id"] == test_workspace.id


@pytest.mark.asyncio
async def test_create_environment_as_default(auth_client, test_user, test_workspace):
    """Test creating a new environment as default."""
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments",
        json={
            "name": "New Production",
            "is_default": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["is_default"] is True


@pytest.mark.asyncio
async def test_create_environment_duplicate_name(
    auth_client, test_user, test_workspace, test_environment
):
    """Test that creating environment with duplicate name fails."""
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments",
        json={
            "name": test_environment.name,  # Same name as existing
            "is_default": False,
        },
    )
    # Should fail due to unique constraint
    assert response.status_code in [400, 409, 422, 500]


@pytest.mark.asyncio
async def test_update_environment_name(
    auth_client, test_user, test_workspace, test_environment
):
    """Test updating an environment's name."""
    response = await auth_client.patch(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{test_environment.id}",
        json={"name": "Updated Production"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Production"


@pytest.mark.asyncio
async def test_update_environment_auto_discovery(
    auth_client, test_user, test_workspace, test_environment
):
    """Test updating is_default setting."""
    response = await auth_client.patch(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{test_environment.id}",
        json={"is_default": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_default"] is False


@pytest.mark.asyncio
async def test_delete_environment(auth_client, test_db, test_user, test_workspace):
    """Test deleting an environment."""
    from app.models import Environment

    env_to_delete = Environment(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        name="Env to Delete",
        is_default=False,
    )
    test_db.add(env_to_delete)
    await test_db.commit()

    response = await auth_client.delete(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{env_to_delete.id}"
    )
    assert response.status_code == 204

    # Verify it's deleted
    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{env_to_delete.id}"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_set_default_environment(auth_client, test_db, test_user, test_workspace):
    """Test setting an environment as default."""
    from app.models import Environment

    # Create a non-default environment
    env = Environment(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        name="Soon Default",
        is_default=False,
    )
    test_db.add(env)
    await test_db.commit()

    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{env.id}/set-default"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_default"] is True


@pytest.mark.asyncio
async def test_list_environment_repositories(
    auth_client, test_db, test_user, test_workspace, test_environment
):
    """Test listing repository configurations for an environment."""
    from app.models import EnvironmentRepository

    # Add a repository to the environment
    repo_config = EnvironmentRepository(
        id=str(uuid.uuid4()),
        environment_id=test_environment.id,
        repo_full_name="owner/test-repo",
        branch_name="main",
        is_enabled=True,
    )
    test_db.add(repo_config)
    await test_db.commit()

    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{test_environment.id}/repositories"
    )
    assert response.status_code == 200
    data = response.json()
    assert "repositories" in data
    assert len(data["repositories"]) >= 1
    repo_names = [r["repo_full_name"] for r in data["repositories"]]
    assert "owner/test-repo" in repo_names


@pytest.mark.asyncio
async def test_add_repository_to_environment(
    auth_client, test_user, test_workspace, test_environment
):
    """Test adding a repository to an environment."""
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{test_environment.id}/repositories",
        json={
            "repo_full_name": "owner/new-repo",
            "branch_name": "develop",
            "is_enabled": False,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["repo_full_name"] == "owner/new-repo"
    assert data["branch_name"] == "develop"
    assert data["is_enabled"] is False


@pytest.mark.asyncio
async def test_add_repository_without_branch(
    auth_client, test_user, test_workspace, test_environment
):
    """Test adding a repository without a branch (enabled by default)."""
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{test_environment.id}/repositories",
        json={
            "repo_full_name": "owner/no-branch-repo",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["repo_full_name"] == "owner/no-branch-repo"
    assert data["branch_name"] is None
    assert data["is_enabled"] is True  # Default is True per schema


@pytest.mark.asyncio
async def test_update_environment_repository(
    auth_client, test_db, test_user, test_workspace, test_environment
):
    """Test updating a repository configuration."""
    from app.models import EnvironmentRepository

    repo_config = EnvironmentRepository(
        id=str(uuid.uuid4()),
        environment_id=test_environment.id,
        repo_full_name="owner/update-repo",
        branch_name=None,
        is_enabled=False,
    )
    test_db.add(repo_config)
    await test_db.commit()

    response = await auth_client.patch(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{test_environment.id}/repositories/{repo_config.id}",
        json={
            "branch_name": "main",
            "is_enabled": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["branch_name"] == "main"
    assert data["is_enabled"] is True


@pytest.mark.asyncio
async def test_remove_repository_from_environment(
    auth_client, test_db, test_user, test_workspace, test_environment
):
    """Test removing a repository from an environment."""
    from app.models import EnvironmentRepository

    repo_config = EnvironmentRepository(
        id=str(uuid.uuid4()),
        environment_id=test_environment.id,
        repo_full_name="owner/remove-repo",
        branch_name="main",
        is_enabled=True,
    )
    test_db.add(repo_config)
    await test_db.commit()

    response = await auth_client.delete(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{test_environment.id}/repositories/{repo_config.id}"
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_non_member_cannot_access_environments(
    auth_client, test_db, test_user, second_user
):
    """Test that a non-member cannot access workspace environments."""
    from app.models import Environment, Membership, Role, Workspace, WorkspaceType

    # Create a workspace owned by second_user
    other_workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Other Workspace",
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
        name="Private Environment",
    )
    test_db.add(env)
    await test_db.commit()

    # test_user (authenticated via auth_client) is not a member
    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{other_workspace.id}/environments"
    )
    # Should fail because test_user is not a member
    assert response.status_code in [403, 404]


@pytest.mark.asyncio
async def test_member_can_list_environments(
    auth_client, test_db, test_user, second_user
):
    """Test that a regular member can list environments."""
    from app.models import Environment, Membership, Role, Workspace, WorkspaceType

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Shared Workspace",
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
        name="Shared Environment",
    )
    test_db.add(env)
    await test_db.commit()

    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{workspace.id}/environments"
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["environments"]) >= 1


@pytest.mark.asyncio
async def test_non_owner_cannot_create_environment(
    auth_client, test_db, test_user, second_user
):
    """Test that a non-owner cannot create an environment."""
    from app.models import Membership, Role, Workspace, WorkspaceType

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Restricted Workspace",
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

    # test_user is just a member
    member_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        workspace_id=workspace.id,
        role=Role.USER,
    )
    test_db.add(member_membership)
    await test_db.commit()

    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{workspace.id}/environments",
        json={"name": "Should Fail"},
    )
    assert response.status_code in [400, 403]


@pytest.mark.asyncio
async def test_environment_response_includes_timestamps(
    auth_client, test_user, test_workspace, test_environment
):
    """Test that environment response includes timestamp fields."""
    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/environments/{test_environment.id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert "created_at" in data
    assert data["created_at"] is not None
