from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Role(str, Enum):
    OWNER = "owner"
    USER = "user"  # Renamed from MEMBER


class WorkspaceType(str, Enum):
    PERSONAL = "personal"
    TEAM = "team"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"


# User schemas
class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    last_visited_workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# Workspace schemas
class WorkspaceCreate(BaseModel):
    name: str
    type: WorkspaceType = WorkspaceType.TEAM
    domain: Optional[str] = None
    visible_to_org: bool = False


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    visible_to_org: Optional[bool] = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    type: WorkspaceType
    domain: Optional[str] = None
    visible_to_org: bool
    is_paid: bool
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# Combined response schemas
class WorkspaceWithMembership(BaseModel):
    """Workspace with user's membership role"""

    id: str
    name: str
    type: WorkspaceType
    domain: Optional[str] = None
    visible_to_org: bool
    is_paid: bool
    created_at: Optional[datetime] = None
    user_role: Role  # The current user's role in this workspace

    model_config = {"from_attributes": True}


# Grafana Integration schemas
class GrafanaIntegrationCreate(BaseModel):
    workspace_id: str
    grafana_url: str
    api_token: str


class GrafanaIntegrationUpdate(BaseModel):
    grafana_url: Optional[str] = None
    api_token: Optional[str] = None


class GrafanaIntegrationResponse(BaseModel):
    id: str
    vm_workspace_id: str
    grafana_url: str
    api_token: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# Invitation schemas
class InvitationCreate(BaseModel):
    """Request to invite a user to a workspace"""

    email: str
    role: Role = Role.USER


class InvitationResponse(BaseModel):
    """Response for an invitation"""

    id: str
    workspace_id: str
    workspace_name: str
    inviter_name: str
    invitee_email: str
    role: Role
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


# Member schemas
class MemberResponse(BaseModel):
    """Response for a workspace member"""

    user_id: str
    user_name: str
    user_email: str
    role: Role
    joined_at: datetime  # membership.created_at

    model_config = {"from_attributes": True}


class MemberRoleUpdate(BaseModel):
    """Request to update a member's role"""

    role: Role
