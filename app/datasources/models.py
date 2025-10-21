"""
Pydantic models for datasources module
"""
from typing import List
from pydantic import BaseModel, Field


class DatasourceResponse(BaseModel):
    """Response model for datasource information"""
    id: int = Field(description="Datasource ID")
    uid: str = Field(description="Datasource UID")
    name: str = Field(description="Datasource name")
    type: str = Field(description="Datasource type (e.g., prometheus, loki, tempo)")
    url: str = Field(description="Datasource URL")
    is_default: bool = Field(description="Whether this is the default datasource", alias="isDefault")

    class Config:
        populate_by_name = True


class LabelResponse(BaseModel):
    """Response model for label queries"""
    status: str = Field(description="Query status (success/error)")
    data: List[str] = Field(description="List of label names or values")
