"""
Service layer for team management operations.
"""

import logging
import uuid
from typing import List, Optional

from sqlalchemy import and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import select

from app.models import Membership, Role, Team, TeamMembership, User, Service

logger = logging.getLogger(__name__)


class TeamService:
    """Service for team management operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _escape_like_pattern(value: str) -> str:
        """Escape LIKE/ILIKE special characters to prevent unintended wildcard matching."""
        return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

    async def list_teams(
        self,
        workspace_id: str,
        user_id: str,
        search: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """
        List teams in a workspace with optional search and pagination.

        Args:
            workspace_id: Workspace ID
            user_id: Current user ID (for auth check)
            search: Optional search term for team names
            offset: Pagination offset
            limit: Page size (max 100)

        Returns:
            Dictionary with teams list and pagination info
        """
        # Verify user is workspace member
        is_member = await self._verify_workspace_member(workspace_id, user_id)
        if not is_member:
            raise PermissionError("User is not a member of this workspace")

        # Build query
        query = select(Team).where(Team.workspace_id == workspace_id)

        # Apply search filter
        if search:
            escaped_search = self._escape_like_pattern(search)
            query = query.where(
                Team.name.ilike(f"%{escaped_search}%", escape="\\")
            )

        # Count total
        count_query = select(func.count(Team.id)).where(Team.workspace_id == workspace_id)
        if search:
            escaped_search = self._escape_like_pattern(search)
            count_query = count_query.where(Team.name.ilike(f"%{escaped_search}%", escape="\\"))

        total_count_result = await self.db.execute(count_query)
        total_count = total_count_result.scalar() or 0

        # Apply pagination
        query = query.offset(offset).limit(limit)
        query = query.order_by(Team.created_at.desc())

        # Execute query
        result = await self.db.execute(query)
        teams = result.scalars().all()

        # Get all counts in a single query (optimized: no N+1)
        team_ids = [team.id for team in teams]
        counts_map = await self._get_counts_for_teams(team_ids)

        # Enrich with counts
        teams_with_counts = []
        for team in teams:
            team_dict = {
                "id": team.id,
                "workspace_id": team.workspace_id,
                "name": team.name,
                "geography": team.geography,
                "membership_count": counts_map.get(team.id, {}).get("membership_count", 0),
                "service_count": counts_map.get(team.id, {}).get("service_count", 0),
                "created_at": team.created_at,
                "updated_at": team.updated_at,
            }
            teams_with_counts.append(team_dict)

        return {
            "teams": teams_with_counts,
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
        }

    async def get_team_detail(
        self, workspace_id: str, team_id: str, user_id: str
    ) -> dict:
        """
        Get detailed team info with members and services.

        Args:
            workspace_id: Workspace ID
            team_id: Team ID
            user_id: Current user ID

        Returns:
            Detailed team object
        """
        # Verify user is workspace member
        is_member = await self._verify_workspace_member(workspace_id, user_id)
        if not is_member:
            raise PermissionError("User is not a member of this workspace")

        # Get team
        query = (
            select(Team)
            .where(and_(Team.id == team_id, Team.workspace_id == workspace_id))
            .options(
                selectinload(Team.memberships).selectinload(TeamMembership.user),
                selectinload(Team.services),
            )
        )
        result = await self.db.execute(query)
        team = result.scalar_one_or_none()

        if not team:
            raise ValueError(f"Team {team_id} not found in workspace {workspace_id}")

        # Format response with nested user data
        membership = []
        for tm in team.memberships:
            membership.append(
                {
                    "id": tm.id,
                    "user": {
                        "id": tm.user.id,
                        "name": tm.user.name,
                        "email": tm.user.email,
                    },
                    "created_at": tm.created_at,
                }
            )

        from .schemas import ServiceSummaryResponse

        services = [
            ServiceSummaryResponse(
                id=s.id,
                name=s.name,
                repository_name=s.repository_name,
                enabled=s.enabled,
            ).model_dump()
            for s in team.services
        ]

        return {
            "id": team.id,
            "workspace_id": team.workspace_id,
            "name": team.name,
            "geography": team.geography,
            "membership_count": len(team.memberships),
            "service_count": len(team.services),
            "membership": membership,
            "services": services,
            "created_at": team.created_at,
            "updated_at": team.updated_at,
        }

    async def _verify_workspace_member(self, workspace_id: str, user_id: str) -> bool:
        """Verify user is a member of the workspace."""
        query = select(Membership).where(
            and_(
                Membership.workspace_id == workspace_id,
                Membership.user_id == user_id,
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def _get_team_membership_count(self, team_id: str) -> int:
        """Get count of team members."""
        query = select(func.count(TeamMembership.id)).where(
            TeamMembership.team_id == team_id
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def _get_team_service_count(self, team_id: str) -> int:
        """Get count of services owned by team."""
        query = select(func.count(Service.id)).where(Service.team_id == team_id)
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def _get_counts_for_teams(self, team_ids: list) -> dict:
        """
        Get membership and service counts for multiple teams in a single query.

        Optimized approach to avoid N+1 query problem.

        Args:
            team_ids: List of team IDs

        Returns:
            Dictionary mapping team_id to {membership_count, service_count}
        """
        if not team_ids:
            return {}

        # Query membership counts
        membership_query = (
            select(
                TeamMembership.team_id,
                func.count(TeamMembership.id).label("count")
            )
            .where(TeamMembership.team_id.in_(team_ids))
            .group_by(TeamMembership.team_id)
        )

        # Query service counts
        service_query = (
            select(
                Service.team_id,
                func.count(Service.id).label("count")
            )
            .where(Service.team_id.in_(team_ids))
            .group_by(Service.team_id)
        )

        # Execute queries and build counts maps
        membership_result = await self.db.execute(membership_query)
        membership_rows = membership_result.fetchall()
        membership_counts = {row[0]: row[1] for row in membership_rows}

        service_result = await self.db.execute(service_query)
        service_rows = service_result.fetchall()
        service_counts = {row[0]: row[1] for row in service_rows}

        # Build map for all team_ids
        counts_map = {}
        for team_id in team_ids:
            counts_map[team_id] = {
                "membership_count": membership_counts.get(team_id, 0),
                "service_count": service_counts.get(team_id, 0),
            }

        return counts_map

    async def create_team(
        self,
        workspace_id: str,
        user_id: str,
        name: str,
        geography: Optional[str] = None,
        membership_ids: Optional[List[str]] = None,
    ) -> dict:
        """
        Create a new team in the workspace.

        Args:
            workspace_id: Workspace ID
            user_id: Current user ID (must be owner)
            name: Team name
            geography: Team geography (optional)
            membership_ids: Optional list of user IDs to add to team

        Returns:
            Created team object

        Raises:
            PermissionError: User is not workspace owner
            ValueError: Validation errors
        """
        try:
            # Verify user is workspace owner
            is_owner = await self._verify_workspace_owner(workspace_id, user_id)
            if not is_owner:
                raise PermissionError("Only workspace owners can create teams")

            # Validate all members exist BEFORE creating team (atomic transaction)
            valid_member_ids = []
            if membership_ids:
                for mem_user_id in membership_ids:
                    is_member = await self._verify_workspace_member(workspace_id, mem_user_id)
                    if is_member:
                        valid_member_ids.append(mem_user_id)
                    else:
                        logger.warning(
                            f"User {mem_user_id} is not a member of workspace {workspace_id}, skipping"
                        )

            # Create team and add members in single transaction
            team_id = str(uuid.uuid4())
            team = Team(
                id=team_id,
                workspace_id=workspace_id,
                name=name,
                geography=geography,
            )
            self.db.add(team)

            # Add validated members
            for mem_user_id in valid_member_ids:
                team_membership = TeamMembership(
                    id=str(uuid.uuid4()),
                    team_id=team_id,
                    user_id=mem_user_id,
                )
                self.db.add(team_membership)

            # Single commit for team + all members
            await self.db.commit()

            # Return created team with actual member count
            return {
                "id": team.id,
                "workspace_id": team.workspace_id,
                "name": team.name,
                "geography": team.geography,
                "membership_count": len(valid_member_ids),
                "service_count": 0,
                "created_at": team.created_at,
                "updated_at": team.updated_at,
            }

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating team: {str(e)}")
            raise

    async def update_team(
        self,
        workspace_id: str,
        team_id: str,
        user_id: str,
        name: Optional[str] = None,
        geography: Optional[str] = None,
    ) -> dict:
        """
        Update a team.

        Args:
            workspace_id: Workspace ID
            team_id: Team ID
            user_id: Current user ID (must be owner)
            name: New team name (optional)
            geography: New geography (optional)

        Returns:
            Updated team object

        Raises:
            PermissionError: User is not workspace owner
            ValueError: Team not found
        """
        # Verify user is workspace owner
        is_owner = await self._verify_workspace_owner(workspace_id, user_id)
        if not is_owner:
            raise PermissionError("Only workspace owners can update teams")

        # Get team
        query = select(Team).where(
            and_(Team.id == team_id, Team.workspace_id == workspace_id)
        )
        result = await self.db.execute(query)
        team = result.scalar_one_or_none()

        if not team:
            raise ValueError(f"Team {team_id} not found in workspace {workspace_id}")

        # Update fields
        if name is not None:
            team.name = name
        if geography is not None:
            team.geography = geography

        await self.db.commit()

        # Get counts
        membership_count = await self._get_team_membership_count(team.id)
        service_count = await self._get_team_service_count(team.id)

        return {
            "id": team.id,
            "workspace_id": team.workspace_id,
            "name": team.name,
            "geography": team.geography,
            "membership_count": membership_count,
            "service_count": service_count,
            "created_at": team.created_at,
            "updated_at": team.updated_at,
        }

    async def delete_team(
        self, workspace_id: str, team_id: str, user_id: str
    ) -> None:
        """
        Delete a team.

        Side effect: Sets all services' team_id to NULL.

        Args:
            workspace_id: Workspace ID
            team_id: Team ID
            user_id: Current user ID (must be owner)

        Raises:
            PermissionError: User is not workspace owner
            ValueError: Team not found
        """
        # Verify user is workspace owner
        is_owner = await self._verify_workspace_owner(workspace_id, user_id)
        if not is_owner:
            raise PermissionError("Only workspace owners can delete teams")

        # Get team
        query = select(Team).where(
            and_(Team.id == team_id, Team.workspace_id == workspace_id)
        )
        result = await self.db.execute(query)
        team = result.scalar_one_or_none()

        if not team:
            raise ValueError(f"Team {team_id} not found in workspace {workspace_id}")

        # Set services' team_id to NULL
        update_query = (
            select(Service)
            .where(Service.team_id == team_id)
        )
        result = await self.db.execute(update_query)
        services = result.scalars().all()
        for service in services:
            service.team_id = None

        # Delete team (cascade will delete team_memberships)
        await self.db.delete(team)
        await self.db.commit()

        logger.info(f"Team {team_id} deleted. {len(services)} services unassigned.")

    async def _verify_workspace_owner(self, workspace_id: str, user_id: str) -> bool:
        """Verify user is an owner of the workspace."""
        query = select(Membership).where(
            and_(
                Membership.workspace_id == workspace_id,
                Membership.user_id == user_id,
                Membership.role == Role.OWNER,
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def add_team_member(
        self, workspace_id: str, team_id: str, user_id: str, member_user_id: str
    ) -> dict:
        """
        Add a member to a team.

        Args:
            workspace_id: Workspace ID
            team_id: Team ID
            user_id: Current user ID (must be owner)
            member_user_id: User ID to add to team

        Returns:
            TeamMembership object

        Raises:
            PermissionError: User is not workspace owner
            ValueError: Team/User not found or already a member
        """
        # Verify user is workspace owner
        is_owner = await self._verify_workspace_owner(workspace_id, user_id)
        if not is_owner:
            raise PermissionError("Only workspace owners can add team members")

        # Verify team exists in workspace
        team_query = select(Team).where(
            and_(Team.id == team_id, Team.workspace_id == workspace_id)
        )
        team_result = await self.db.execute(team_query)
        team = team_result.scalar_one_or_none()
        if not team:
            raise ValueError(f"Team {team_id} not found in workspace {workspace_id}")

        # Verify member is workspace member
        member_is_workspace_member = await self._verify_workspace_member(
            workspace_id, member_user_id
        )
        if not member_is_workspace_member:
            raise ValueError(
                f"User {member_user_id} is not a member of workspace {workspace_id}"
            )

        # Check if already a team member
        existing_query = select(TeamMembership).where(
            and_(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == member_user_id,
            )
        )
        existing_result = await self.db.execute(existing_query)
        if existing_result.scalar_one_or_none():
            raise ValueError(
                f"User {member_user_id} is already a member of this team"
            )

        # Get member details
        member_query = select(User).where(User.id == member_user_id)
        member_result = await self.db.execute(member_query)
        member_user = member_result.scalar_one_or_none()

        # Create team membership
        membership_id = str(uuid.uuid4())
        team_membership = TeamMembership(
            id=membership_id,
            team_id=team_id,
            user_id=member_user_id,
        )
        self.db.add(team_membership)
        await self.db.commit()

        return {
            "id": team_membership.id,
            "team_id": team_membership.team_id,
            "user": {
                "id": member_user.id,
                "name": member_user.name,
                "email": member_user.email,
            },
            "created_at": team_membership.created_at,
            "team_name": team.name,
        }

    async def remove_team_member(
        self, workspace_id: str, team_id: str, user_id: str, member_user_id: str
    ) -> None:
        """
        Remove a member from a team.

        Args:
            workspace_id: Workspace ID
            team_id: Team ID
            user_id: Current user ID (must be owner)
            member_user_id: User ID to remove from team

        Raises:
            PermissionError: User is not workspace owner
            ValueError: Team/Membership not found
        """
        # Verify user is workspace owner
        is_owner = await self._verify_workspace_owner(workspace_id, user_id)
        if not is_owner:
            raise PermissionError("Only workspace owners can remove team members")

        # Verify team exists in workspace
        team_query = select(Team).where(
            and_(Team.id == team_id, Team.workspace_id == workspace_id)
        )
        team_result = await self.db.execute(team_query)
        team = team_result.scalar_one_or_none()
        if not team:
            raise ValueError(f"Team {team_id} not found in workspace {workspace_id}")

        # Find and delete membership
        membership_query = select(TeamMembership).where(
            and_(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == member_user_id,
            )
        )
        membership_result = await self.db.execute(membership_query)
        membership = membership_result.scalar_one_or_none()

        if not membership:
            raise ValueError(
                f"User {member_user_id} is not a member of this team"
            )

        await self.db.delete(membership)
        await self.db.commit()

        logger.info(
            f"User {member_user_id} removed from team {team_id} by {user_id}"
        )
