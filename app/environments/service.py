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

from app.environments.schemas import (
    AvailableRepository,
    EnvironmentCreate,
    EnvironmentRepositoryCreate,
    EnvironmentRepositoryUpdate,
    EnvironmentUpdate,
)
from app.models import Environment, EnvironmentRepository, Membership, Role

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
        self, workspace_id: str, data: EnvironmentCreate, user_id: str
    ) -> Environment:
        """Create a new environment."""
        # Verify user is owner
        await self._verify_owner(workspace_id, user_id)

        # Check for duplicate name
        existing = await self.db.execute(
            select(Environment).where(
                Environment.workspace_id == workspace_id,
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
            await self._unset_default_environment(workspace_id)

        # Create environment
        environment = Environment(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            name=data.name,
            is_default=data.is_default,
        )

        self.db.add(environment)
        await self.db.flush()

        logger.info(f"Created environment '{data.name}' in workspace {workspace_id}")
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

        if data.is_default is not None:
            if data.is_default:
                # Setting as default - unset any existing default first
                await self._unset_default_environment(environment.workspace_id)
                environment.is_default = True
            else:
                # Removing from default
                environment.is_default = False

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

    # ==================== Repository Configuration Methods ====================

    async def list_environment_repositories(
        self, environment_id: str, user_id: str
    ) -> List[EnvironmentRepository]:
        """List all repository configurations for an environment."""
        environment = await self._get_environment_with_workspace_check(
            environment_id, user_id, require_owner=False
        )
        return environment.repository_configs

    async def add_repository_to_environment(
        self, environment_id: str, data: EnvironmentRepositoryCreate, user_id: str
    ) -> EnvironmentRepository:
        """Add a repository to an environment."""
        # Verify environment access (owner required)
        await self._get_environment_with_workspace_check(
            environment_id, user_id, require_owner=True
        )

        # Check for duplicate repo in this environment
        existing = await self.db.execute(
            select(EnvironmentRepository).where(
                EnvironmentRepository.environment_id == environment_id,
                EnvironmentRepository.repo_full_name == data.repo_full_name,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Repository '{data.repo_full_name}' already exists in this environment",
            )

        # Create repository configuration
        repo_config = EnvironmentRepository(
            id=str(uuid.uuid4()),
            environment_id=environment_id,
            repo_full_name=data.repo_full_name,
            branch_name=data.branch_name,
            is_enabled=data.is_enabled,
        )

        self.db.add(repo_config)
        await self.db.flush()

        logger.info(
            f"Added repository '{data.repo_full_name}' to environment {environment_id}"
        )
        return repo_config

    async def update_environment_repository(
        self,
        environment_id: str,
        repo_config_id: str,
        data: EnvironmentRepositoryUpdate,
        user_id: str,
    ) -> EnvironmentRepository:
        """Update a repository configuration."""
        # Verify environment access (owner required)
        await self._get_environment_with_workspace_check(
            environment_id, user_id, require_owner=True
        )

        # Get the repository configuration
        result = await self.db.execute(
            select(EnvironmentRepository).where(
                EnvironmentRepository.id == repo_config_id,
                EnvironmentRepository.environment_id == environment_id,
            )
        )
        repo_config = result.scalar_one_or_none()

        if not repo_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Repository configuration not found",
            )

        # Update fields
        if data.branch_name is not None:
            repo_config.branch_name = data.branch_name

        if data.is_enabled is not None:
            repo_config.is_enabled = data.is_enabled

        await self.db.flush()
        logger.info(f"Updated repository configuration {repo_config_id}")
        return repo_config

    async def remove_repository_from_environment(
        self, environment_id: str, repo_config_id: str, user_id: str
    ) -> None:
        """Remove a repository from an environment."""
        # Verify environment access (owner required)
        await self._get_environment_with_workspace_check(
            environment_id, user_id, require_owner=True
        )

        # Get the repository configuration
        result = await self.db.execute(
            select(EnvironmentRepository).where(
                EnvironmentRepository.id == repo_config_id,
                EnvironmentRepository.environment_id == environment_id,
            )
        )
        repo_config = result.scalar_one_or_none()

        if not repo_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Repository configuration not found",
            )

        await self.db.delete(repo_config)
        await self.db.flush()
        logger.info(f"Removed repository configuration {repo_config_id}")

    async def get_available_repositories(
        self, environment_id: str, user_id: str
    ) -> List[AvailableRepository]:
        """
        List GitHub repositories accessible to workspace but not yet in this environment.

        Note: This requires GitHub tools service which needs workspace context.
        """
        environment = await self._get_environment_with_workspace_check(
            environment_id, user_id, require_owner=False
        )

        # Import here to avoid circular imports
        from app.github.tools.router import list_repositories_graphql

        # Get all repos from GitHub
        try:
            github_response = await list_repositories_graphql(
                workspace_id=environment.workspace_id,
                first=100,
                after=None,
                user_id=user_id,
                db=self.db,
            )
        except HTTPException as e:
            if e.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_424_FAILED_DEPENDENCY,
                    detail="GitHub integration not configured for this workspace",
                )
            raise

        # Get repos already in this environment
        existing_repos = {r.repo_full_name for r in environment.repository_configs}

        # Filter out repos that are already in the environment
        available = []
        repos_data = github_response.get("repositories", [])
        for repo in repos_data:
            full_name = repo.get("nameWithOwner")
            if full_name and full_name not in existing_repos:
                available.append(
                    AvailableRepository(
                        full_name=full_name,
                        default_branch=None,  # Would need separate API call
                        is_private=repo.get("isPrivate", False),
                    )
                )

        return available

    async def get_repository_branches(
        self, workspace_id: str, repo_full_name: str, user_id: str
    ) -> List[str]:
        """
        Get list of branches for a repository.

        Args:
            workspace_id: Workspace ID
            repo_full_name: Repository full name (owner/repo)
            user_id: User ID for authorization

        Returns:
            List of branch names
        """
        # Verify membership
        await self._verify_membership(workspace_id, user_id)

        # Import here to avoid circular imports
        from app.github.tools.service import (
            execute_github_graphql,
            get_github_integration_with_token,
        )

        # Get GitHub integration
        try:
            _, access_token = await get_github_integration_with_token(
                workspace_id, self.db
            )
        except HTTPException as e:
            if e.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_424_FAILED_DEPENDENCY,
                    detail="GitHub integration not configured for this workspace",
                )
            raise

        # Parse owner and repo from full name
        parts = repo_full_name.split("/")
        if len(parts) != 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid repository name format. Expected 'owner/repo'",
            )
        owner, repo = parts

        # GraphQL query to get branches
        query = """
        query GetBranches($owner: String!, $name: String!, $first: Int!) {
          repository(owner: $owner, name: $name) {
            refs(refPrefix: "refs/heads/", first: $first, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
              nodes {
                name
              }
            }
          }
        }
        """

        variables = {"owner": owner, "name": repo, "first": 100}

        try:
            data = await execute_github_graphql(query, variables, access_token)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to fetch branches for {repo_full_name}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch branches from GitHub",
            )

        repository_data = data.get("data", {}).get("repository", {})
        refs_data = repository_data.get("refs", {})
        nodes = refs_data.get("nodes", [])

        branches = [node.get("name") for node in nodes if node.get("name")]
        return branches
