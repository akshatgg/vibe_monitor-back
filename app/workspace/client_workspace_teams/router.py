"""
FastAPI router for team endpoints.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google.service import AuthService
from app.core.database import get_db
from app.models import User
from .schemas import (
    TeamCreate,
    TeamDetailResponse,
    TeamListResponse,
    TeamMemberAdd,
    TeamMemberResponse,
    TeamResponse,
    TeamUpdate,
)
from .service import TeamService

logger = logging.getLogger(__name__)
auth_service = AuthService()

router = APIRouter(prefix="/workspaces/{workspace_id}/teams", tags=["teams"])


@router.get("", response_model=TeamListResponse)
async def list_teams(
    workspace_id: str,
    search: Optional[str] = Query(None, description="Filter by team name (case-insensitive)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    List all teams in a workspace with optional search and pagination.

    **Auth:** Workspace member (any role)

    **Query Parameters:**
    - `search` (optional): Filter by team name (case-insensitive)
    - `offset` (default: 0): Pagination offset
    - `limit` (default: 20, max: 100): Page size

    **Response:** Paginated list of teams with member and service counts
    """
    try:
        service = TeamService(db)
        result = await service.list_teams(
            workspace_id=workspace_id,
            user_id=current_user.id,
            search=search,
            offset=offset,
            limit=limit,
        )
        return result
    except PermissionError as e:
        logger.warning(f"Permission denied for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of this workspace",
        )
    except Exception as e:
        logger.error(f"Error listing teams: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list teams",
        )


@router.get("/{team_id}", response_model=TeamDetailResponse)
async def get_team_detail(
    workspace_id: str,
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Get detailed team information including members and services.

    **Auth:** Workspace member (any role)

    **Response:** Team object with nested member details and services
    """
    try:
        service = TeamService(db)
        result = await service.get_team_detail(
            workspace_id=workspace_id,
            team_id=team_id,
            user_id=current_user.id,
        )
        return result
    except PermissionError as e:
        logger.warning(f"Permission denied for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of this workspace",
        )
    except ValueError as e:
        logger.warning(f"Team not found: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error getting team detail: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve team details",
        )


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    workspace_id: str,
    team_data: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Create a new team in a workspace.

    **Auth:** Workspace owner only

    **Request:**
    - `name` (required): Team name
    - `geography` (optional): Team location/region
    - `membership_ids` (optional): List of user IDs to add to team

    **Response:** Created team object (201 Created)
    """
    try:
        service = TeamService(db)
        result = await service.create_team(
            workspace_id=workspace_id,
            user_id=current_user.id,
            name=team_data.name,
            geography=team_data.geography,
            membership_ids=team_data.membership_ids,
        )
        return result
    except PermissionError as e:
        logger.warning(f"Permission denied for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace owners can create teams",
        )
    except Exception as e:
        logger.error(f"Error creating team: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create team",
        )


@router.patch("/{team_id}", response_model=TeamResponse)
async def update_team(
    workspace_id: str,
    team_id: str,
    team_data: TeamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Update a team.

    **Auth:** Workspace owner only

    **Request:**
    - `name` (optional): New team name
    - `geography` (optional): New team location/region

    **Response:** Updated team object
    """
    try:
        service = TeamService(db)
        result = await service.update_team(
            workspace_id=workspace_id,
            team_id=team_id,
            user_id=current_user.id,
            name=team_data.name,
            geography=team_data.geography,
        )
        return result
    except PermissionError as e:
        logger.warning(f"Permission denied for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace owners can update teams",
        )
    except ValueError as e:
        logger.warning(f"Team not found: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error updating team: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update team",
        )


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    workspace_id: str,
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Delete a team.

    **Auth:** Workspace owner only

    **Response:** 204 No Content

    **Side Effect:** All services assigned to this team will have their team_id set to NULL
    """
    try:
        service = TeamService(db)
        await service.delete_team(
            workspace_id=workspace_id,
            team_id=team_id,
            user_id=current_user.id,
        )
    except PermissionError as e:
        logger.warning(f"Permission denied for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace owners can delete teams",
        )
    except ValueError as e:
        logger.warning(f"Team not found: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error deleting team: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete team",
        )


@router.post("/{team_id}/members", response_model=TeamMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_team_member(
    workspace_id: str,
    team_id: str,
    member_data: TeamMemberAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Add a member to a team.

    **Auth:** Workspace owner only

    **Request:**
    - `user_id` (required): User ID to add to team

    **Response:** TeamMembership object (201 Created)

    **Validation:** User must be a workspace member
    """
    try:
        service = TeamService(db)
        result = await service.add_team_member(
            workspace_id=workspace_id,
            team_id=team_id,
            user_id=current_user.id,
            member_user_id=member_data.user_id,
        )
        return result
    except PermissionError as e:
        logger.warning(f"Permission denied for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace owners can add team members",
        )
    except ValueError as e:
        logger.warning(f"Validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error adding team member: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add team member",
        )


@router.delete("/{team_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member(
    workspace_id: str,
    team_id: str,
    member_user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Remove a member from a team.

    **Auth:** Workspace owner only

    **Response:** 204 No Content
    """
    try:
        service = TeamService(db)
        await service.remove_team_member(
            workspace_id=workspace_id,
            team_id=team_id,
            user_id=current_user.id,
            member_user_id=member_user_id,
        )
    except PermissionError as e:
        logger.warning(f"Permission denied for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace owners can remove team members",
        )
    except ValueError as e:
        logger.warning(f"Validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error removing team member: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove team member",
        )
