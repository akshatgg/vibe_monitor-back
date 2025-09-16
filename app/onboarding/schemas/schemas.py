from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum


class Role(str, Enum):
    OWNER = "owner"
    MEMBER = "member"


# User schemas
class UserCreate(BaseModel):
    name: str
    email: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    created_at: Optional[datetime] = None
    
    model_config = {"from_attributes": True}


# Workspace schemas
class WorkspaceCreate(BaseModel):
    name: str
    domain: Optional[str] = None
    visible_to_org: bool = False


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    domain: Optional[str] = None
    visible_to_org: bool
    is_paid: bool
    created_at: Optional[datetime] = None
    
    model_config = {"from_attributes": True}


# Membership schemas
class MembershipResponse(BaseModel):
    id: str
    user_id: str
    workspace_id: str
    role: Role
    created_at: Optional[datetime] = None
    
    # Optional nested objects
    user: Optional[UserResponse] = None
    workspace: Optional[WorkspaceResponse] = None
    
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


# Auth schemas
class GoogleOAuthToken(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str