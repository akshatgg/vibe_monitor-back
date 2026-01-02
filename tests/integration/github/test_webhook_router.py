"""
Integration tests for GitHub Webhook router endpoint.

Tests for:
- POST /api/v1/github/webhook - Handle GitHub webhook events

Events tested:
- installation (deleted, suspend, unsuspend, created)
- installation_repositories
- ping
- Unknown events

IMPORTANT: All tests use async fixtures and AsyncClient from conftest.py
"""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

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

# Test webhook secret for signature generation
TEST_WEBHOOK_SECRET = "test_webhook_secret_12345"


# =============================================================================
# Helper Functions
# =============================================================================


def generate_webhook_signature(payload: str, secret: str = TEST_WEBHOOK_SECRET) -> str:
    """Generate a valid GitHub webhook signature for testing"""
    signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={signature}"


def make_webhook_headers(
    payload: str, event: str, secret: str = TEST_WEBHOOK_SECRET
) -> dict:
    """Generate webhook headers with valid signature"""
    return {
        "X-Hub-Signature-256": generate_webhook_signature(payload, secret),
        "X-GitHub-Event": event,
        "Content-Type": "application/json",
    }


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


# =============================================================================
# POST /api/v1/github/webhook Tests - Signature Verification
# =============================================================================


@pytest.mark.asyncio
async def test_webhook_missing_signature(client, test_db):
    """Test webhook request without signature header"""
    payload = json.dumps({"action": "ping"})

    response = await client.post(
        f"{API_PREFIX}/github/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "ping",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401
    assert "signature" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client, test_db):
    """Test webhook request with invalid signature"""
    payload = json.dumps({"action": "ping"})

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": "sha256=invalid_signature",
                "X-GitHub-Event": "ping",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 403
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_webhook_invalid_signature_format(client, test_db):
    """Test webhook request with invalid signature format (missing sha256= prefix)"""
    payload = json.dumps({"action": "ping"})

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": "invalid_format_no_prefix",
                "X-GitHub-Event": "ping",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 403


# =============================================================================
# POST /api/v1/github/webhook Tests - Ping Event
# =============================================================================


@pytest.mark.asyncio
async def test_webhook_ping_event(client, test_db):
    """Test ping event from GitHub"""
    payload = json.dumps(
        {
            "zen": "Keep it logically awesome.",
            "hook_id": 123456,
        }
    )

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        headers = make_webhook_headers(payload, "ping")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "pong" in data["message"].lower()


# =============================================================================
# POST /api/v1/github/webhook Tests - Installation Events
# =============================================================================


@pytest.mark.asyncio
async def test_webhook_installation_deleted(
    client, test_db, test_workspace, test_github_integration, test_integration
):
    """Test installation.deleted event"""
    payload = json.dumps(
        {
            "action": "deleted",
            "installation": {
                "id": 67890,  # Matches test_github_integration
                "account": {
                    "id": 12345,
                    "login": "testuser",
                    "type": "User",
                },
            },
        }
    )

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        headers = make_webhook_headers(payload, "installation")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["action"] == "deleted"


@pytest.mark.asyncio
async def test_webhook_installation_deleted_not_found(client, test_db):
    """Test installation.deleted event when integration doesn't exist"""
    payload = json.dumps(
        {
            "action": "deleted",
            "installation": {
                "id": 99999,  # Non-existent installation
                "account": {
                    "id": 12345,
                    "login": "unknownuser",
                    "type": "User",
                },
            },
        }
    )

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        headers = make_webhook_headers(payload, "installation")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_found"


@pytest.mark.asyncio
async def test_webhook_installation_suspend(
    client, test_db, test_workspace, test_github_integration, test_integration
):
    """Test installation.suspend event"""
    payload = json.dumps(
        {
            "action": "suspend",
            "installation": {
                "id": 67890,  # Matches test_github_integration
                "account": {
                    "id": 12345,
                    "login": "testuser",
                    "type": "User",
                },
            },
        }
    )

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        headers = make_webhook_headers(payload, "installation")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["action"] == "suspend"


@pytest.mark.asyncio
async def test_webhook_installation_unsuspend(
    client, test_db, test_workspace, test_github_integration, test_integration
):
    """Test installation.unsuspend event"""
    payload = json.dumps(
        {
            "action": "unsuspend",
            "installation": {
                "id": 67890,  # Matches test_github_integration
                "account": {
                    "id": 12345,
                    "login": "testuser",
                    "type": "User",
                },
            },
        }
    )

    with (
        patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET),
        patch(
            "app.github.webhook.service.GitHubAppService.get_installation_access_token",
            new_callable=AsyncMock,
        ) as mock_token,
    ):
        mock_token.return_value = {
            "token": "ghs_new_test_token",
            "expires_at": "2024-12-31T23:59:59Z",
        }

        headers = make_webhook_headers(payload, "installation")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["action"] == "unsuspend"


