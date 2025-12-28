"""
Pytest configuration and shared fixtures for all tests.
Merged from multiple feature branches.
"""

import os

# Set required environment variables BEFORE importing app modules
# This is necessary because pydantic settings are validated on import
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("CRYPTOGRAPHY_SECRET", "test-cryptography-secret-for-testing")
# Note: This is a test-only dummy value, not a real secret
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-for-unit-tests")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-api-key")
os.environ.setdefault(
    "SQS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123456789/test"
)
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "test-github-oauth-client-id")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "test-github-oauth-client-secret")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-slack-signing-secret")
os.environ.setdefault("SLACK_CLIENT_ID", "test-slack-client-id")
os.environ.setdefault("SLACK_CLIENT_SECRET", "test-slack-client-secret")
os.environ.setdefault("POSTMARK_SERVER_TOKEN", "test-postmark-token")
os.environ.setdefault("SCHEDULER_SECRET_TOKEN", "test-scheduler-token")
os.environ.setdefault("GITHUB_APP_NAME", "test-app")
os.environ.setdefault("GITHUB_APP_ID", "12345")
os.environ.setdefault("GITHUB_PRIVATE_KEY_PEM", "dGVzdC1rZXk=")  # base64 "test-key"
os.environ.setdefault("GITHUB_CLIENT_ID", "test-client-id")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-webhook-secret")

import json
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    User,
    Workspace,
    Membership,
    Role,
    LLMProviderConfig,
    LLMProvider,
    LLMConfigStatus,
    WorkspaceType as DBWorkspaceType,
)


# In-memory SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# =============================================================================
# Database Fixtures
# =============================================================================


@pytest.fixture
def mock_db():
    """Create a mock async session for unit tests."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.rollback = AsyncMock()
    return mock_session


# =============================================================================
# User Fixtures
# =============================================================================


@pytest.fixture
def sample_user():
    """Create a sample user for testing (real model instance)."""
    return User(
        id=str(uuid.uuid4()),
        name="Test User",
        email="test@example.com",
        is_verified=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_user():
    """Create a mock user (MagicMock)."""
    user = MagicMock(spec=User)
    user.id = str(uuid.uuid4())
    user.name = "Test User"
    user.email = "test@example.com"
    user.password_hash = None  # OAuth user by default
    user.is_verified = True
    user.last_visited_workspace_id = None
    user.created_at = datetime.now(timezone.utc)
    return user


@pytest.fixture
def mock_credential_user():
    """Create a mock user with password (credential-based)."""
    user = MagicMock(spec=User)
    user.id = str(uuid.uuid4())
    user.name = "Credential User"
    user.email = "credential@example.com"
    user.password_hash = "hashed_password"
    user.is_verified = True
    user.last_visited_workspace_id = None
    user.created_at = datetime.now(timezone.utc)
    return user


# =============================================================================
# Workspace Fixtures
# =============================================================================


@pytest.fixture
def sample_workspace():
    """Create a sample workspace for testing (real model instance)."""
    return Workspace(
        id=str(uuid.uuid4()),
        name="Test Workspace",
        daily_request_limit=100,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_personal_workspace():
    """Create a mock personal workspace."""
    workspace = MagicMock(spec=Workspace)
    workspace.id = str(uuid.uuid4())
    workspace.name = "Test User's Workspace"
    workspace.type = DBWorkspaceType.PERSONAL
    workspace.domain = None
    workspace.visible_to_org = False
    workspace.is_paid = False
    workspace.created_at = datetime.now(timezone.utc)
    return workspace


@pytest.fixture
def mock_team_workspace():
    """Create a mock team workspace."""
    workspace = MagicMock(spec=Workspace)
    workspace.id = str(uuid.uuid4())
    workspace.name = "Team Workspace"
    workspace.type = DBWorkspaceType.TEAM
    workspace.domain = "example.com"
    workspace.visible_to_org = True
    workspace.is_paid = False
    workspace.created_at = datetime.now(timezone.utc)
    return workspace


@pytest.fixture
def personal_workspace_type():
    """Fixture for personal workspace type."""
    return DBWorkspaceType.PERSONAL


@pytest.fixture
def team_workspace_type():
    """Fixture for team workspace type."""
    return DBWorkspaceType.TEAM


# =============================================================================
# Membership Fixtures
# =============================================================================


@pytest.fixture
def sample_membership(sample_user, sample_workspace):
    """Create a sample owner membership (real model instance)."""
    return Membership(
        id=str(uuid.uuid4()),
        user_id=sample_user.id,
        workspace_id=sample_workspace.id,
        role=Role.OWNER,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_membership_owner(mock_user, mock_personal_workspace):
    """Create a mock owner membership."""
    membership = MagicMock(spec=Membership)
    membership.id = str(uuid.uuid4())
    membership.user_id = mock_user.id
    membership.workspace_id = mock_personal_workspace.id
    membership.role = Role.OWNER
    membership.workspace = mock_personal_workspace
    membership.user = mock_user
    return membership


@pytest.fixture
def mock_membership_member(mock_user, mock_team_workspace):
    """Create a mock member membership."""
    membership = MagicMock(spec=Membership)
    membership.id = str(uuid.uuid4())
    membership.user_id = mock_user.id
    membership.workspace_id = mock_team_workspace.id
    membership.role = Role.USER
    membership.workspace = mock_team_workspace
    membership.user = mock_user
    return membership


# =============================================================================
# LLM Fixtures (BYOLLM)
# =============================================================================


@pytest.fixture
def sample_llm_config(sample_workspace):
    """Create a sample LLM config for OpenAI."""
    return LLMProviderConfig(
        id=str(uuid.uuid4()),
        workspace_id=sample_workspace.id,
        provider=LLMProvider.OPENAI,
        model_name="gpt-4-turbo",
        config_encrypted="encrypted_config_blob",
        status=LLMConfigStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_token_processor():
    """Mock the token processor for encryption/decryption."""
    with patch("app.llm.service.token_processor") as mock:
        mock.encrypt.return_value = "encrypted_value"
        mock.decrypt.return_value = json.dumps({"api_key": "test-api-key"})
        yield mock


@pytest.fixture
def mock_token_processor_providers():
    """Mock the token processor for providers module."""
    with patch("app.llm.providers.token_processor") as mock:
        mock.decrypt.return_value = json.dumps({"api_key": "test-api-key"})
        yield mock


@pytest.fixture
def mock_settings():
    """Mock settings for LLM configuration."""
    with patch("app.llm.providers.settings") as mock:
        mock.GROQ_API_KEY = "test-groq-key"
        mock.GROQ_LLM_MODEL = "llama-3.3-70b-versatile"
        mock.RCA_AGENT_TEMPERATURE = 0.1
        mock.RCA_AGENT_MAX_TOKENS = 4096
        yield mock


# =============================================================================
# Auth Fixtures
# =============================================================================


@pytest.fixture
def mock_credential_auth_service():
    """Create a mock credential auth service."""
    service = MagicMock()
    service.verify_password = MagicMock(return_value=True)
    return service
