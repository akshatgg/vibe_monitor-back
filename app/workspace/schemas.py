from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Role(str, Enum):
    OWNER = "OWNER"
    USER = "USER"  # Renamed from MEMBER


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
    domain: Optional[str] = None
    visible_to_org: bool = False


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    visible_to_org: Optional[bool] = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
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
    domain: Optional[str] = None
    visible_to_org: bool
    is_paid: bool
    created_at: Optional[datetime] = None
    user_role: Role  # The current user's role in this workspace

    model_config = {"from_attributes": True}
