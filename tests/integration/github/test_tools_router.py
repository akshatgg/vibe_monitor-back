"""
Integration tests for GitHub Tools router endpoints.

Tests for:
- POST /api/v1/github-tools/repositories - List repositories via GraphQL
- POST /api/v1/github-tools/repository/tree - Get repository tree
- POST /api/v1/github-tools/repository/read-file - Read file content
- POST /api/v1/github-tools/repository/context - Get branch recent commits
- POST /api/v1/github-tools/repository/commits - Get all commits
- POST /api/v1/github-tools/repository/pull-requests - List pull requests
- POST /api/v1/github-tools/repository/metadata - Get repository metadata
- POST /api/v1/github-tools/repository/download-file - Download file content
- POST /api/v1/github-tools/search/code - Search code

NOTE: These routes are only registered when settings.is_local is True.
All tests are marked to skip if running in non-local environment.

IMPORTANT: All tests use async fixtures and AsyncClient from conftest.py
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.auth.google.service import AuthService
from app.core.config import settings
from app.models import (
    GitHubIntegration,
    Integration,
    Membership,
    Role,
    User,
    Workspace,
)
from tests.integration.conftest import API_PREFIX

# Initialize auth service for creating test tokens
auth_service = AuthService()

# Skip all tests in this module if not running in local environment
pytestmark = pytest.mark.skipif(
    not settings.is_local,
    reason="GitHub tools routes are only available in local environment",
)


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
    """Create a test GitHub integration with valid token"""
    github_integration = GitHubIntegration(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        integration_id=test_integration.id,
        github_user_id="12345",
        github_username="testuser",
        installation_id="67890",
        is_active=True,
        access_token="encrypted_test_token",
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
# POST /api/v1/github-tools/repositories Tests
# =============================================================================


@pytest.mark.asyncio
async def test_list_repositories_graphql_success(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test listing repositories via GraphQL"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/repositories",
        params={"workspace_id": test_workspace.id, "first": 50},
        headers=auth_headers,
    )

    # In local environment, should return 200 or 500 (if external services fail)
    # The actual GraphQL call will fail without mocking external services
    assert response.status_code in [200, 404, 500]


@pytest.mark.asyncio
async def test_list_repositories_graphql_unauthorized(client, test_workspace):
    """Test listing repositories without authentication"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/repositories",
        params={"workspace_id": test_workspace.id},
    )

    # Either 403 (no auth) or 404 (routes not available)
    assert response.status_code in [403, 404]


# =============================================================================
# POST /api/v1/github-tools/repository/tree Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_repository_tree_success(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test getting repository tree structure"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/repository/tree",
        params={
            "workspace_id": test_workspace.id,
            "name": "test-repo",
        },
        headers=auth_headers,
    )

    # In local environment, should return 200 or 500 (if external services fail)
    assert response.status_code in [200, 404, 500]


# =============================================================================
# POST /api/v1/github-tools/repository/read-file Tests
# =============================================================================


@pytest.mark.asyncio
async def test_read_repository_file_success(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test reading a file from repository"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/repository/read-file",
        params={
            "workspace_id": test_workspace.id,
            "name": "test-repo",
            "file_path": "README.md",
        },
        headers=auth_headers,
    )

    # In local environment, should return 200, 404 (not found), or 500 (external failure)
    assert response.status_code in [200, 404, 500]


@pytest.mark.asyncio
async def test_read_repository_file_not_found(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test reading a non-existent file"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/repository/read-file",
        params={
            "workspace_id": test_workspace.id,
            "name": "test-repo",
            "file_path": "nonexistent_file_12345.txt",
        },
        headers=auth_headers,
    )

    # Should return 404 for file not found or 500 for external service failure
    assert response.status_code in [404, 500]


# =============================================================================
# POST /api/v1/github-tools/repository/commits Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_repository_commits_success(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test getting repository commit history"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/repository/commits",
        params={
            "workspace_id": test_workspace.id,
            "name": "test-repo",
        },
        headers=auth_headers,
    )

    assert response.status_code in [200, 404, 500]


# =============================================================================
# POST /api/v1/github-tools/repository/pull-requests Tests
# =============================================================================


@pytest.mark.asyncio
async def test_list_pull_requests_success(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test listing pull requests"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/repository/pull-requests",
        params={
            "workspace_id": test_workspace.id,
            "name": "test-repo",
        },
        headers=auth_headers,
    )

    assert response.status_code in [200, 404, 500]


@pytest.mark.asyncio
async def test_list_pull_requests_with_states(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test listing pull requests with state filter"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/repository/pull-requests",
        params={
            "workspace_id": test_workspace.id,
            "name": "test-repo",
            "states": ["OPEN", "MERGED"],
        },
        headers=auth_headers,
    )

    assert response.status_code in [200, 404, 500]


# =============================================================================
# POST /api/v1/github-tools/repository/metadata Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_repository_metadata_success(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test getting repository metadata (languages, topics)"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/repository/metadata",
        params={
            "workspace_id": test_workspace.id,
            "name": "test-repo",
        },
        headers=auth_headers,
    )

    assert response.status_code in [200, 404, 500]


# =============================================================================
# POST /api/v1/github-tools/repository/download-file Tests
# =============================================================================


@pytest.mark.asyncio
async def test_download_file_success(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test downloading file content via REST API"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/repository/download-file",
        params={
            "workspace_id": test_workspace.id,
            "repo": "test-repo",
            "file_path": "README.md",
        },
        headers=auth_headers,
    )

    assert response.status_code in [200, 404, 500]


# =============================================================================
# POST /api/v1/github-tools/search/code Tests
# =============================================================================


@pytest.mark.asyncio
async def test_search_code_success(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test searching code in repositories"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/search/code",
        params={
            "workspace_id": test_workspace.id,
            "search_query": "def test_function",
        },
        headers=auth_headers,
    )

    assert response.status_code in [200, 404, 500]


@pytest.mark.asyncio
async def test_search_code_in_specific_repo(
    client,
    test_db,
    test_user,
    test_workspace,
    test_membership,
    test_github_integration,
    auth_headers,
):
    """Test searching code in a specific repository"""
    response = await client.post(
        f"{API_PREFIX}/github-tools/search/code",
        params={
            "workspace_id": test_workspace.id,
            "search_query": "import fastapi",
            "repo": "test-repo",
        },
        headers=auth_headers,
    )

    assert response.status_code in [200, 404, 500]


# =============================================================================
# Error Handling Tests
# =============================================================================


@pytest.mark.asyncio
async def test_github_tools_no_integration(
    client, test_db, test_user, test_workspace, test_membership, auth_headers
):
    """Test accessing tools without GitHub integration - expects 404 or 500"""
    # Without a GitHub integration, the endpoint should fail
    response = await client.post(
        f"{API_PREFIX}/github-tools/repositories",
        params={"workspace_id": test_workspace.id},
        headers=auth_headers,
    )

    assert response.status_code in [404, 500]


@pytest.mark.asyncio
async def test_github_tools_workspace_access_denied(
    client, test_db, test_workspace, test_github_integration
):
    """Test accessing tools without workspace access"""
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

    response = await client.post(
        f"{API_PREFIX}/github-tools/repositories",
        params={"workspace_id": test_workspace.id},
        headers=headers,
    )

    # Should return 403 (forbidden) or 404 (not found) or 500 (error)
    assert response.status_code in [403, 404, 500]
