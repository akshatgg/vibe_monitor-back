"""
Account schemas for profile and deletion.
"""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class AccountProfileResponse(BaseModel):
    """Response for user account profile"""

    id: str
    name: str
    email: str
    is_verified: bool
    newsletter_subscribed: bool = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AccountUpdateRequest(BaseModel):
    """Request body for updating account profile"""

    name: Optional[str] = None
    newsletter_subscribed: Optional[bool] = None


class WorkspaceType(str, Enum):
    """Type of workspace - personal or team"""

    PERSONAL = "personal"
    TEAM = "team"


class Role(str, Enum):
    """Role of user in a workspace"""

    OWNER = "owner"
    USER = "user"


class BlockingWorkspace(BaseModel):
    """Workspace that prevents account deletion"""

    id: str
    name: str
    type: WorkspaceType
    member_count: int
    action_required: str = Field(
        ...,
        description="Action required to unblock deletion, e.g., 'Transfer ownership or remove 3 members'",
    )


class WorkspacePreview(BaseModel):
    """Workspace that will be affected by account deletion"""

    id: str
    name: str
    type: WorkspaceType
    user_role: Role


class DeletionPreviewResponse(BaseModel):
    """Response for account deletion preview"""

    can_delete: bool
    blocking_workspaces: List[BlockingWorkspace]
    workspaces_to_delete: List[WorkspacePreview]
    workspaces_to_leave: List[WorkspacePreview]
    message: str


class AccountDeleteRequest(BaseModel):
    """Request body for account deletion"""

    confirmation: str = Field(
        ...,
        description="Must be 'DELETE' or user's email to confirm deletion",
    )
    password: Optional[str] = Field(
        None,
        description="Required for credential-based (password) accounts",
    )


class AccountDeleteResponse(BaseModel):
    """Response for successful account deletion"""

    success: bool
    deleted_workspaces: List[str] = Field(
        default_factory=list,
        description="IDs of workspaces that were deleted",
    )
    left_workspaces: List[str] = Field(
        default_factory=list,
        description="IDs of workspaces user was removed from",
    )
    message: str
