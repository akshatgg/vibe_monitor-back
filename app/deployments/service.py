"""
Service layer for deployments operations.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deployments.schemas import (
    ApiKeyCreate,
    DeploymentCreate,
    WebhookDeploymentCreate,
)
from app.models import (
    Deployment,
    DeploymentSource,
    DeploymentStatus,
    Environment,
    Membership,
    Role,
    Workspace,
    WorkspaceApiKey,
)

logger = logging.getLogger(__name__)


class DeploymentService:
    """Service layer for deployment operations."""

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

    async def _get_environment(
        self, environment_id: str, workspace_id: str
    ) -> Environment:
        """Get environment by ID and verify it belongs to workspace."""
        result = await self.db.execute(
            select(Environment).where(
                Environment.id == environment_id,
                Environment.workspace_id == workspace_id,
            )
        )
        environment = result.scalar_one_or_none()
        if not environment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Environment not found",
            )
        return environment

    async def _get_environment_by_name(
        self, name: str, workspace_id: str
    ) -> Optional[Environment]:
        """Get environment by name within a workspace."""
        result = await self.db.execute(
            select(Environment).where(
                Environment.name == name,
                Environment.workspace_id == workspace_id,
            )
        )
        return result.scalar_one_or_none()

    # ==================== Deployment Methods ====================

    async def create_deployment(
        self,
        workspace_id: str,
        environment_id: str,
        data: DeploymentCreate,
        user_id: str,
    ) -> Deployment:
        """Create a new deployment record (manual)."""
        # Verify user has access
        await self._verify_membership(workspace_id, user_id)

        # Verify environment exists and belongs to workspace
        await self._get_environment(environment_id, workspace_id)

        # Create deployment
        deployment = Deployment(
            id=str(uuid.uuid4()),
            environment_id=environment_id,
            repo_full_name=data.repo_full_name,
            branch=data.branch,
            commit_sha=data.commit_sha,
            status=data.status,
            source=data.source,
            deployed_at=data.deployed_at or datetime.now(timezone.utc),
            extra_data=data.extra_data,
        )

        self.db.add(deployment)
        await self.db.flush()

        logger.info(
            f"Created deployment for {data.repo_full_name} in environment {environment_id}"
        )
        return deployment

    async def create_deployment_from_webhook(
        self, workspace_id: str, data: WebhookDeploymentCreate
    ) -> Deployment:
        """Create a deployment record from webhook (no user auth, uses API key)."""
        # Find environment by name or ID
        environment = await self._get_environment_by_name(
            data.environment, workspace_id
        )
        if not environment:
            # Try by ID
            result = await self.db.execute(
                select(Environment).where(
                    Environment.id == data.environment,
                    Environment.workspace_id == workspace_id,
                )
            )
            environment = result.scalar_one_or_none()

        if not environment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Environment '{data.environment}' not found in this workspace",
            )

        # Parse status
        try:
            deployment_status = DeploymentStatus(data.status or "success")
        except ValueError:
            deployment_status = DeploymentStatus.SUCCESS

        # Parse source
        try:
            deployment_source = DeploymentSource(data.source or "webhook")
        except ValueError:
            deployment_source = DeploymentSource.WEBHOOK

        # Create deployment
        deployment = Deployment(
            id=str(uuid.uuid4()),
            environment_id=environment.id,
            repo_full_name=data.repository,
            branch=data.branch,
            commit_sha=data.commit_sha,
            status=deployment_status,
            source=deployment_source,
            deployed_at=data.deployed_at or datetime.now(timezone.utc),
            extra_data=data.metadata,
        )

        self.db.add(deployment)
        await self.db.flush()

        logger.info(
            f"Created deployment from webhook for {data.repository} "
            f"in environment {environment.name} ({environment.id})"
        )
        return deployment

    async def get_latest_deployment(
        self,
        workspace_id: str,
        environment_id: str,
        repo_full_name: str,
        user_id: str,
    ) -> Optional[Deployment]:
        """Get the latest successful deployment for a repo in an environment."""
        # Verify user has access
        await self._verify_membership(workspace_id, user_id)

        # Verify environment exists
        await self._get_environment(environment_id, workspace_id)

        # Get latest successful deployment
        result = await self.db.execute(
            select(Deployment)
            .where(
                Deployment.environment_id == environment_id,
                Deployment.repo_full_name == repo_full_name,
                Deployment.status == DeploymentStatus.SUCCESS,
            )
            .order_by(Deployment.deployed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_deployments(
        self,
        workspace_id: str,
        environment_id: str,
        user_id: str,
        repo_full_name: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[Deployment], int]:
        """List deployments for an environment."""
        # Verify user has access
        await self._verify_membership(workspace_id, user_id)

        # Verify environment exists
        await self._get_environment(environment_id, workspace_id)

        # Build query
        query = select(Deployment).where(Deployment.environment_id == environment_id)
        if repo_full_name:
            query = query.where(Deployment.repo_full_name == repo_full_name)

        # Get total count
        count_result = await self.db.execute(query.with_only_columns(Deployment.id))
        total = len(count_result.scalars().all())

        # Get paginated results
        query = (
            query.order_by(Deployment.deployed_at.desc()).limit(limit).offset(offset)
        )
        result = await self.db.execute(query)
        deployments = list(result.scalars().all())

        return deployments, total

    # ==================== API Key Methods ====================

    @staticmethod
    def _hash_key(key: str) -> str:
        """Hash an API key using SHA-256."""
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def _generate_key() -> tuple[str, str]:
        """Generate a new API key. Returns (full_key, prefix)."""
        key = f"vm_{secrets.token_urlsafe(32)}"
        prefix = key[:8]
        return key, prefix

    async def create_api_key(
        self, workspace_id: str, data: ApiKeyCreate, user_id: str
    ) -> tuple[WorkspaceApiKey, str]:
        """Create a new API key. Returns (api_key_record, full_key)."""
        # Verify user is owner
        await self._verify_owner(workspace_id, user_id)

        # Generate key
        full_key, prefix = self._generate_key()
        key_hash = self._hash_key(full_key)

        # Create record
        api_key = WorkspaceApiKey(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            key_hash=key_hash,
            key_prefix=prefix,
            name=data.name,
        )

        self.db.add(api_key)
        await self.db.flush()

        logger.info(f"Created API key '{data.name}' for workspace {workspace_id}")
        return api_key, full_key

    async def list_api_keys(
        self, workspace_id: str, user_id: str
    ) -> List[WorkspaceApiKey]:
        """List API keys for a workspace."""
        # Verify user is owner
        await self._verify_owner(workspace_id, user_id)

        result = await self.db.execute(
            select(WorkspaceApiKey)
            .where(WorkspaceApiKey.workspace_id == workspace_id)
            .order_by(WorkspaceApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete_api_key(
        self, workspace_id: str, key_id: str, user_id: str
    ) -> None:
        """Delete an API key."""
        # Verify user is owner
        await self._verify_owner(workspace_id, user_id)

        # Get the key
        result = await self.db.execute(
            select(WorkspaceApiKey).where(
                WorkspaceApiKey.id == key_id,
                WorkspaceApiKey.workspace_id == workspace_id,
            )
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found",
            )

        await self.db.delete(api_key)
        await self.db.flush()

        logger.info(f"Deleted API key {key_id} from workspace {workspace_id}")

    async def validate_api_key(self, key: str) -> Optional[Workspace]:
        """Validate an API key and return the associated workspace."""
        key_hash = self._hash_key(key)

        result = await self.db.execute(
            select(WorkspaceApiKey).where(WorkspaceApiKey.key_hash == key_hash)
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            return None

        # Update last_used_at
        api_key.last_used_at = datetime.now(timezone.utc)
        await self.db.flush()

        # Get workspace
        result = await self.db.execute(
            select(Workspace).where(Workspace.id == api_key.workspace_id)
        )
        return result.scalar_one_or_none()
