"""
Integration tests for workspace router endpoints.

Tests cover:
- POST /api/v1/workspaces - Create workspace
- GET /api/v1/workspaces - List user workspaces
- GET /api/v1/workspaces/{workspace_id} - Get single workspace
- PATCH /api/v1/workspaces/{workspace_id} - Update workspace
- POST /api/v1/workspaces/{workspace_id}/visit - Mark workspace visited
- DELETE /api/v1/workspaces/{workspace_id} - Delete workspace
"""

import pytest

from tests.integration.conftest import API_PREFIX


@pytest.mark.asyncio
async def test_create_workspace(auth_client, test_user):
    """Test creating a new workspace."""
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/",
        json={
            "name": "New Workspace",
            "visible_to_org": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Workspace"
    assert data["visible_to_org"] is False
    assert "id" in data


@pytest.mark.asyncio
async def test_create_workspace_with_domain(auth_client, test_user):
    """Test creating a workspace with a domain."""
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/",
        json={
            "name": "Company Workspace",
            "domain": "example.com",
            "visible_to_org": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Company Workspace"
    assert data["visible_to_org"] is True


@pytest.mark.asyncio
async def test_get_user_workspaces(auth_client, test_user, test_workspace):
    """Test listing workspaces for a user."""
    response = await auth_client.get(f"{API_PREFIX}/workspaces/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    workspace_ids = [w["id"] for w in data]
    assert test_workspace.id in workspace_ids


@pytest.mark.asyncio
async def test_get_user_workspaces_includes_role(
    auth_client, test_user, test_workspace
):
    """Test that workspace list includes the user's role."""
    response = await auth_client.get(f"{API_PREFIX}/workspaces/")
    assert response.status_code == 200
    data = response.json()
    workspace_data = next(w for w in data if w["id"] == test_workspace.id)
    assert "user_role" in workspace_data
    assert workspace_data["user_role"] == "owner"


@pytest.mark.asyncio
async def test_get_workspace_by_id(auth_client, test_user, test_workspace):
    """Test getting a single workspace by ID."""
    response = await auth_client.get(f"{API_PREFIX}/workspaces/{test_workspace.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_workspace.id
    assert data["name"] == test_workspace.name
    assert "user_role" in data


@pytest.mark.asyncio
async def test_get_workspace_not_found(auth_client, test_user):
    """Test getting a workspace that doesn't exist."""
    response = await auth_client.get(f"{API_PREFIX}/workspaces/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_workspace_no_access(auth_client, test_db, second_user):
    """Test that a user cannot access a workspace they're not a member of."""
    import uuid

    from app.models import Membership, Role, Workspace

    # Create a workspace owned by the second user
    other_workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Other Workspace",
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
    await test_db.commit()

    # Try to access with the first user (auth_client is authenticated as test_user)
    response = await auth_client.get(f"{API_PREFIX}/workspaces/{other_workspace.id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_workspace_name(auth_client, test_user, test_workspace):
    """Test updating workspace name as owner."""
    response = await auth_client.patch(
        f"{API_PREFIX}/workspaces/{test_workspace.id}",
        json={"name": "Updated Workspace Name"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Workspace Name"


@pytest.mark.asyncio
async def test_update_workspace_visibility(auth_client, test_user, test_workspace):
    """Test updating workspace visibility."""
    response = await auth_client.patch(
        f"{API_PREFIX}/workspaces/{test_workspace.id}",
        json={"visible_to_org": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["visible_to_org"] is True


@pytest.mark.asyncio
async def test_update_workspace_no_valid_updates(
    auth_client, test_user, test_workspace
):
    """Test that empty update returns error."""
    response = await auth_client.patch(
        f"{API_PREFIX}/workspaces/{test_workspace.id}",
        json={},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_mark_workspace_visited(auth_client, test_user, test_workspace):
    """Test marking a workspace as last visited."""
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/visit"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Workspace marked as last visited"


@pytest.mark.asyncio
async def test_delete_workspace(auth_client, test_db, test_user):
    """Test deleting a workspace as owner."""
    import uuid

    from app.models import Membership, Role, Workspace

    # Create a new workspace to delete
    workspace_to_delete = Workspace(
        id=str(uuid.uuid4()),
        name="Workspace to Delete",
    )
    test_db.add(workspace_to_delete)
    await test_db.flush()

    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        workspace_id=workspace_to_delete.id,
        role=Role.OWNER,
    )
    test_db.add(membership)
    await test_db.commit()

    response = await auth_client.delete(
        f"{API_PREFIX}/workspaces/{workspace_to_delete.id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Workspace deleted successfully"

    # Verify it's deleted
    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{workspace_to_delete.id}"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_workspace_not_owner(auth_client, test_db, test_user, second_user):
    """Test that a non-owner cannot delete a workspace."""
    import uuid

    from app.models import Membership, Role, Workspace

    # Create a workspace owned by second_user with test_user as member
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Not My Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    # Second user is owner
    owner_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(owner_membership)

    # Test user is just a member
    member_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        workspace_id=workspace.id,
        role=Role.USER,
    )
    test_db.add(member_membership)
    await test_db.commit()

    # Try to delete as test_user (who is just a member)
    response = await auth_client.delete(f"{API_PREFIX}/workspaces/{workspace.id}")
    # Should fail because test_user is not owner
    assert response.status_code in [400, 403]
