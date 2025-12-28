"""
Unit tests for LLM Provider Factory (get_llm_for_workspace).

Tests cover:
- Default/no config → Returns Groq LLM
- VibeMonitor provider → Returns Groq LLM
- OpenAI provider → Returns ChatOpenAI
- Azure OpenAI provider → Returns AzureChatOpenAI
- Gemini provider → Returns ChatGoogleGenerativeAI
- Error handling/fallback → Falls back to Groq on errors
- is_byollm_workspace helper function
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
from unittest.mock import MagicMock, patch

from app.llm.providers import (
    get_llm_for_workspace,
    is_byollm_workspace,
    _create_groq_llm,
    _create_openai_llm,
    _create_azure_openai_llm,
    _create_gemini_llm,
)
from app.models import LLMProviderConfig, LLMProvider, LLMConfigStatus


class TestGetLlmForWorkspace:
    """Tests for get_llm_for_workspace() factory function."""

    @pytest.mark.asyncio
    async def test_no_config_returns_groq(self, mock_db, mock_settings):
        """When no config exists, should return Groq LLM."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("app.llm.providers.ChatGroq") as mock_groq:
            mock_groq.return_value = MagicMock()

            await get_llm_for_workspace("workspace-123", mock_db)

            mock_groq.assert_called_once()

    @pytest.mark.asyncio
    async def test_vibemonitor_provider_returns_groq(
        self, mock_db, mock_settings, sample_workspace
    ):
        """When provider is vibemonitor, should return Groq LLM."""
        config = LLMProviderConfig(
            id=str(uuid.uuid4()),
            workspace_id=sample_workspace.id,
            provider=LLMProvider.VIBEMONITOR,
            status=LLMConfigStatus.ACTIVE,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_db.execute.return_value = mock_result

        with patch("app.llm.providers.ChatGroq") as mock_groq:
            mock_groq.return_value = MagicMock()

            await get_llm_for_workspace(sample_workspace.id, mock_db)

            mock_groq.assert_called_once()

    @pytest.mark.asyncio
    async def test_openai_provider_returns_chat_openai(
        self, mock_db, mock_settings, mock_token_processor_providers, sample_workspace
    ):
        """When provider is OpenAI, should return ChatOpenAI."""
        config = LLMProviderConfig(
            id=str(uuid.uuid4()),
            workspace_id=sample_workspace.id,
            provider=LLMProvider.OPENAI,
            model_name="gpt-4-turbo",
            config_encrypted="encrypted_config",
            status=LLMConfigStatus.ACTIVE,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_db.execute.return_value = mock_result

        with patch("app.llm.providers.ChatOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()

            await get_llm_for_workspace(sample_workspace.id, mock_db)

            mock_openai.assert_called_once()
            call_kwargs = mock_openai.call_args[1]
            assert call_kwargs["api_key"] == "test-api-key"
            assert call_kwargs["model"] == "gpt-4-turbo"

    @pytest.mark.asyncio
    async def test_azure_provider_returns_azure_chat_openai(
        self, mock_db, mock_settings, sample_workspace
    ):
        """When provider is Azure OpenAI, should return AzureChatOpenAI."""
        config = LLMProviderConfig(
            id=str(uuid.uuid4()),
            workspace_id=sample_workspace.id,
            provider=LLMProvider.AZURE_OPENAI,
            model_name="gpt-4",
            config_encrypted="encrypted_config",
            status=LLMConfigStatus.ACTIVE,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_db.execute.return_value = mock_result

        azure_config = {
            "api_key": "azure-key",
            "endpoint": "https://test.openai.azure.com/",
            "deployment_name": "gpt-4-deployment",
            "api_version": "2024-02-01",
        }

        with patch("app.llm.providers.token_processor") as mock_tp:
            mock_tp.decrypt.return_value = json.dumps(azure_config)

            with patch("app.llm.providers.AzureChatOpenAI") as mock_azure:
                mock_azure.return_value = MagicMock()

                await get_llm_for_workspace(sample_workspace.id, mock_db)

                mock_azure.assert_called_once()
                call_kwargs = mock_azure.call_args[1]
                assert call_kwargs["api_key"] == "azure-key"
                assert call_kwargs["azure_endpoint"] == "https://test.openai.azure.com/"
                assert call_kwargs["azure_deployment"] == "gpt-4-deployment"

    @pytest.mark.asyncio
    async def test_gemini_provider_returns_gemini_llm(
        self, mock_db, mock_settings, mock_token_processor_providers, sample_workspace
    ):
        """When provider is Gemini, should return ChatGoogleGenerativeAI."""
        config = LLMProviderConfig(
            id=str(uuid.uuid4()),
            workspace_id=sample_workspace.id,
            provider=LLMProvider.GEMINI,
            model_name="gemini-1.5-pro",
            config_encrypted="encrypted_config",
            status=LLMConfigStatus.ACTIVE,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_db.execute.return_value = mock_result

        with patch("app.llm.providers.ChatGoogleGenerativeAI") as mock_gemini:
            mock_gemini.return_value = MagicMock()

            await get_llm_for_workspace(sample_workspace.id, mock_db)

            mock_gemini.assert_called_once()
            call_kwargs = mock_gemini.call_args[1]
            assert call_kwargs["google_api_key"] == "test-api-key"
            assert call_kwargs["model"] == "gemini-1.5-pro"

    @pytest.mark.asyncio
    async def test_custom_temperature_and_max_tokens(
        self, mock_db, mock_settings, sample_workspace
    ):
        """Should use custom temperature and max_tokens when provided."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("app.llm.providers.ChatGroq") as mock_groq:
            mock_groq.return_value = MagicMock()

            await get_llm_for_workspace(
                sample_workspace.id, mock_db, temperature=0.5, max_tokens=2000
            )

            call_kwargs = mock_groq.call_args[1]
            assert call_kwargs["temperature"] == 0.5
            assert call_kwargs["max_tokens"] == 2000

    @pytest.mark.asyncio
    async def test_error_falls_back_to_groq(
        self, mock_db, mock_settings, sample_workspace
    ):
        """On error creating custom LLM, should fall back to Groq."""
        config = LLMProviderConfig(
            id=str(uuid.uuid4()),
            workspace_id=sample_workspace.id,
            provider=LLMProvider.OPENAI,
            model_name="gpt-4-turbo",
            config_encrypted="encrypted_config",
            status=LLMConfigStatus.ACTIVE,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_db.execute.return_value = mock_result

        with patch("app.llm.providers.token_processor") as mock_tp:
            mock_tp.decrypt.side_effect = Exception("Decryption failed")

            with patch("app.llm.providers.ChatGroq") as mock_groq:
                mock_groq.return_value = MagicMock()

                await get_llm_for_workspace(sample_workspace.id, mock_db)

                # Should fall back to Groq
                mock_groq.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_config_encrypted_falls_back_to_groq(
        self, mock_db, mock_settings, sample_workspace
    ):
        """When config_encrypted is None (no API key), should fall back to Groq."""
        config = LLMProviderConfig(
            id=str(uuid.uuid4()),
            workspace_id=sample_workspace.id,
            provider=LLMProvider.OPENAI,
            model_name=None,  # No model specified
            config_encrypted=None,  # No encrypted config - missing API key
            status=LLMConfigStatus.ACTIVE,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_db.execute.return_value = mock_result

        # When there's no encrypted config, _create_openai_llm will fail
        # because api_key is None, so it should fall back to Groq
        with patch("app.llm.providers.ChatGroq") as mock_groq:
            mock_groq.return_value = MagicMock()

            await get_llm_for_workspace(sample_workspace.id, mock_db)

            # Should fall back to Groq since OpenAI has no API key
            mock_groq.assert_called_once()


class TestIsByollmWorkspace:
    """Tests for is_byollm_workspace() helper function."""

    @pytest.mark.asyncio
    async def test_no_config_returns_false(self, mock_db):
        """When no config exists, should return False."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await is_byollm_workspace("workspace-123", mock_db)

        assert result is False

    @pytest.mark.asyncio
    async def test_vibemonitor_returns_false(self, mock_db):
        """When provider is vibemonitor, should return False."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = LLMProvider.VIBEMONITOR
        mock_db.execute.return_value = mock_result

        result = await is_byollm_workspace("workspace-123", mock_db)

        assert result is False

    @pytest.mark.asyncio
    async def test_openai_returns_true(self, mock_db):
        """When provider is OpenAI, should return True."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = LLMProvider.OPENAI
        mock_db.execute.return_value = mock_result

        result = await is_byollm_workspace("workspace-123", mock_db)

        assert result is True

    @pytest.mark.asyncio
    async def test_azure_returns_true(self, mock_db):
        """When provider is Azure OpenAI, should return True."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = LLMProvider.AZURE_OPENAI
        mock_db.execute.return_value = mock_result

        result = await is_byollm_workspace("workspace-123", mock_db)

        assert result is True

    @pytest.mark.asyncio
    async def test_gemini_returns_true(self, mock_db):
        """When provider is Gemini, should return True."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = LLMProvider.GEMINI
        mock_db.execute.return_value = mock_result

        result = await is_byollm_workspace("workspace-123", mock_db)

        assert result is True


class TestCreateLlmFunctions:
    """Tests for individual LLM creation functions."""

    def test_create_groq_llm(self, mock_settings):
        """Should create Groq LLM with correct settings."""
        with patch("app.llm.providers.ChatGroq") as mock_groq:
            mock_groq.return_value = MagicMock()

            _create_groq_llm(0.1, 4096)

            mock_groq.assert_called_once_with(
                api_key="test-groq-key",
                model="llama-3.3-70b-versatile",
                temperature=0.1,
                max_tokens=4096,
            )

    def test_create_groq_llm_missing_key_raises(self):
        """Should raise error when GROQ_API_KEY not set."""
        with patch("app.llm.providers.settings") as mock_settings:
            mock_settings.GROQ_API_KEY = None

            with pytest.raises(ValueError, match="GROQ_API_KEY not configured"):
                _create_groq_llm(0.1, 4096)

    def test_create_openai_llm(self):
        """Should create OpenAI LLM with correct settings."""
        config = {"api_key": "sk-test-key"}

        with patch("app.llm.providers.ChatOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()

            _create_openai_llm(config, "gpt-4-turbo", 0.1, 4096)

            mock_openai.assert_called_once_with(
                api_key="sk-test-key",
                model="gpt-4-turbo",
                temperature=0.1,
                max_tokens=4096,
            )

    def test_create_openai_llm_missing_key_raises(self):
        """Should raise error when API key not in config."""
        config = {}

        with pytest.raises(ValueError, match="OpenAI API key not configured"):
            _create_openai_llm(config, "gpt-4-turbo", 0.1, 4096)

    def test_create_azure_openai_llm(self):
        """Should create Azure OpenAI LLM with correct settings."""
        config = {
            "api_key": "azure-key",
            "endpoint": "https://test.openai.azure.com/",
            "deployment_name": "gpt-4-deployment",
            "api_version": "2024-02-01",
        }

        with patch("app.llm.providers.AzureChatOpenAI") as mock_azure:
            mock_azure.return_value = MagicMock()

            _create_azure_openai_llm(config, None, 0.1, 4096)

            mock_azure.assert_called_once()
            call_kwargs = mock_azure.call_args[1]
            assert call_kwargs["api_key"] == "azure-key"
            assert call_kwargs["azure_endpoint"] == "https://test.openai.azure.com/"
            assert call_kwargs["azure_deployment"] == "gpt-4-deployment"

    def test_create_azure_openai_llm_missing_key_raises(self):
        """Should raise error when API key not in config."""
        config = {"endpoint": "https://test.openai.azure.com/"}

        with pytest.raises(ValueError, match="Azure OpenAI API key not configured"):
            _create_azure_openai_llm(config, None, 0.1, 4096)

    def test_create_azure_openai_llm_missing_endpoint_raises(self):
        """Should raise error when endpoint not in config."""
        config = {"api_key": "azure-key"}

        with pytest.raises(ValueError, match="Azure OpenAI endpoint not configured"):
            _create_azure_openai_llm(config, None, 0.1, 4096)

    def test_create_azure_openai_llm_missing_deployment_raises(self):
        """Should raise error when deployment name not in config."""
        config = {
            "api_key": "azure-key",
            "endpoint": "https://test.openai.azure.com/",
        }

        with pytest.raises(
            ValueError, match="Azure OpenAI deployment name not configured"
        ):
            _create_azure_openai_llm(config, None, 0.1, 4096)

    def test_create_gemini_llm(self):
        """Should create Gemini LLM with correct settings."""
        config = {"api_key": "gemini-key"}

        with patch("app.llm.providers.ChatGoogleGenerativeAI") as mock_gemini:
            mock_gemini.return_value = MagicMock()

            _create_gemini_llm(config, "gemini-1.5-pro", 0.1, 4096)

            mock_gemini.assert_called_once_with(
                google_api_key="gemini-key",
                model="gemini-1.5-pro",
                temperature=0.1,
                max_output_tokens=4096,
            )

    def test_create_gemini_llm_missing_key_raises(self):
        """Should raise error when API key not in config."""
        config = {}

        with pytest.raises(ValueError, match="Gemini API key not configured"):
            _create_gemini_llm(config, "gemini-1.5-pro", 0.1, 4096)
