"""
Service layer for environments operations.
"""

import logging
import uuid
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Environment, Membership, Role
from app.environments.schemas import EnvironmentCreate, EnvironmentUpdate

logger = logging.getLogger(__name__)


class EnvironmentService:
    """Service layer for environment operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_membership(
        self, workspace_id: str, user_id: str
    ) -> Optional[Membership]:
        """Get membership for user in workspace."""
        result = await self.db.execute(
            select(Membership).where(
                Membership.workspace_id == workspace_id,
                Membership.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _verify_membership(self, workspace_id: str, user_id: str) -> Membership:
        """Verify user is a member of the workspace."""
        membership = await self._get_membership(workspace_id, user_id)
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this workspace",
            )
        return membership

    async def _verify_owner(self, workspace_id: str, user_id: str) -> Membership:
        """Verify user is an owner of the workspace."""
        membership = await self._verify_membership(workspace_id, user_id)
        if membership.role != Role.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only workspace owners can perform this action",
            )
        return membership

    async def _get_environment_with_workspace_check(
        self, environment_id: str, user_id: str, require_owner: bool = False
    ) -> Environment:
        """Get environment and verify user has access to its workspace."""
        result = await self.db.execute(
            select(Environment)
            .options(selectinload(Environment.repository_configs))
            .where(Environment.id == environment_id)
        )
        environment = result.scalar_one_or_none()

        if not environment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Environment not found",
            )

        # Verify membership
        if require_owner:
            await self._verify_owner(environment.workspace_id, user_id)
        else:
            await self._verify_membership(environment.workspace_id, user_id)

        return environment

    async def list_environments(
        self, workspace_id: str, user_id: str
    ) -> List[Environment]:
        """List all environments for a workspace."""
        # Verify membership
        await self._verify_membership(workspace_id, user_id)

        result = await self.db.execute(
            select(Environment)
            .where(Environment.workspace_id == workspace_id)
            .order_by(Environment.created_at)
        )
        return list(result.scalars().all())

    async def get_environment(self, environment_id: str, user_id: str) -> Environment:
        """Get environment by ID with repository configs."""
        return await self._get_environment_with_workspace_check(
            environment_id, user_id, require_owner=False
        )

    async def create_environment(
        self, data: EnvironmentCreate, user_id: str
    ) -> Environment:
        """Create a new environment."""
        # Verify user is owner
        await self._verify_owner(data.workspace_id, user_id)

        # Check for duplicate name
        existing = await self.db.execute(
            select(Environment).where(
                Environment.workspace_id == data.workspace_id,
                Environment.name == data.name,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Environment with name '{data.name}' already exists in this workspace",
            )

        # If this is set as default, unset any existing default
        if data.is_default:
            await self._unset_default_environment(data.workspace_id)

        # Create environment
        environment = Environment(
            id=str(uuid.uuid4()),
            workspace_id=data.workspace_id,
            name=data.name,
            is_default=data.is_default,
            auto_discovery_enabled=data.auto_discovery_enabled,
        )

        self.db.add(environment)
        await self.db.flush()

        logger.info(
            f"Created environment '{data.name}' in workspace {data.workspace_id}"
        )
        return environment

    async def update_environment(
        self, environment_id: str, data: EnvironmentUpdate, user_id: str
    ) -> Environment:
        """Update an environment."""
        environment = await self._get_environment_with_workspace_check(
            environment_id, user_id, require_owner=True
        )

        # Check for duplicate name if name is being updated
        if data.name is not None and data.name != environment.name:
            existing = await self.db.execute(
                select(Environment).where(
                    Environment.workspace_id == environment.workspace_id,
                    Environment.name == data.name,
                    Environment.id != environment_id,
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Environment with name '{data.name}' already exists in this workspace",
                )
            environment.name = data.name

        if data.auto_discovery_enabled is not None:
            environment.auto_discovery_enabled = data.auto_discovery_enabled

        await self.db.flush()
        logger.info(f"Updated environment {environment_id}")
        return environment

    async def delete_environment(self, environment_id: str, user_id: str) -> None:
        """Delete an environment."""
        environment = await self._get_environment_with_workspace_check(
            environment_id, user_id, require_owner=True
        )

        await self.db.delete(environment)
        await self.db.flush()
        logger.info(f"Deleted environment {environment_id}")

    async def _unset_default_environment(self, workspace_id: str) -> None:
        """Unset any existing default environment in workspace."""
        result = await self.db.execute(
            select(Environment).where(
                Environment.workspace_id == workspace_id,
                Environment.is_default == True,  # noqa: E712
            )
        )
        existing_default = result.scalar_one_or_none()
        if existing_default:
            existing_default.is_default = False
            await self.db.flush()

    async def set_default_environment(
        self, environment_id: str, user_id: str
    ) -> Environment:
        """Set an environment as the default for RCA."""
        environment = await self._get_environment_with_workspace_check(
            environment_id, user_id, require_owner=True
        )

        # Unset any existing default in the same workspace
        await self._unset_default_environment(environment.workspace_id)

        # Set this environment as default
        environment.is_default = True
        await self.db.flush()

        logger.info(
            f"Set environment {environment_id} as default for workspace {environment.workspace_id}"
        )
        return environment
