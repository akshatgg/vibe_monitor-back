"""
Pytest configuration and shared fixtures for BYOLLM tests.
"""

import os

# Set required environment variables BEFORE importing app modules
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("CRYPTOGRAPHY_SECRET", "test-cryptography-secret-for-testing")
# Note: This is a test-only dummy value, not a real secret
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-for-unit-tests")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault(
    "SQS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123456789/test"
)
os.environ.setdefault("AWS_REGION", "us-east-1")

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
)


# In-memory SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


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


@pytest.fixture
def sample_user():
    """Create a sample user for testing."""
    return User(
        id=str(uuid.uuid4()),
        name="Test User",
        email="test@example.com",
        is_verified=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_workspace():
    """Create a sample workspace for testing."""
    return Workspace(
        id=str(uuid.uuid4()),
        name="Test Workspace",
        daily_request_limit=100,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_membership(sample_user, sample_workspace):
    """Create a sample owner membership."""
    return Membership(
        id=str(uuid.uuid4()),
        user_id=sample_user.id,
        workspace_id=sample_workspace.id,
        role=Role.OWNER,
        created_at=datetime.now(timezone.utc),
    )


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
