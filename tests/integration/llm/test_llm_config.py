"""
Integration tests for LLM config endpoints.

Tests the BYOLLM (Bring Your Own LLM) API endpoints:
- GET  /api/v1/workspaces/{workspace_id}/llm-config
- PUT  /api/v1/workspaces/{workspace_id}/llm-config
- DELETE /api/v1/workspaces/{workspace_id}/llm-config
- POST /api/v1/workspaces/{workspace_id}/llm-config/verify
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from jose import jwt

from app.core.config import settings
from app.models import Membership, Role, User, Workspace


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


async def create_test_workspace(
    db, workspace_id: str = None, name: str = None
) -> Workspace:
    """Create a test workspace in the database."""
    workspace_id = workspace_id or str(uuid.uuid4())
    name = name or f"Test Workspace {workspace_id[:8]}"
    workspace = Workspace(
        id=workspace_id,
        name=name,
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


# =============================================================================
# GET /api/v1/workspaces/{workspace_id}/llm-config Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_llm_config_unauthenticated(client):
    """Test that unauthenticated requests return 403."""
    workspace_id = str(uuid.uuid4())
    response = await client.get(f"/api/v1/workspaces/{workspace_id}/llm-config")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_llm_config_not_member(client, test_db):
    """Test that non-members cannot access workspace LLM config."""
    # Create user and workspace (no membership)
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    token = create_access_token(user.id, user.email)

    response = await client.get(
        f"/api/v1/workspaces/{workspace.id}/llm-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "not a member" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_llm_config_user_role_forbidden(client, test_db):
    """Test that USER role members cannot access LLM config (OWNER only)."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.USER)
    token = create_access_token(user.id, user.email)

    response = await client.get(
        f"/api/v1/workspaces/{workspace.id}/llm-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "owner" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_llm_config_owner_success(client, test_db):
    """Test that workspace owners can get LLM config."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.OWNER)
    token = create_access_token(user.id, user.email)

    # Mock the service to return default config
    with patch("app.llm.router.LLMConfigService.get_config") as mock_get:
        mock_get.return_value = {
            "provider": "vibemonitor",
            "model_name": None,
            "status": "active",
            "last_verified_at": None,
            "last_error": None,
            "has_custom_key": False,
            "created_at": None,
            "updated_at": None,
        }

        response = await client.get(
            f"/api/v1/workspaces/{workspace.id}/llm-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "vibemonitor"
        assert data["has_custom_key"] is False


# =============================================================================
# PUT /api/v1/workspaces/{workspace_id}/llm-config Tests
# =============================================================================


@pytest.mark.asyncio
async def test_update_llm_config_unauthenticated(client):
    """Test that unauthenticated requests return 403."""
    workspace_id = str(uuid.uuid4())
    response = await client.put(
        f"/api/v1/workspaces/{workspace_id}/llm-config",
        json={"provider": "vibemonitor"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_llm_config_openai_requires_api_key(client, test_db):
    """Test that OpenAI provider requires API key."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.OWNER)
    token = create_access_token(user.id, user.email)

    response = await client.put(
        f"/api/v1/workspaces/{workspace.id}/llm-config",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "openai"},  # Missing api_key
    )
    assert response.status_code == 400
    assert "api key is required" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_llm_config_azure_requires_all_fields(client, test_db):
    """Test that Azure OpenAI requires api_key, endpoint, and deployment_name."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.OWNER)
    token = create_access_token(user.id, user.email)

    # Missing endpoint
    response = await client.put(
        f"/api/v1/workspaces/{workspace.id}/llm-config",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "azure_openai",
            "api_key": "test-key",
            "azure_deployment_name": "gpt-4",
        },
    )
    assert response.status_code == 400
    assert "endpoint" in response.json()["detail"].lower()

    # Missing deployment_name
    response = await client.put(
        f"/api/v1/workspaces/{workspace.id}/llm-config",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "azure_openai",
            "api_key": "test-key",
            "azure_endpoint": "https://test.openai.azure.com/",
        },
    )
    assert response.status_code == 400
    assert "deployment" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_llm_config_gemini_requires_api_key(client, test_db):
    """Test that Gemini provider requires API key."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.OWNER)
    token = create_access_token(user.id, user.email)

    response = await client.put(
        f"/api/v1/workspaces/{workspace.id}/llm-config",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "gemini"},  # Missing api_key
    )
    assert response.status_code == 400
    assert "api key is required" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_llm_config_vibemonitor_success(client, test_db):
    """Test that vibemonitor provider can be set without API key."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.OWNER)
    token = create_access_token(user.id, user.email)

    with patch(
        "app.llm.router.LLMConfigService.create_or_update_config"
    ) as mock_update:
        mock_update.return_value = {
            "provider": "vibemonitor",
            "model_name": None,
            "status": "active",
            "last_verified_at": None,
            "last_error": None,
            "has_custom_key": False,
            "created_at": datetime.now(timezone.utc),
            "updated_at": None,
        }

        response = await client.put(
            f"/api/v1/workspaces/{workspace.id}/llm-config",
            headers={"Authorization": f"Bearer {token}"},
            json={"provider": "vibemonitor"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "vibemonitor"


@pytest.mark.asyncio
async def test_update_llm_config_openai_success(client, test_db):
    """Test that OpenAI provider can be set with API key."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.OWNER)
    token = create_access_token(user.id, user.email)

    with patch(
        "app.llm.router.LLMConfigService.create_or_update_config"
    ) as mock_update:
        mock_update.return_value = {
            "provider": "openai",
            "model_name": "gpt-4-turbo",
            "status": "active",
            "last_verified_at": None,
            "last_error": None,
            "has_custom_key": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": None,
        }

        response = await client.put(
            f"/api/v1/workspaces/{workspace.id}/llm-config",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "provider": "openai",
                "api_key": "sk-test-key",
                "model_name": "gpt-4-turbo",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "openai"
        assert data["has_custom_key"] is True


# =============================================================================
# DELETE /api/v1/workspaces/{workspace_id}/llm-config Tests
# =============================================================================


@pytest.mark.asyncio
async def test_delete_llm_config_unauthenticated(client):
    """Test that unauthenticated requests return 403."""
    workspace_id = str(uuid.uuid4())
    response = await client.delete(f"/api/v1/workspaces/{workspace_id}/llm-config")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_llm_config_user_role_forbidden(client, test_db):
    """Test that USER role members cannot delete LLM config."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.USER)
    token = create_access_token(user.id, user.email)

    response = await client.delete(
        f"/api/v1/workspaces/{workspace.id}/llm-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_llm_config_already_default(client, test_db):
    """Test deleting config when workspace already uses default."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.OWNER)
    token = create_access_token(user.id, user.email)

    with patch("app.llm.router.LLMConfigService.delete_config") as mock_delete:
        mock_delete.return_value = False  # No config existed

        response = await client.delete(
            f"/api/v1/workspaces/{workspace.id}/llm-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert "default" in response.json()["message"].lower()


@pytest.mark.asyncio
async def test_delete_llm_config_success(client, test_db):
    """Test successfully deleting LLM config."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.OWNER)
    token = create_access_token(user.id, user.email)

    with patch("app.llm.router.LLMConfigService.delete_config") as mock_delete:
        mock_delete.return_value = True  # Config was deleted

        response = await client.delete(
            f"/api/v1/workspaces/{workspace.id}/llm-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()


# =============================================================================
# POST /api/v1/workspaces/{workspace_id}/llm-config/verify Tests
# =============================================================================


@pytest.mark.asyncio
async def test_verify_llm_config_unauthenticated(client):
    """Test that unauthenticated requests return 403."""
    workspace_id = str(uuid.uuid4())
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/llm-config/verify",
        json={"provider": "openai", "api_key": "test-key"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_verify_llm_config_success(client, test_db):
    """Test verifying LLM config credentials."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.OWNER)
    token = create_access_token(user.id, user.email)

    with patch("app.llm.router.LLMConfigService.verify_config") as mock_verify:
        mock_verify.return_value = {
            "success": True,
            "error": None,
            "model_info": {"models": ["gpt-4", "gpt-4-turbo"]},
        }

        response = await client.post(
            f"/api/v1/workspaces/{workspace.id}/llm-config/verify",
            headers={"Authorization": f"Bearer {token}"},
            json={"provider": "openai", "api_key": "sk-test-valid-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["error"] is None


@pytest.mark.asyncio
async def test_verify_llm_config_invalid_credentials(client, test_db):
    """Test verifying invalid LLM credentials."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.OWNER)
    token = create_access_token(user.id, user.email)

    with patch("app.llm.router.LLMConfigService.verify_config") as mock_verify:
        mock_verify.return_value = {
            "success": False,
            "error": "Invalid API key",
            "model_info": None,
        }

        response = await client.post(
            f"/api/v1/workspaces/{workspace.id}/llm-config/verify",
            headers={"Authorization": f"Bearer {token}"},
            json={"provider": "openai", "api_key": "sk-invalid-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "invalid" in data["error"].lower()


@pytest.mark.asyncio
async def test_verify_llm_config_exception_handling(client, test_db):
    """Test that verification exceptions are handled gracefully."""
    user = await create_test_user(test_db)
    workspace = await create_test_workspace(test_db)
    await create_test_membership(test_db, user, workspace, role=Role.OWNER)
    token = create_access_token(user.id, user.email)

    with patch("app.llm.router.LLMConfigService.verify_config") as mock_verify:
        mock_verify.side_effect = Exception("Connection error")

        response = await client.post(
            f"/api/v1/workspaces/{workspace.id}/llm-config/verify",
            headers={"Authorization": f"Bearer {token}"},
            json={"provider": "openai", "api_key": "sk-test-key"},
        )
        assert response.status_code == 200  # Error is returned in response body
        data = response.json()
        assert data["success"] is False
        assert "verification failed" in data["error"].lower()
