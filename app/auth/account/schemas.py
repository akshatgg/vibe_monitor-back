"""
Account schemas for profile and deletion.
"""

from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class AccountProfileResponse(BaseModel):
    """Response for user account profile"""

    id: str
    name: str
    email: str
    is_verified: bool
    newsletter_subscribed: bool = True
    auth_provider: Literal["google", "credentials"]
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AccountUpdateRequest(BaseModel):
    """Request body for updating account profile"""

    name: Optional[str] = None
    newsletter_subscribed: Optional[bool] = None


class Role(str, Enum):
    """Role of user in a workspace"""

    OWNER = "OWNER"
    USER = "USER"


class BlockingWorkspace(BaseModel):
    """Workspace that prevents account deletion"""

    id: str
    name: str
    member_count: int
    action_required: str = Field(
        ...,
        description="Action required to unblock deletion, e.g., 'Transfer ownership or remove 3 members'",
    )


class WorkspacePreview(BaseModel):
    """Workspace that will be affected by account deletion"""

    id: str
    name: str
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
        description="Must be 'DELETE' to confirm deletion",
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
