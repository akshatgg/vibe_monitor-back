"""
Service management business logic.
Handles CRUD operations for billable services within workspaces.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func
from typing import Optional, Tuple
import uuid
from fastapi import HTTPException

from app.models import Service, Workspace, Membership, Role
from ..schemas import (
    ServiceCreate,
    ServiceUpdate,
    ServiceResponse,
    ServiceListResponse,
    ServiceCountResponse,
    FREE_TIER_SERVICE_LIMIT,
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
        self, workspace_id: str, repository_name: Optional[str], db: AsyncSession
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolve repository name to repository_id.
        Returns (repository_id, repository_name) tuple.
        """
        if not repository_name:
            return None, None

        # For now, just store the repository_name as-is without validation.
        # A future enhancement could validate against repos accessible via
        # the GitHub integration for this workspace.
        # Return None for repository_id since we don't have a direct repo table.
        return None, repository_name

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
                status_code=400,
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

        return ServiceResponse.model_validate(new_service)

    async def list_services(
        self, workspace_id: str, user_id: str, db: AsyncSession
    ) -> ServiceListResponse:
        """
        List all services in a workspace.
        Any workspace member can view services.
        """
        # Verify user is a member
        await self._verify_member(workspace_id, user_id, db)

        # Get services
        services_query = (
            select(Service)
            .where(Service.workspace_id == workspace_id)
            .order_by(Service.created_at.desc())
        )
        result = await db.execute(services_query)
        services = result.scalars().all()

        # Get limit info
        limit = await self._get_service_limit(workspace_id, db)
        total_count = len(services)
        limit_reached = total_count >= limit

        return ServiceListResponse(
            services=[ServiceResponse.model_validate(s) for s in services],
            total_count=total_count,
            limit=limit if limit < 999999 else FREE_TIER_SERVICE_LIMIT,
            limit_reached=limit_reached,
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

        # Get service
        service_query = select(Service).where(
            Service.id == service_id,
            Service.workspace_id == workspace_id,
        )
        result = await db.execute(service_query)
        service = result.scalar_one_or_none()

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        return ServiceResponse.model_validate(service)

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
                    status_code=400,
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

        # Update enabled status if provided
        if service_data.enabled is not None:
            service.enabled = service_data.enabled

        await db.commit()
        await db.refresh(service)

        return ServiceResponse.model_validate(service)

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
