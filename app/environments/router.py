"""
FastAPI router for environments endpoints.
"""

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.auth.services.google_auth_service import AuthService
from app.models import User
from app.environments.service import EnvironmentService
from app.environments.schemas import (
    EnvironmentCreate,
    EnvironmentUpdate,
    EnvironmentResponse,
    EnvironmentListResponse,
    EnvironmentSummaryResponse,
    EnvironmentRepositoryCreate,
    EnvironmentRepositoryUpdate,
    EnvironmentRepositoryResponse,
    EnvironmentRepositoryListResponse,
    AvailableRepositoriesResponse,
)

logger = logging.getLogger(__name__)
auth_service = AuthService()

router = APIRouter(
    prefix="/workspaces/{workspace_id}/environments", tags=["environments"]
)


@router.get("", response_model=EnvironmentListResponse)
async def list_environments(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    List all environments for a workspace.

    Requires membership in the workspace (Owner or Member).
    """
    service = EnvironmentService(db)
    environments = await service.list_environments(
        workspace_id=workspace_id,
        user_id=current_user.id,
    )
    return EnvironmentListResponse(
        environments=[
            EnvironmentSummaryResponse.model_validate(env) for env in environments
        ]
    )


@router.get("/{environment_id}", response_model=EnvironmentResponse)
async def get_environment(
    workspace_id: str,
    environment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Get a single environment with its repository configurations.

    Requires membership in the workspace (Owner or Member).
    """
    service = EnvironmentService(db)
    environment = await service.get_environment(
        environment_id=environment_id,
        user_id=current_user.id,
    )
    return EnvironmentResponse.model_validate(environment)


@router.post(
    "", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED
)
async def create_environment(
    workspace_id: str,
    request: EnvironmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Create a new environment.

    Requires Owner role in the workspace.
    """
    service = EnvironmentService(db)
    environment = await service.create_environment(
        workspace_id=workspace_id,
        data=request,
        user_id=current_user.id,
    )
    await db.commit()
    await db.refresh(environment, ["repository_configs"])
    return EnvironmentResponse.model_validate(environment)


@router.patch("/{environment_id}", response_model=EnvironmentResponse)
async def update_environment(
    workspace_id: str,
    environment_id: str,
    request: EnvironmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Update an environment (name, auto_discovery_enabled).

    Requires Owner role in the workspace.
    """
    service = EnvironmentService(db)
    environment = await service.update_environment(
        environment_id=environment_id,
        data=request,
        user_id=current_user.id,
    )
    await db.commit()
    await db.refresh(environment, ["repository_configs"])
    return EnvironmentResponse.model_validate(environment)


@router.delete("/{environment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(
    workspace_id: str,
    environment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Delete an environment.

    Requires Owner role in the workspace.
    """
    service = EnvironmentService(db)
    await service.delete_environment(
        environment_id=environment_id,
        user_id=current_user.id,
    )
    await db.commit()


@router.post("/{environment_id}/set-default", response_model=EnvironmentResponse)
async def set_default_environment(
    workspace_id: str,
    environment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Set an environment as the default for RCA.

    Only one environment per workspace can be the default.
    Any existing default will be unset.

    Requires Owner role in the workspace.
    """
    service = EnvironmentService(db)
    environment = await service.set_default_environment(
        environment_id=environment_id,
        user_id=current_user.id,
    )
    await db.commit()
    await db.refresh(environment, ["repository_configs"])
    return EnvironmentResponse.model_validate(environment)


# ==================== Repository Configuration Endpoints ====================


@router.get(
    "/{environment_id}/repositories", response_model=EnvironmentRepositoryListResponse
)
async def list_environment_repositories(
    workspace_id: str,
    environment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    List all repository configurations for an environment.

    Requires membership in the workspace (Owner or Member).
    """
    service = EnvironmentService(db)
    repositories = await service.list_environment_repositories(
        environment_id=environment_id,
        user_id=current_user.id,
    )
    return EnvironmentRepositoryListResponse(
        repositories=[
            EnvironmentRepositoryResponse.model_validate(repo) for repo in repositories
        ]
    )


@router.post(
    "/{environment_id}/repositories",
    response_model=EnvironmentRepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_repository_to_environment(
    workspace_id: str,
    environment_id: str,
    request: EnvironmentRepositoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Add a repository to an environment.

    Requires Owner role in the workspace.
    Note: Cannot enable repository without a configured branch.
    """
    service = EnvironmentService(db)
    repo_config = await service.add_repository_to_environment(
        environment_id=environment_id,
        data=request,
        user_id=current_user.id,
    )
    await db.commit()
    await db.refresh(repo_config)
    return EnvironmentRepositoryResponse.model_validate(repo_config)


@router.patch(
    "/{environment_id}/repositories/{repo_config_id}",
    response_model=EnvironmentRepositoryResponse,
)
async def update_environment_repository(
    workspace_id: str,
    environment_id: str,
    repo_config_id: str,
    request: EnvironmentRepositoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Update a repository configuration (branch, enabled status).

    Requires Owner role in the workspace.
    Note: Cannot enable repository without a configured branch.
    """
    service = EnvironmentService(db)
    repo_config = await service.update_environment_repository(
        environment_id=environment_id,
        repo_config_id=repo_config_id,
        data=request,
        user_id=current_user.id,
    )
    await db.commit()
    await db.refresh(repo_config)
    return EnvironmentRepositoryResponse.model_validate(repo_config)


@router.delete(
    "/{environment_id}/repositories/{repo_config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_repository_from_environment(
    workspace_id: str,
    environment_id: str,
    repo_config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Remove a repository from an environment.

    Requires Owner role in the workspace.
    """
    service = EnvironmentService(db)
    await service.remove_repository_from_environment(
        environment_id=environment_id,
        repo_config_id=repo_config_id,
        user_id=current_user.id,
    )
    await db.commit()


@router.get(
    "/{environment_id}/available-repositories",
    response_model=AvailableRepositoriesResponse,
)
async def get_available_repositories(
    workspace_id: str,
    environment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    List GitHub repositories accessible to workspace but not yet in this environment.

    Requires membership in the workspace (Owner or Member).
    Requires GitHub integration to be configured.
    """
    service = EnvironmentService(db)
    available = await service.get_available_repositories(
        environment_id=environment_id,
        user_id=current_user.id,
    )
    return AvailableRepositoriesResponse(repositories=available)
