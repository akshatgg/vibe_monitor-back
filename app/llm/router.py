"""
BYOLLM (Bring Your Own LLM) API Router

Provides endpoints for managing workspace LLM configurations:
1. GET  /workspaces/{workspace_id}/llm-config          - Get current LLM config
2. PUT  /workspaces/{workspace_id}/llm-config          - Create or update LLM config
3. DELETE /workspaces/{workspace_id}/llm-config        - Reset to VibeMonitor default
4. POST /workspaces/{workspace_id}/llm-config/verify   - Verify LLM provider credentials

All endpoints require workspace OWNER role.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models import User, Membership, Role
from app.auth.services.google_auth_service import AuthService
from .schemas import (
    LLMConfigCreate,
    LLMConfigResponse,
    LLMVerifyRequest,
    LLMVerifyResponse,
)
from .service import LLMConfigService


router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["llm-config"])
auth_service = AuthService()


async def require_workspace_owner(
    workspace_id: str,
    user: User,
    db: AsyncSession,
) -> None:
    """
    Verify that the user is an OWNER of the workspace.

    LLM configuration is restricted to workspace owners only.

    Args:
        workspace_id: Workspace ID to check
        user: Authenticated user
        db: Database session

    Raises:
        HTTPException: 403 if user is not a workspace owner
    """
    membership_query = select(Membership).where(
        Membership.workspace_id == workspace_id,
        Membership.user_id == user.id,
    )

    result = await db.execute(membership_query)
    membership = result.scalar_one_or_none()

    if not membership:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied. You are not a member of workspace: {workspace_id}",
        )

    if membership.role != Role.OWNER:
        raise HTTPException(
            status_code=403,
            detail="Owner access required. Only workspace owners can configure LLM settings.",
        )


@router.get("/llm-config", response_model=LLMConfigResponse)
async def get_llm_config(
    workspace_id: str,
    user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current LLM configuration for a workspace.

    Returns the current provider, model, and status.
    API keys are NEVER returned - only indicates if a custom key is configured.

    If no custom configuration exists, returns the default VibeMonitor AI config.

    **Requires:** Workspace OWNER role
    """
    await require_workspace_owner(workspace_id, user, db)

    try:
        config = await LLMConfigService.get_config(workspace_id, db)
        return config

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get LLM configuration: {str(e)}",
        )


@router.put("/llm-config", response_model=LLMConfigResponse, status_code=200)
async def update_llm_config(
    workspace_id: str,
    request: LLMConfigCreate,
    user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create or update the LLM configuration for a workspace.

    **Providers:**
    - `vibemonitor`: Default VibeMonitor AI (no API key needed)
    - `openai`: OpenAI API (requires api_key)
    - `azure_openai`: Azure OpenAI (requires api_key, azure_endpoint, azure_deployment_name)
    - `gemini`: Google Gemini (requires api_key)

    **Rate Limiting:**
    - VibeMonitor AI users are subject to workspace rate limits
    - BYOLLM users (OpenAI, Azure, Gemini) have NO rate limits

    API keys are encrypted before storage and NEVER returned in responses.

    **Requires:** Workspace OWNER role
    """
    await require_workspace_owner(workspace_id, user, db)

    # Validate required fields based on provider
    if request.provider == "openai" and not request.api_key:
        raise HTTPException(
            status_code=400,
            detail="API key is required for OpenAI provider",
        )

    if request.provider == "azure_openai":
        if not request.api_key:
            raise HTTPException(
                status_code=400,
                detail="API key is required for Azure OpenAI provider",
            )
        if not request.azure_endpoint:
            raise HTTPException(
                status_code=400,
                detail="Azure endpoint is required for Azure OpenAI provider",
            )
        if not request.azure_deployment_name:
            raise HTTPException(
                status_code=400,
                detail="Deployment name is required for Azure OpenAI provider",
            )

    if request.provider == "gemini" and not request.api_key:
        raise HTTPException(
            status_code=400,
            detail="API key is required for Gemini provider",
        )

    try:
        config = await LLMConfigService.create_or_update_config(
            workspace_id, request, db
        )
        return config

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update LLM configuration: {str(e)}",
        )


@router.delete("/llm-config")
async def delete_llm_config(
    workspace_id: str,
    user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete the LLM configuration for a workspace (reset to VibeMonitor default).

    After deletion, the workspace will use the default VibeMonitor AI
    and be subject to standard rate limits.

    **Requires:** Workspace OWNER role
    """
    await require_workspace_owner(workspace_id, user, db)

    try:
        deleted = await LLMConfigService.delete_config(workspace_id, db)

        if not deleted:
            # No config existed, but that's fine - workspace already uses default
            return {
                "message": "Workspace already using VibeMonitor default AI",
                "workspace_id": workspace_id,
            }

        return {
            "message": "LLM configuration deleted. Workspace now uses VibeMonitor default AI.",
            "workspace_id": workspace_id,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete LLM configuration: {str(e)}",
        )


@router.post("/llm-config/verify", response_model=LLMVerifyResponse)
async def verify_llm_config(
    workspace_id: str,
    request: LLMVerifyRequest,
    user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Verify LLM provider credentials before saving.

    Makes a test API call to verify the credentials are valid and working.
    Use this endpoint before saving configuration to ensure credentials are correct.

    **Requires:** Workspace OWNER role
    """
    await require_workspace_owner(workspace_id, user, db)

    try:
        result = await LLMConfigService.verify_config(request)
        return result

    except Exception as e:
        return LLMVerifyResponse(
            success=False,
            error=f"Verification failed: {str(e)}",
        )
