"""
Unit tests for LLMConfigService.

Tests cover:
- get_config: Get LLM config for workspace (default and custom)
- create_or_update_config: Create new and update existing configs
- delete_config: Delete config (reset to default)
- verify_config: Verify provider credentials
- _build_encrypted_config: Build encrypted config for different providers
"""

import os

# Set required environment variables BEFORE importing app modules
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("CRYPTOGRAPHY_SECRET", "test-cryptography-secret-for-testing")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault(
    "SQS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123456789/test"
)
os.environ.setdefault("AWS_REGION", "us-east-1")

import json
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.llm.service import LLMConfigService
from app.llm.schemas import LLMConfigCreate, LLMVerifyRequest
from app.models import LLMProviderConfig, LLMProvider, LLMConfigStatus


class TestGetConfig:
    """Tests for LLMConfigService.get_config()"""

    @pytest.mark.asyncio
    async def test_get_config_no_config_returns_default(self, mock_db):
        """When no config exists, should return VibeMonitor default."""
        # Mock no config found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await LLMConfigService.get_config("workspace-123", mock_db)

        assert result.provider == "vibemonitor"
        assert result.status == "active"
        assert result.has_custom_key is False

    @pytest.mark.asyncio
    async def test_get_config_with_openai_config(self, mock_db, sample_llm_config):
        """When OpenAI config exists, should return it."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_llm_config
        mock_db.execute.return_value = mock_result

        result = await LLMConfigService.get_config("workspace-123", mock_db)

        assert result.provider == "openai"
        assert result.model_name == "gpt-4-turbo"
        assert result.status == "active"
        assert result.has_custom_key is True

    @pytest.mark.asyncio
    async def test_get_config_with_azure_config(self, mock_db, sample_workspace):
        """When Azure OpenAI config exists, should return it."""
        azure_config = LLMProviderConfig(
            id=str(uuid.uuid4()),
            workspace_id=sample_workspace.id,
            provider=LLMProvider.AZURE_OPENAI,
            model_name="gpt-4",
            config_encrypted="encrypted_azure_config",
            status=LLMConfigStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = azure_config
        mock_db.execute.return_value = mock_result

        result = await LLMConfigService.get_config(sample_workspace.id, mock_db)

        assert result.provider == "azure_openai"
        assert result.has_custom_key is True

    @pytest.mark.asyncio
    async def test_get_config_with_error_status(self, mock_db, sample_workspace):
        """When config has error status, should return it."""
        error_config = LLMProviderConfig(
            id=str(uuid.uuid4()),
            workspace_id=sample_workspace.id,
            provider=LLMProvider.GEMINI,
            model_name="gemini-1.5-pro",
            config_encrypted="encrypted_config",
            status=LLMConfigStatus.ERROR,
            last_error="Invalid API key",
            created_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = error_config
        mock_db.execute.return_value = mock_result

        result = await LLMConfigService.get_config(sample_workspace.id, mock_db)

        assert result.provider == "gemini"
        assert result.status == "error"
        assert result.last_error == "Invalid API key"


class TestCreateOrUpdateConfig:
    """Tests for LLMConfigService.create_or_update_config()"""

    @pytest.mark.asyncio
    async def test_create_new_openai_config(self, mock_db, mock_token_processor):
        """Should create new OpenAI config when none exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        config_data = LLMConfigCreate(
            provider="openai",
            model_name="gpt-4-turbo",
            api_key="sk-test-key-123",
        )

        result = await LLMConfigService.create_or_update_config(
            "workspace-123", config_data, mock_db
        )

        assert result.provider == "openai"
        assert result.model_name == "gpt-4-turbo"
        assert result.has_custom_key is True
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_existing_config(
        self, mock_db, sample_llm_config, mock_token_processor
    ):
        """Should update existing config."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_llm_config
        mock_db.execute.return_value = mock_result

        config_data = LLMConfigCreate(
            provider="gemini",
            model_name="gemini-1.5-pro",
            api_key="new-gemini-key",
        )

        result = await LLMConfigService.create_or_update_config(
            sample_llm_config.workspace_id, config_data, mock_db
        )

        assert result.provider == "gemini"
        assert sample_llm_config.provider == LLMProvider.GEMINI
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_azure_config(self, mock_db, mock_token_processor):
        """Should create Azure OpenAI config with all required fields."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        config_data = LLMConfigCreate(
            provider="azure_openai",
            model_name="gpt-4",
            api_key="azure-key-123",
            azure_endpoint="https://test.openai.azure.com/",
            azure_api_version="2024-02-01",
            azure_deployment_name="gpt-4-deployment",
        )

        result = await LLMConfigService.create_or_update_config(
            "workspace-123", config_data, mock_db
        )

        assert result.provider == "azure_openai"
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_vibemonitor_config_no_key_needed(
        self, mock_db, mock_token_processor
    ):
        """VibeMonitor config should not require API key."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        config_data = LLMConfigCreate(
            provider="vibemonitor",
        )

        result = await LLMConfigService.create_or_update_config(
            "workspace-123", config_data, mock_db
        )

        assert result.provider == "vibemonitor"
        assert result.has_custom_key is False


class TestDeleteConfig:
    """Tests for LLMConfigService.delete_config()"""

    @pytest.mark.asyncio
    async def test_delete_existing_config(self, mock_db, sample_llm_config):
        """Should delete existing config and return True."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_llm_config
        mock_db.execute.return_value = mock_result

        result = await LLMConfigService.delete_config(
            sample_llm_config.workspace_id, mock_db
        )

        assert result is True
        mock_db.delete.assert_called_once_with(sample_llm_config)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_config(self, mock_db):
        """Should return False when no config exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await LLMConfigService.delete_config("workspace-123", mock_db)

        assert result is False
        mock_db.delete.assert_not_called()


class TestVerifyConfig:
    """Tests for LLMConfigService.verify_config()"""

    @pytest.mark.asyncio
    async def test_verify_vibemonitor_always_succeeds(self):
        """VibeMonitor verification should always succeed."""
        request = LLMVerifyRequest(provider="vibemonitor")

        result = await LLMConfigService.verify_config(request)

        assert result.success is True
        assert result.model_info is not None
        assert result.model_info["provider"] == "Groq"

    @pytest.mark.asyncio
    async def test_verify_openai_success(self):
        """Should verify OpenAI credentials successfully."""
        request = LLMVerifyRequest(
            provider="openai",
            api_key="sk-test-key",
            model_name="gpt-4-turbo",
        )

        with patch("app.llm.service.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.models.list.return_value = [{"id": "gpt-4"}, {"id": "gpt-3.5"}]
            mock_openai.return_value = mock_client

            result = await LLMConfigService.verify_config(request)

            assert result.success is True
            assert result.model_info is not None

    @pytest.mark.asyncio
    async def test_verify_openai_missing_key(self):
        """OpenAI verification should fail without API key."""
        request = LLMVerifyRequest(
            provider="openai",
            model_name="gpt-4-turbo",
        )

        result = await LLMConfigService.verify_config(request)

        assert result.success is False
        assert "API key is required" in result.error

    @pytest.mark.asyncio
    async def test_verify_azure_missing_endpoint(self):
        """Azure OpenAI verification should fail without endpoint."""
        request = LLMVerifyRequest(
            provider="azure_openai",
            api_key="azure-key",
        )

        result = await LLMConfigService.verify_config(request)

        assert result.success is False
        assert "endpoint is required" in result.error

    @pytest.mark.asyncio
    async def test_verify_azure_missing_deployment(self):
        """Azure OpenAI verification should fail without deployment name."""
        request = LLMVerifyRequest(
            provider="azure_openai",
            api_key="azure-key",
            azure_endpoint="https://test.openai.azure.com/",
        )

        result = await LLMConfigService.verify_config(request)

        assert result.success is False
        assert "Deployment name is required" in result.error

    @pytest.mark.asyncio
    async def test_verify_gemini_missing_key(self):
        """Gemini verification should fail without API key."""
        request = LLMVerifyRequest(
            provider="gemini",
            model_name="gemini-1.5-pro",
        )

        result = await LLMConfigService.verify_config(request)

        assert result.success is False
        assert "API key is required" in result.error

    @pytest.mark.asyncio
    async def test_verify_gemini_success(self):
        """Should verify Gemini credentials successfully."""
        request = LLMVerifyRequest(
            provider="gemini",
            api_key="test-gemini-key",
            model_name="gemini-1.5-pro",
        )

        with patch("google.generativeai.configure"):
            with patch("google.generativeai.GenerativeModel") as mock_model:
                mock_instance = MagicMock()
                mock_instance.generate_content.return_value = MagicMock()
                mock_model.return_value = mock_instance

                result = await LLMConfigService.verify_config(request)

                assert result.success is True
                assert result.model_info is not None


class TestBuildEncryptedConfig:
    """Tests for LLMConfigService._build_encrypted_config()"""

    def test_build_openai_config(self, mock_token_processor):
        """Should build encrypted config for OpenAI."""
        config_data = LLMConfigCreate(
            provider="openai",
            api_key="sk-test-key",
        )

        result = LLMConfigService._build_encrypted_config(config_data)

        assert result == "encrypted_value"
        mock_token_processor.encrypt.assert_called_once()
        call_arg = mock_token_processor.encrypt.call_args[0][0]
        assert "api_key" in json.loads(call_arg)

    def test_build_azure_config(self, mock_token_processor):
        """Should build encrypted config for Azure OpenAI with all fields."""
        config_data = LLMConfigCreate(
            provider="azure_openai",
            api_key="azure-key",
            azure_endpoint="https://test.openai.azure.com/",
            azure_api_version="2024-02-01",
            azure_deployment_name="gpt-4-deployment",
        )

        result = LLMConfigService._build_encrypted_config(config_data)

        assert result == "encrypted_value"
        call_arg = mock_token_processor.encrypt.call_args[0][0]
        parsed = json.loads(call_arg)
        assert parsed["api_key"] == "azure-key"
        assert parsed["endpoint"] == "https://test.openai.azure.com/"
        assert parsed["deployment_name"] == "gpt-4-deployment"

    def test_build_gemini_config(self, mock_token_processor):
        """Should build encrypted config for Gemini."""
        config_data = LLMConfigCreate(
            provider="gemini",
            api_key="gemini-key",
        )

        result = LLMConfigService._build_encrypted_config(config_data)

        assert result == "encrypted_value"
        call_arg = mock_token_processor.encrypt.call_args[0][0]
        assert "api_key" in json.loads(call_arg)

    def test_build_vibemonitor_config_returns_none(self):
        """VibeMonitor config should return None (no API key needed)."""
        config_data = LLMConfigCreate(
            provider="vibemonitor",
        )

        result = LLMConfigService._build_encrypted_config(config_data)

        assert result is None

    def test_build_config_without_key_returns_none(self):
        """Config without API key should return None."""
        config_data = LLMConfigCreate(
            provider="openai",
            model_name="gpt-4-turbo",
        )

        result = LLMConfigService._build_encrypted_config(config_data)

        assert result is None


class TestUpdateConfigStatus:
    """Tests for LLMConfigService.update_config_status()"""

    @pytest.mark.asyncio
    async def test_update_status_to_error(self, mock_db, sample_llm_config):
        """Should update status to error with message."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_llm_config
        mock_db.execute.return_value = mock_result

        await LLMConfigService.update_config_status(
            sample_llm_config.workspace_id,
            mock_db,
            LLMConfigStatus.ERROR,
            "API key expired",
        )

        assert sample_llm_config.status == LLMConfigStatus.ERROR
        assert sample_llm_config.last_error == "API key expired"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_status_to_active(self, mock_db, sample_llm_config):
        """Should update status to active and set verified timestamp."""
        sample_llm_config.status = LLMConfigStatus.ERROR
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_llm_config
        mock_db.execute.return_value = mock_result

        await LLMConfigService.update_config_status(
            sample_llm_config.workspace_id,
            mock_db,
            LLMConfigStatus.ACTIVE,
        )

        assert sample_llm_config.status == LLMConfigStatus.ACTIVE
        assert sample_llm_config.last_verified_at is not None

    @pytest.mark.asyncio
    async def test_update_status_no_config(self, mock_db):
        """Should handle missing config gracefully."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Should not raise error
        await LLMConfigService.update_config_status(
            "nonexistent-workspace",
            mock_db,
            LLMConfigStatus.ERROR,
        )

        # Commit should still be called (no-op)
        mock_db.commit.assert_not_called()
