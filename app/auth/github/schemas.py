from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# User schemas
class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    last_visited_workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# Auth schemas
class GitHubOAuthToken(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str
