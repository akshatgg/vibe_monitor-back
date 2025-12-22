"""
Schemas for repository service discovery
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class ScanRepositoryRequest(BaseModel):
    """Request to scan a repository"""

    repo: str = Field(..., description="Repository name")


class RepositoryServiceResponse(BaseModel):
    """Response with repository services"""

    id: str
    workspace_id: str
    repo_name: str
    services: List[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
