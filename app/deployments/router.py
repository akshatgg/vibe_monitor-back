"""
API routes for deployments.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google.service import AuthService
from app.core.database import get_db
from app.deployments.schemas import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ApiKeyResponse,
    DeploymentCreate,
    DeploymentListResponse,
    DeploymentResponse,
    WebhookDeploymentCreate,
)
from app.deployments.service import DeploymentService
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deployments", tags=["deployments"])

# Initialize auth service
auth_service = AuthService()


# ==================== Webhook Endpoint ====================


@router.post(
    "/webhook",
    response_model=DeploymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Report a deployment via webhook",
    description="""
    Report a deployment from CI/CD systems. Requires workspace API key authentication.

    **Headers:**
    - `X-Workspace-Key`: Your workspace API key

    **Example curl:**
    ```bash
    curl -X POST https://api.vibemonitor.com/api/v1/deployments/webhook \\
      -H "X-Workspace-Key: <YOUR_API_KEY>" \\
      -H "Content-Type: application/json" \\
      -d '{
        "environment": "production",
        "repository": "owner/repo",
        "branch": "main",
        "commit_sha": "abc123def456..."
      }'
    ```
    """,
)
async def create_deployment_webhook(
    data: WebhookDeploymentCreate,
    x_workspace_key: str = Header(..., description="Workspace API key"),
    db: AsyncSession = Depends(get_db),
) -> DeploymentResponse:
    """Create a deployment record via webhook."""
    service = DeploymentService(db)

    # Validate API key
    workspace = await service.validate_api_key(x_workspace_key)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # Create deployment
    deployment = await service.create_deployment_from_webhook(workspace.id, data)
    await db.commit()

    return DeploymentResponse(
        id=deployment.id,
        environment_id=deployment.environment_id,
        repo_full_name=deployment.repo_full_name,
        branch=deployment.branch,
        commit_sha=deployment.commit_sha,
        status=deployment.status.value,
        source=deployment.source.value,
        deployed_at=deployment.deployed_at,
        extra_data=deployment.extra_data,
        created_at=deployment.created_at,
    )


# ==================== Workspace-scoped Endpoints ====================


@router.post(
    "/workspaces/{workspace_id}/environments/{environment_id}",
    response_model=DeploymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a deployment record",
)
async def create_deployment(
    workspace_id: str,
    environment_id: str,
    data: DeploymentCreate,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeploymentResponse:
    """Create a deployment record (manual update)."""
    service = DeploymentService(db)
    deployment = await service.create_deployment(
        workspace_id, environment_id, data, current_user.id
    )
    await db.commit()

    return DeploymentResponse(
        id=deployment.id,
        environment_id=deployment.environment_id,
        repo_full_name=deployment.repo_full_name,
        branch=deployment.branch,
        commit_sha=deployment.commit_sha,
        status=deployment.status.value,
        source=deployment.source.value,
        deployed_at=deployment.deployed_at,
        extra_data=deployment.extra_data,
        created_at=deployment.created_at,
    )


@router.get(
    "/workspaces/{workspace_id}/environments/{environment_id}",
    response_model=DeploymentListResponse,
    summary="List deployments for an environment",
)
async def list_deployments(
    workspace_id: str,
    environment_id: str,
    repo: Optional[str] = Query(None, description="Filter by repository full name"),
    limit: int = Query(50, ge=1, le=100, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeploymentListResponse:
    """List deployment history for an environment."""
    service = DeploymentService(db)
    deployments, total = await service.list_deployments(
        workspace_id, environment_id, current_user.id, repo, limit, offset
    )

    return DeploymentListResponse(
        deployments=[
            DeploymentResponse(
                id=d.id,
                environment_id=d.environment_id,
                repo_full_name=d.repo_full_name,
                branch=d.branch,
                commit_sha=d.commit_sha,
                status=d.status.value,
                source=d.source.value,
                deployed_at=d.deployed_at,
                extra_data=d.extra_data,
                created_at=d.created_at,
            )
            for d in deployments
        ],
        total=total,
    )


@router.get(
    "/workspaces/{workspace_id}/environments/{environment_id}/repos/{repo_full_name:path}/latest",
    response_model=Optional[DeploymentResponse],
    summary="Get latest deployment for a repository",
)
async def get_latest_deployment(
    workspace_id: str,
    environment_id: str,
    repo_full_name: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[DeploymentResponse]:
    """Get the latest successful deployment for a repository in an environment."""
    service = DeploymentService(db)
    deployment = await service.get_latest_deployment(
        workspace_id, environment_id, repo_full_name, current_user.id
    )

    if not deployment:
        return None

    return DeploymentResponse(
        id=deployment.id,
        environment_id=deployment.environment_id,
        repo_full_name=deployment.repo_full_name,
        branch=deployment.branch,
        commit_sha=deployment.commit_sha,
        status=deployment.status.value,
        source=deployment.source.value,
        deployed_at=deployment.deployed_at,
        extra_data=deployment.extra_data,
        created_at=deployment.created_at,
    )


# ==================== API Key Endpoints ====================


@router.post(
    "/workspaces/{workspace_id}/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key",
)
async def create_api_key(
    workspace_id: str,
    data: ApiKeyCreate,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    """
    Create a new API key for the workspace.

    **Important:** The full API key is only shown once in this response.
    Store it securely - you won't be able to retrieve it again.
    """
    service = DeploymentService(db)
    api_key, full_key = await service.create_api_key(
        workspace_id, data, current_user.id
    )
    await db.commit()

    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key=full_key,
        key_prefix=api_key.key_prefix,
        created_at=api_key.created_at,
    )


@router.get(
    "/workspaces/{workspace_id}/api-keys",
    response_model=ApiKeyListResponse,
    summary="List API keys",
)
async def list_api_keys(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyListResponse:
    """List all API keys for a workspace."""
    service = DeploymentService(db)
    api_keys = await service.list_api_keys(workspace_id, current_user.id)

    return ApiKeyListResponse(
        api_keys=[
            ApiKeyResponse(
                id=k.id,
                name=k.name,
                key_prefix=k.key_prefix,
                last_used_at=k.last_used_at,
                created_at=k.created_at,
            )
            for k in api_keys
        ]
    )


@router.delete(
    "/workspaces/{workspace_id}/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an API key",
)
async def delete_api_key(
    workspace_id: str,
    key_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an API key."""
    service = DeploymentService(db)
    await service.delete_api_key(workspace_id, key_id, current_user.id)
    await db.commit()
