"""
Integration tests for LLM Config API Router.

Tests cover:
- GET /workspaces/{workspace_id}/llm-config - Get LLM config for workspace
- PUT /workspaces/{workspace_id}/llm-config - Create or update LLM config
- DELETE /workspaces/{workspace_id}/llm-config - Delete LLM config (reset to default)
- POST /workspaces/{workspace_id}/llm-config/verify - Verify LLM provider credentials

All endpoints require:
- Valid authentication
- Workspace OWNER role
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

import pytest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.llm.router import (
    require_workspace_owner,
    get_llm_config,
    update_llm_config,
    delete_llm_config,
    verify_llm_config,
)
from app.llm.schemas import LLMConfigCreate, LLMVerifyRequest
from app.models import Role


class TestRequireWorkspaceOwner:
    """Tests for require_workspace_owner() dependency."""

    @pytest.mark.asyncio
    async def test_owner_access_allowed(
        self, mock_db, sample_user, sample_membership, sample_workspace
    ):
        """Owner should be allowed access."""
        sample_membership.role = Role.OWNER

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_db.execute.return_value = mock_result

        # Should not raise
        await require_workspace_owner(sample_workspace.id, sample_user, mock_db)
        assert True  # No exception raised

    @pytest.mark.asyncio
    async def test_member_access_denied(
        self, mock_db, sample_user, sample_membership, sample_workspace
    ):
        """Member (non-owner) should be denied access."""
        sample_membership.role = Role.USER

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await require_workspace_owner(sample_workspace.id, sample_user, mock_db)

        assert exc_info.value.status_code == 403
        assert "Owner access required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_non_member_access_denied(
        self, mock_db, sample_user, sample_workspace
    ):
        """Non-member should be denied access."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await require_workspace_owner(sample_workspace.id, sample_user, mock_db)

        assert exc_info.value.status_code == 403
        assert "not a member" in exc_info.value.detail


class TestGetLlmConfig:
    """Tests for GET /llm/config endpoint."""

    @pytest.mark.asyncio
    async def test_get_default_config(
        self, mock_db, sample_user, sample_membership, sample_workspace
    ):
        """Should return default VibeMonitor config when no config exists."""
        sample_membership.role = Role.OWNER

        # Mock membership check
        mock_membership_result = MagicMock()
        mock_membership_result.scalar_one_or_none.return_value = sample_membership

        # Mock config check (no config)
        mock_config_result = MagicMock()
        mock_config_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_membership_result, mock_config_result]

        result = await get_llm_config(
            workspace_id=sample_workspace.id,
            user=sample_user,
            db=mock_db,
        )

        assert result.provider == "vibemonitor"
        assert result.status == "active"
        assert result.has_custom_key is False

    @pytest.mark.asyncio
    async def test_get_custom_config(
        self, mock_db, sample_user, sample_membership, sample_llm_config
    ):
        """Should return custom config when it exists."""
        sample_membership.role = Role.OWNER

        mock_membership_result = MagicMock()
        mock_membership_result.scalar_one_or_none.return_value = sample_membership

        mock_config_result = MagicMock()
        mock_config_result.scalar_one_or_none.return_value = sample_llm_config

        mock_db.execute.side_effect = [mock_membership_result, mock_config_result]

        result = await get_llm_config(
            workspace_id=sample_llm_config.workspace_id,
            user=sample_user,
            db=mock_db,
        )

        assert result.provider == "openai"
        assert result.model_name == "gpt-4-turbo"
        assert result.has_custom_key is True


