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
)

logger = logging.getLogger(__name__)
auth_service = AuthService()

router = APIRouter(prefix="/environments", tags=["environments"])


@router.get("/workspace/{workspace_id}", response_model=EnvironmentListResponse)
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
        data=request,
        user_id=current_user.id,
    )
    await db.commit()
    return EnvironmentResponse.model_validate(environment)


@router.patch("/{environment_id}", response_model=EnvironmentResponse)
async def update_environment(
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
    return EnvironmentResponse.model_validate(environment)


@router.delete("/{environment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(
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
    return EnvironmentResponse.model_validate(environment)