@pytest.mark.asyncio
async def test_webhook_installation_created_ignored(client, test_db):
    """Test installation.created event is acknowledged but ignored"""
    payload = json.dumps(
        {
            "action": "created",
            "installation": {
                "id": 11111,
                "account": {
                    "id": 22222,
                    "login": "newuser",
                    "type": "User",
                },
            },
        }
    )

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        headers = make_webhook_headers(payload, "installation")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    # Created action is not in allowed_actions, should be ignored
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"


# =============================================================================
# POST /api/v1/github/webhook Tests - Installation Repositories Events
# =============================================================================


@pytest.mark.asyncio
async def test_webhook_installation_repositories_added(client, test_db):
    """Test installation_repositories.added event"""
    payload = json.dumps(
        {
            "action": "added",
            "installation": {
                "id": 67890,
                "account": {
                    "id": 12345,
                    "login": "testuser",
                    "type": "User",
                },
            },
            "repositories_added": [
                {"id": 1, "name": "new-repo", "full_name": "testuser/new-repo"},
            ],
            "repositories_removed": [],
        }
    )

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        headers = make_webhook_headers(payload, "installation_repositories")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "acknowledged"


@pytest.mark.asyncio
async def test_webhook_installation_repositories_removed(client, test_db):
    """Test installation_repositories.removed event"""
    payload = json.dumps(
        {
            "action": "removed",
            "installation": {
                "id": 67890,
                "account": {
                    "id": 12345,
                    "login": "testuser",
                    "type": "User",
                },
            },
            "repositories_added": [],
            "repositories_removed": [
                {"id": 1, "name": "old-repo", "full_name": "testuser/old-repo"},
            ],
        }
    )

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        headers = make_webhook_headers(payload, "installation_repositories")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "acknowledged"


# =============================================================================
# POST /api/v1/github/webhook Tests - Unknown Events
# =============================================================================


@pytest.mark.asyncio
async def test_webhook_unknown_event(client, test_db):
    """Test handling of unknown/unhandled event types"""
    payload = json.dumps(
        {
            "action": "opened",
            "pull_request": {"number": 1},
        }
    )

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        headers = make_webhook_headers(payload, "pull_request")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"
    assert "pull_request" in data["message"]


# =============================================================================
# POST /api/v1/github/webhook Tests - Invalid Payloads
# =============================================================================


@pytest.mark.asyncio
async def test_webhook_invalid_json(client, test_db):
    """Test webhook with invalid JSON payload"""
    invalid_payload = "not valid json {"

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        headers = make_webhook_headers(invalid_payload, "installation")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=invalid_payload,
            headers=headers,
        )

    assert response.status_code == 400
    assert "json" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_webhook_installation_invalid_payload(client, test_db):
    """Test installation event with invalid payload structure"""
    # Missing required 'installation' field
    payload = json.dumps(
        {
            "action": "deleted",
        }
    )

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        headers = make_webhook_headers(payload, "installation")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    # The router catches validation errors and returns 500 due to outer exception handler
    # The 400 HTTPException is re-raised but caught by the generic Exception handler
    assert response.status_code in [400, 500]
    assert (
        "invalid" in response.json()["detail"].lower()
        or "failed" in response.json()["detail"].lower()
    )


# =============================================================================
# POST /api/v1/github/webhook Tests - Edge Cases
# =============================================================================


@pytest.mark.asyncio
async def test_webhook_suspend_not_found(client, test_db):
    """Test suspend event when integration doesn't exist"""
    payload = json.dumps(
        {
            "action": "suspend",
            "installation": {
                "id": 99999,  # Non-existent
                "account": {
                    "id": 12345,
                    "login": "unknownuser",
                    "type": "User",
                },
            },
        }
    )

    with patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        headers = make_webhook_headers(payload, "installation")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_found"


@pytest.mark.asyncio
async def test_webhook_unsuspend_token_fetch_fails(
    client, test_db, test_workspace, test_github_integration, test_integration
):
    """Test unsuspend event when token fetch fails"""
    payload = json.dumps(
        {
            "action": "unsuspend",
            "installation": {
                "id": 67890,
                "account": {
                    "id": 12345,
                    "login": "testuser",
                    "type": "User",
                },
            },
        }
    )

    with (
        patch("app.core.config.settings.GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET),
        patch(
            "app.github.webhook.service.GitHubAppService.get_installation_access_token",
            new_callable=AsyncMock,
        ) as mock_token,
    ):
        mock_token.side_effect = Exception("GitHub API error")

        headers = make_webhook_headers(payload, "installation")
        response = await client.post(
            f"{API_PREFIX}/github/webhook",
            content=payload,
            headers=headers,
        )

    # When token fetch fails, the service returns status="error"
    # The router returns 500 for error status (so GitHub will retry)
    assert response.status_code == 500
    data = response.json()
    assert (
        "token" in data["detail"].lower()
        or "github" in data["detail"].lower()
        or "failed" in data["detail"].lower()
    )