class TestUpdateLlmConfig:
    """Tests for PUT /llm/config endpoint."""

    @pytest.mark.asyncio
    async def test_create_openai_config(
        self,
        mock_db,
        sample_user,
        sample_membership,
        sample_workspace,
        mock_token_processor,
    ):
        """Should create new OpenAI config."""
        sample_membership.role = Role.OWNER

        mock_membership_result = MagicMock()
        mock_membership_result.scalar_one_or_none.return_value = sample_membership

        mock_config_result = MagicMock()
        mock_config_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_membership_result, mock_config_result]

        request = LLMConfigCreate(
            provider="openai",
            model_name="gpt-4-turbo",
            api_key="sk-test-key",
        )

        result = await update_llm_config(
            workspace_id=sample_workspace.id,
            request=request,
            user=sample_user,
            db=mock_db,
        )

        assert result.provider == "openai"
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_openai_requires_api_key(
        self, mock_db, sample_user, sample_membership, sample_workspace
    ):
        """OpenAI config should require API key."""
        sample_membership.role = Role.OWNER

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_db.execute.return_value = mock_result

        request = LLMConfigCreate(
            provider="openai",
            model_name="gpt-4-turbo",
            # No api_key
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_llm_config(
                workspace_id=sample_workspace.id,
                request=request,
                user=sample_user,
                db=mock_db,
            )

        assert exc_info.value.status_code == 400
        assert "API key is required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_azure_requires_endpoint(
        self, mock_db, sample_user, sample_membership, sample_workspace
    ):
        """Azure OpenAI config should require endpoint."""
        sample_membership.role = Role.OWNER

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_db.execute.return_value = mock_result

        request = LLMConfigCreate(
            provider="azure_openai",
            api_key="azure-key",
            # No azure_endpoint
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_llm_config(
                workspace_id=sample_workspace.id,
                request=request,
                user=sample_user,
                db=mock_db,
            )

        assert exc_info.value.status_code == 400
        assert "Azure endpoint is required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_azure_requires_deployment_name(
        self, mock_db, sample_user, sample_membership, sample_workspace
    ):
        """Azure OpenAI config should require deployment name."""
        sample_membership.role = Role.OWNER

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_db.execute.return_value = mock_result

        request = LLMConfigCreate(
            provider="azure_openai",
            api_key="azure-key",
            azure_endpoint="https://test.openai.azure.com/",
            # No azure_deployment_name
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_llm_config(
                workspace_id=sample_workspace.id,
                request=request,
                user=sample_user,
                db=mock_db,
            )

        assert exc_info.value.status_code == 400
        assert "Deployment name is required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_gemini_requires_api_key(
        self, mock_db, sample_user, sample_membership, sample_workspace
    ):
        """Gemini config should require API key."""
        sample_membership.role = Role.OWNER

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_db.execute.return_value = mock_result

        request = LLMConfigCreate(
            provider="gemini",
            model_name="gemini-1.5-pro",
            # No api_key
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_llm_config(
                workspace_id=sample_workspace.id,
                request=request,
                user=sample_user,
                db=mock_db,
            )

        assert exc_info.value.status_code == 400
        assert "API key is required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_vibemonitor_no_api_key_needed(
        self,
        mock_db,
        sample_user,
        sample_membership,
        sample_workspace,
        mock_token_processor,
    ):
        """VibeMonitor config should not require API key."""
        sample_membership.role = Role.OWNER

        mock_membership_result = MagicMock()
        mock_membership_result.scalar_one_or_none.return_value = sample_membership

        mock_config_result = MagicMock()
        mock_config_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_membership_result, mock_config_result]

        request = LLMConfigCreate(
            provider="vibemonitor",
        )

        result = await update_llm_config(
            workspace_id=sample_workspace.id,
            request=request,
            user=sample_user,
            db=mock_db,
        )

        assert result.provider == "vibemonitor"


class TestDeleteLlmConfig:
    """Tests for DELETE /llm/config endpoint."""

    @pytest.mark.asyncio
    async def test_delete_existing_config(
        self, mock_db, sample_user, sample_membership, sample_llm_config
    ):
        """Should delete existing config."""
        sample_membership.role = Role.OWNER

        mock_membership_result = MagicMock()
        mock_membership_result.scalar_one_or_none.return_value = sample_membership

        mock_config_result = MagicMock()
        mock_config_result.scalar_one_or_none.return_value = sample_llm_config

        mock_db.execute.side_effect = [mock_membership_result, mock_config_result]

        result = await delete_llm_config(
            workspace_id=sample_llm_config.workspace_id,
            user=sample_user,
            db=mock_db,
        )

        assert (
            "deleted" in result["message"].lower()
            or "uses VibeMonitor" in result["message"]
        )
        mock_db.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_config(
        self, mock_db, sample_user, sample_membership, sample_workspace
    ):
        """Should return appropriate message when no config exists."""
        sample_membership.role = Role.OWNER

        mock_membership_result = MagicMock()
        mock_membership_result.scalar_one_or_none.return_value = sample_membership

        mock_config_result = MagicMock()
        mock_config_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_membership_result, mock_config_result]

        result = await delete_llm_config(
            workspace_id=sample_workspace.id,
            user=sample_user,
            db=mock_db,
        )

        assert "already using VibeMonitor" in result["message"]


