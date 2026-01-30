"""
Service management business logic.
Handles CRUD operations for billable services within workspaces.
"""

import uuid
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func as sql_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Membership, Role, Service, Workspace
from app.teams.schemas import TeamSummaryResponse

from ..schemas import (
    FREE_TIER_SERVICE_LIMIT,
    ServiceCountResponse,
    ServiceCreate,
    ServiceListResponse,
    ServiceResponse,
    ServiceUpdate,
)
from .limit_service import limit_service


class ServiceService:
    """Business logic for service management."""

    async def _verify_owner(
        self, workspace_id: str, user_id: str, db: AsyncSession
    ) -> Membership:
        """
        Verify that the user is an owner of the workspace.
        Raises HTTPException if not.
        """
        membership_query = select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user_id,
            Membership.role == Role.OWNER,
        )
        result = await db.execute(membership_query)
        membership = result.scalar_one_or_none()

        if not membership:
            raise HTTPException(
                status_code=403,
                detail="Only workspace owners can perform this action",
            )

        return membership

    async def _verify_member(
        self, workspace_id: str, user_id: str, db: AsyncSession
    ) -> Membership:
        """
        Verify that the user is a member of the workspace.
        Raises HTTPException if not.
        """
        membership_query = select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user_id,
        )
        result = await db.execute(membership_query)
        membership = result.scalar_one_or_none()

        if not membership:
            raise HTTPException(
                status_code=403,
                detail="You are not a member of this workspace",
            )

        return membership

    async def _get_service_limit(self, workspace_id: str, db: AsyncSession) -> int:
        """
        Get the service limit for a workspace based on billing tier.
        For now, returns FREE_TIER_SERVICE_LIMIT (5).
        In the future, this will check the workspace's billing status.
        """
        workspace_query = select(Workspace).where(Workspace.id == workspace_id)
        result = await db.execute(workspace_query)
        workspace = result.scalar_one_or_none()

        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # For paid workspaces, we could return a higher limit or unlimited
        # For now, free tier limit applies to all
        if workspace.is_paid:
            # Paid tier: unlimited services (or a much higher limit)
            return 999999
        return FREE_TIER_SERVICE_LIMIT

    async def _resolve_repository(
        self, workspace_id: str, repository_name: str, db: AsyncSession
    ) -> Tuple[Optional[str], str]:
        """
        Resolve repository name to repository_id.
        Returns (repository_id, repository_name) tuple.
        Repository name is required; repository_id may be None if not linked to GitHub integration.
        """
        # For now, just store the repository_name as-is without validation.
        # A future enhancement could validate against repos accessible via
        # the GitHub integration for this workspace.
        # Return None for repository_id since we don't have a direct repo table.
        return None, repository_name

    def _format_service_response(self, service: Service) -> ServiceResponse:
        """
        Format a Service ORM object to ServiceResponse schema with team data.
        """
        service_dict = {
            "id": service.id,
            "workspace_id": service.workspace_id,
            "name": service.name,
            "repository_id": service.repository_id,
            "repository_name": service.repository_name,
            "team_id": service.team_id,
            "enabled": service.enabled,
            "created_at": service.created_at,
            "updated_at": service.updated_at,
        }

        # Add team details if service is assigned to a team
        if service.team:
            service_dict["team"] = TeamSummaryResponse(
                id=service.team.id,
                name=service.team.name,
                geography=service.team.geography,
            )
        else:
            service_dict["team"] = None

        return ServiceResponse(**service_dict)

    @staticmethod
    def _escape_like_pattern(value: str) -> str:
        """Escape LIKE/ILIKE special characters to prevent unintended wildcard matching."""
        return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

    async def get_service_count(
        self, workspace_id: str, db: AsyncSession
    ) -> ServiceCountResponse:
        """
        Get the count of services and limit information for a workspace.
        """
        # Count services
        count_query = (
            select(sql_func.count())
            .select_from(Service)
            .where(Service.workspace_id == workspace_id)
        )
        result = await db.execute(count_query)
        current_count = result.scalar() or 0

        # Get limit and paid status
        workspace_query = select(Workspace).where(Workspace.id == workspace_id)
        ws_result = await db.execute(workspace_query)
        workspace = ws_result.scalar_one_or_none()

        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        limit = await self._get_service_limit(workspace_id, db)
        can_add_more = current_count < limit

        return ServiceCountResponse(
            current_count=current_count,
            limit=limit if limit < 999999 else FREE_TIER_SERVICE_LIMIT,
            can_add_more=can_add_more,
            is_paid=workspace.is_paid,
        )

    async def validate_service_limit(
        self, workspace_id: str, db: AsyncSession
    ) -> Tuple[bool, int, int]:
        """
        Check if workspace can add more services.
        Returns (can_add: bool, current_count: int, limit: int)
        """
        count_info = await self.get_service_count(workspace_id, db)
        return (count_info.can_add_more, count_info.current_count, count_info.limit)

    async def create_service(
        self,
        workspace_id: str,
        service_data: ServiceCreate,
        user_id: str,
        db: AsyncSession,
    ) -> ServiceResponse:
        """
        Create a new service in the workspace.
        Only workspace owners can create services.
        """
        # Verify user is owner
        await self._verify_owner(workspace_id, user_id, db)

        # Check service limit - raises 402 if exceeded
        await limit_service.enforce_service_limit(db, workspace_id)

        # Check name uniqueness within workspace
        existing_query = select(Service).where(
            Service.workspace_id == workspace_id,
            Service.name == service_data.name,
        )
        result = await db.execute(existing_query)
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"A service named '{service_data.name}' already exists in this workspace",
            )

        # Resolve repository
        repository_id, repository_name = await self._resolve_repository(
            workspace_id, service_data.repository_name, db
        )

        # Create service
        service_id = str(uuid.uuid4())
        new_service = Service(
            id=service_id,
            workspace_id=workspace_id,
            name=service_data.name,
            repository_id=repository_id,
            repository_name=repository_name,
            enabled=True,
        )

        db.add(new_service)
        await db.commit()
        await db.refresh(new_service)

        return self._format_service_response(new_service)

    async def list_services(
        self,
        workspace_id: str,
        user_id: str,
        db: AsyncSession,
        search: Optional[str] = None,
        team_id: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> ServiceListResponse:
        """
        List all services in a workspace with optional search, filter, and pagination.
        Any workspace member can view services.
        """
        # Verify user is a member
        await self._verify_member(workspace_id, user_id, db)

        # Build base query
        query = (
            select(Service)
            .where(Service.workspace_id == workspace_id)
            .options(selectinload(Service.team))
        )

        # Apply search filter
        if search:
            escaped_search = self._escape_like_pattern(search)
            query = query.where(
                Service.name.ilike(f"%{escaped_search}%", escape="\\")
            )

        # Apply team filter
        if team_id:
            query = query.where(Service.team_id == team_id)

        # Count total (with filters applied)
        count_query = select(sql_func.count(Service.id)).where(
            Service.workspace_id == workspace_id
        )
        if search:
            escaped_search = self._escape_like_pattern(search)
            count_query = count_query.where(
                Service.name.ilike(f"%{escaped_search}%", escape="\\")
            )
        if team_id:
            count_query = count_query.where(Service.team_id == team_id)

        total_count_result = await db.execute(count_query)
        total_count = total_count_result.scalar() or 0

        # Apply pagination and ordering
        query = query.offset(offset).limit(limit).order_by(Service.created_at.desc())

        # Execute query
        result = await db.execute(query)
        services = result.scalars().all()

        # Get service limit (for billing limit check)
        service_limit = await self._get_service_limit(workspace_id, db)

        # Get actual count of all services (without filters) for limit check
        if search or team_id:
            all_services_count_query = select(sql_func.count(Service.id)).where(
                Service.workspace_id == workspace_id
            )
            all_count_result = await db.execute(all_services_count_query)
            all_services_count = all_count_result.scalar() or 0
        else:
            all_services_count = total_count

        limit_reached = all_services_count >= service_limit

        return ServiceListResponse(
            services=[self._format_service_response(s) for s in services],
            total_count=total_count,
            offset=offset,
            limit=limit,
            limit_reached=limit_reached,
            service_limit=service_limit if service_limit < 999999 else FREE_TIER_SERVICE_LIMIT,
        )

    async def get_service(
        self, workspace_id: str, service_id: str, user_id: str, db: AsyncSession
    ) -> ServiceResponse:
        """
        Get a single service by ID.
        Any workspace member can view.
        """
        # Verify user is a member
        await self._verify_member(workspace_id, user_id, db)

        # Get service with team relationship
        service_query = (
            select(Service)
            .where(
                Service.id == service_id,
                Service.workspace_id == workspace_id,
            )
            .options(selectinload(Service.team))
        )
        result = await db.execute(service_query)
        service = result.scalar_one_or_none()

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        return self._format_service_response(service)

    async def update_service(
        self,
        workspace_id: str,
        service_id: str,
        service_data: ServiceUpdate,
        user_id: str,
        db: AsyncSession,
    ) -> ServiceResponse:
        """
        Update an existing service.
        Only workspace owners can update services.
        """
        # Verify user is owner
        await self._verify_owner(workspace_id, user_id, db)

        # Get service
        service_query = select(Service).where(
            Service.id == service_id,
            Service.workspace_id == workspace_id,
        )
        result = await db.execute(service_query)
        service = result.scalar_one_or_none()

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        # Check name uniqueness if name is being changed
        if service_data.name and service_data.name != service.name:
            existing_query = select(Service).where(
                Service.workspace_id == workspace_id,
                Service.name == service_data.name,
                Service.id != service_id,
            )
            existing_result = await db.execute(existing_query)
            if existing_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail=f"A service named '{service_data.name}' already exists in this workspace",
                )
            service.name = service_data.name

        # Update repository if provided
        if service_data.repository_name is not None:
            repository_id, repository_name = await self._resolve_repository(
                workspace_id, service_data.repository_name, db
            )
            service.repository_id = repository_id
            service.repository_name = repository_name

        # Update team assignment if provided (None means unassign)
        if hasattr(service_data, 'team_id'):
            service.team_id = service_data.team_id

        # Update enabled status if provided
        if service_data.enabled is not None:
            service.enabled = service_data.enabled

        await db.commit()

        # Refresh service to load team relationship
        await db.refresh(service)

        service_query = (
            select(Service)
            .where(Service.id == service_id)
            .options(selectinload(Service.team))
        )
        result = await db.execute(service_query)
        refreshed_service = result.scalar_one_or_none()

        # This should never be None since we just updated it, but handle defensively
        if not refreshed_service:
            raise HTTPException(
                status_code=500,
                detail="Service not found after update - this should not happen"
            )

        return self._format_service_response(refreshed_service)

    async def delete_service(
        self, workspace_id: str, service_id: str, user_id: str, db: AsyncSession
    ) -> bool:
        """
        Delete a service.
        Only workspace owners can delete services.
        """
        # Verify user is owner
        await self._verify_owner(workspace_id, user_id, db)

        # Get service
        service_query = select(Service).where(
            Service.id == service_id,
            Service.workspace_id == workspace_id,
        )
        result = await db.execute(service_query)
        service = result.scalar_one_or_none()

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        await db.delete(service)
        await db.commit()

        return True
