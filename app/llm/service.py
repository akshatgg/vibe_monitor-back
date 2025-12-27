"""
BYOLLM Service Layer

Handles business logic for LLM configuration:
- CRUD operations for LLM configs
- Provider credential verification
- Encryption/decryption of API keys
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LLMProviderConfig, LLMProvider, LLMConfigStatus, Membership, Role
from app.utils.token_processor import token_processor
from .schemas import (
    LLMConfigCreate,
    LLMConfigResponse,
    LLMVerifyRequest,
    LLMVerifyResponse,
)
from .providers import DEFAULT_MODELS


logger = logging.getLogger(__name__)


class LLMConfigService:
    """Service for managing workspace LLM configurations."""

    @staticmethod
    async def get_config(
        workspace_id: str,
        db: AsyncSession,
    ) -> Optional[LLMConfigResponse]:
        """
        Get the LLM configuration for a workspace.

        Returns None if no config exists (uses VibeMonitor default).
        """
        result = await db.execute(
            select(LLMProviderConfig).where(
                LLMProviderConfig.workspace_id == workspace_id
            )
        )
        config = result.scalar_one_or_none()

        if not config:
            # Return default config indicating VibeMonitor AI
            return LLMConfigResponse(
                provider="vibemonitor",
                model_name=DEFAULT_MODELS.get("vibemonitor"),
                status="active",
                has_custom_key=False,
            )

        return LLMConfigResponse(
            provider=config.provider.value,
            model_name=config.model_name,
            status=config.status.value,
            last_verified_at=config.last_verified_at,
            last_error=config.last_error,
            has_custom_key=bool(config.config_encrypted),
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

    @staticmethod
    async def create_or_update_config(
        workspace_id: str,
        config_data: LLMConfigCreate,
        db: AsyncSession,
    ) -> LLMConfigResponse:
        """
        Create or update the LLM configuration for a workspace.

        API keys are encrypted before storage.
        """
        # Check if config already exists
        result = await db.execute(
            select(LLMProviderConfig).where(
                LLMProviderConfig.workspace_id == workspace_id
            )
        )
        existing_config = result.scalar_one_or_none()

        # Build encrypted config blob
        encrypted_config = LLMConfigService._build_encrypted_config(config_data)

        # Map string provider to enum
        provider_enum = LLMProvider(config_data.provider)

        if existing_config:
            # Update existing config
            existing_config.provider = provider_enum
            existing_config.model_name = config_data.model_name
            existing_config.status = LLMConfigStatus.ACTIVE
            existing_config.last_error = None

            # Only update encrypted config if new key provided
            if encrypted_config:
                existing_config.config_encrypted = encrypted_config

            await db.commit()
            await db.refresh(existing_config)

            logger.info(
                f"Updated LLM config for workspace {workspace_id}: "
                f"provider={config_data.provider}"
            )

            return LLMConfigResponse(
                provider=existing_config.provider.value,
                model_name=existing_config.model_name,
                status=existing_config.status.value,
                last_verified_at=existing_config.last_verified_at,
                last_error=existing_config.last_error,
                has_custom_key=bool(existing_config.config_encrypted),
                created_at=existing_config.created_at,
                updated_at=existing_config.updated_at,
            )
        else:
            # Create new config
            new_config = LLMProviderConfig(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                provider=provider_enum,
                model_name=config_data.model_name,
                config_encrypted=encrypted_config,
                status=LLMConfigStatus.ACTIVE,
            )
            db.add(new_config)
            await db.commit()
            await db.refresh(new_config)

            logger.info(
                f"Created LLM config for workspace {workspace_id}: "
                f"provider={config_data.provider}"
            )

            return LLMConfigResponse(
                provider=new_config.provider.value,
                model_name=new_config.model_name,
                status=new_config.status.value,
                last_verified_at=new_config.last_verified_at,
                last_error=new_config.last_error,
                has_custom_key=bool(new_config.config_encrypted),
                created_at=new_config.created_at,
                updated_at=new_config.updated_at,
            )

    @staticmethod
    async def delete_config(
        workspace_id: str,
        db: AsyncSession,
    ) -> bool:
        """
        Delete the LLM configuration for a workspace (reset to VibeMonitor default).

        Returns True if config was deleted, False if no config existed.
        """
        result = await db.execute(
            select(LLMProviderConfig).where(
                LLMProviderConfig.workspace_id == workspace_id
            )
        )
        config = result.scalar_one_or_none()

        if not config:
            return False

        await db.delete(config)
        await db.commit()

        logger.info(f"Deleted LLM config for workspace {workspace_id}")
        return True

    @staticmethod
    async def verify_config(
        verify_request: LLMVerifyRequest,
    ) -> LLMVerifyResponse:
        """
        Verify LLM provider credentials by making a test API call.

        This is called before saving configuration to ensure credentials work.
        """
        try:
            if verify_request.provider == "vibemonitor":
                # VibeMonitor uses global Groq config, always valid
                return LLMVerifyResponse(
                    success=True,
                    model_info={
                        "provider": "Groq",
                        "model": DEFAULT_MODELS["vibemonitor"],
                    },
                )

            if verify_request.provider == "openai":
                return await LLMConfigService._verify_openai(verify_request)

            elif verify_request.provider == "azure_openai":
                return await LLMConfigService._verify_azure_openai(verify_request)

            elif verify_request.provider == "gemini":
                return await LLMConfigService._verify_gemini(verify_request)

            else:
                return LLMVerifyResponse(
                    success=False,
                    error=f"Unknown provider: {verify_request.provider}",
                )

        except Exception as e:
            logger.error(f"Error verifying LLM config: {e}", exc_info=True)
            return LLMVerifyResponse(
                success=False,
                error=str(e),
            )

    @staticmethod
    async def update_config_status(
        workspace_id: str,
        db: AsyncSession,
        status: LLMConfigStatus,
        error: Optional[str] = None,
    ) -> None:
        """
        Update the status of an LLM configuration.

        Called when LLM calls fail to mark config as errored.
        """
        result = await db.execute(
            select(LLMProviderConfig).where(
                LLMProviderConfig.workspace_id == workspace_id
            )
        )
        config = result.scalar_one_or_none()

        if config:
            config.status = status
            config.last_error = error
            if status == LLMConfigStatus.ACTIVE:
                config.last_verified_at = datetime.now(timezone.utc)
            await db.commit()

    @staticmethod
    def _build_encrypted_config(config_data: LLMConfigCreate) -> Optional[str]:
        """
        Build and encrypt the config blob based on provider.

        Returns None if no API key provided (for vibemonitor or partial updates).
        """
        if not config_data.api_key:
            return None

        config_dict = {}

        if config_data.provider == "openai":
            config_dict = {"api_key": config_data.api_key}

        elif config_data.provider == "azure_openai":
            config_dict = {
                "api_key": config_data.api_key,
                "endpoint": config_data.azure_endpoint,
                "api_version": config_data.azure_api_version or "2024-02-01",
                "deployment_name": config_data.azure_deployment_name,
            }

        elif config_data.provider == "gemini":
            config_dict = {"api_key": config_data.api_key}

        elif config_data.provider == "vibemonitor":
            # No config needed for vibemonitor
            return None

        # Encrypt the config
        return token_processor.encrypt(json.dumps(config_dict))

    @staticmethod
    async def _verify_openai(verify_request: LLMVerifyRequest) -> LLMVerifyResponse:
        """Verify OpenAI credentials."""
        if not verify_request.api_key:
            return LLMVerifyResponse(success=False, error="API key is required")

        try:
            from openai import OpenAI

            client = OpenAI(api_key=verify_request.api_key)
            # Simple models list call to verify API key
            models = client.models.list()
            model_count = len(list(models))

            return LLMVerifyResponse(
                success=True,
                model_info={
                    "available_models": model_count,
                    "requested_model": verify_request.model_name
                    or DEFAULT_MODELS["openai"],
                },
            )
        except Exception as e:
            return LLMVerifyResponse(success=False, error=str(e))

    @staticmethod
    async def _verify_azure_openai(
        verify_request: LLMVerifyRequest,
    ) -> LLMVerifyResponse:
        """Verify Azure OpenAI credentials."""
        if not verify_request.api_key:
            return LLMVerifyResponse(success=False, error="API key is required")
        if not verify_request.azure_endpoint:
            return LLMVerifyResponse(success=False, error="Azure endpoint is required")
        if not verify_request.azure_deployment_name:
            return LLMVerifyResponse(success=False, error="Deployment name is required")

        try:
            from openai import AzureOpenAI

            client = AzureOpenAI(
                api_key=verify_request.api_key,
                azure_endpoint=verify_request.azure_endpoint,
                api_version=verify_request.azure_api_version or "2024-02-01",
            )

            # Test with a minimal completion
            client.chat.completions.create(
                model=verify_request.azure_deployment_name,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,
            )

            return LLMVerifyResponse(
                success=True,
                model_info={
                    "deployment": verify_request.azure_deployment_name,
                    "endpoint": verify_request.azure_endpoint,
                },
            )
        except Exception as e:
            return LLMVerifyResponse(success=False, error=str(e))

    @staticmethod
    async def _verify_gemini(verify_request: LLMVerifyRequest) -> LLMVerifyResponse:
        """Verify Google Gemini credentials."""
        if not verify_request.api_key:
            return LLMVerifyResponse(success=False, error="API key is required")

        try:
            import google.generativeai as genai

            genai.configure(api_key=verify_request.api_key)
            model_name = verify_request.model_name or DEFAULT_MODELS["gemini"]
            model = genai.GenerativeModel(model_name)

            # Simple test
            model.generate_content(
                "test",
                generation_config={"max_output_tokens": 1},
            )

            return LLMVerifyResponse(
                success=True,
                model_info={"model": model_name},
            )
        except Exception as e:
            return LLMVerifyResponse(success=False, error=str(e))


async def require_workspace_owner(
    workspace_id: str,
    user_id: str,
    db: AsyncSession,
) -> bool:
    """
    Check if user is an owner of the workspace.

    Raises HTTPException if not an owner.
    """
    result = await db.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()

    if not membership:
        return False

    return membership.role == Role.OWNER