class TestVerifyLlmConfig:
    """Tests for POST /llm/config/verify endpoint."""

    @pytest.mark.asyncio
    async def test_verify_vibemonitor_succeeds(
        self, mock_db, sample_user, sample_membership, sample_workspace
    ):
        """VibeMonitor verification should always succeed."""
        sample_membership.role = Role.OWNER

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_db.execute.return_value = mock_result

        request = LLMVerifyRequest(provider="vibemonitor")

        result = await verify_llm_config(
            workspace_id=sample_workspace.id,
            request=request,
            user=sample_user,
            db=mock_db,
        )

        assert result.success is True
        assert result.model_info["provider"] == "Groq"

    @pytest.mark.asyncio
    async def test_verify_openai_with_valid_key(
        self, mock_db, sample_user, sample_membership, sample_workspace
    ):
        """OpenAI verification should work with valid key."""
        sample_membership.role = Role.OWNER

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_db.execute.return_value = mock_result

        request = LLMVerifyRequest(
            provider="openai",
            api_key="sk-test-key",
            model_name="gpt-4-turbo",
        )

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.models.list.return_value = [{"id": "gpt-4"}]
            mock_openai.return_value = mock_client

            result = await verify_llm_config(
                workspace_id=sample_workspace.id,
                request=request,
                user=sample_user,
                db=mock_db,
            )

            assert result.success is True

    @pytest.mark.asyncio
    async def test_verify_openai_with_invalid_key(
        self, mock_db, sample_user, sample_membership, sample_workspace
    ):
        """OpenAI verification should fail with invalid key."""
        sample_membership.role = Role.OWNER

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_membership
        mock_db.execute.return_value = mock_result

        request = LLMVerifyRequest(
            provider="openai",
            api_key="invalid-key",
        )

        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value.models.list.side_effect = Exception(
                "Invalid API key"
            )

            result = await verify_llm_config(
                workspace_id=sample_workspace.id,
                request=request,
                user=sample_user,
                db=mock_db,
            )

            assert result.success is False
            assert "Invalid API key" in result.error


class TestRateLimitingIntegration:
    """Tests for rate limiting with BYOLLM bypass in chat router."""

    @pytest.mark.asyncio
    async def test_byollm_workspace_bypasses_rate_limit(self, mock_db):
        """BYOLLM workspace should bypass rate limiting."""
        from app.utils.rate_limiter import (
            check_rate_limit_with_byollm_bypass,
            ResourceType,
        )

        # Mock BYOLLM workspace check
        with patch("app.utils.rate_limiter.is_byollm_workspace") as mock_is_byollm:
            mock_is_byollm.return_value = True

            allowed, count, limit = await check_rate_limit_with_byollm_bypass(
                session=mock_db,
                workspace_id="workspace-123",
                resource_type=ResourceType.RCA_REQUEST,
            )

            assert allowed is True
            assert limit == -1  # Unlimited indicator

    @pytest.mark.asyncio
    async def test_non_byollm_workspace_subject_to_rate_limit(
        self, mock_db, sample_workspace
    ):
        """Non-BYOLLM workspace should be subject to rate limiting."""
        from app.utils.rate_limiter import (
            check_rate_limit_with_byollm_bypass,
            ResourceType,
        )

        # Mock non-BYOLLM workspace
        with patch("app.utils.rate_limiter.is_byollm_workspace") as mock_is_byollm:
            mock_is_byollm.return_value = False

            with patch("app.utils.rate_limiter.check_rate_limit") as mock_rate_limit:
                mock_rate_limit.return_value = (True, 1, 100)

                allowed, count, limit = await check_rate_limit_with_byollm_bypass(
                    session=mock_db,
                    workspace_id=sample_workspace.id,
                    resource_type=ResourceType.RCA_REQUEST,
                )

                assert allowed is True
                assert limit == 100  # Regular limit
