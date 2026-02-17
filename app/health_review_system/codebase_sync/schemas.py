"""
Schemas for Codebase Sync Service.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ParsedFileInfo(BaseModel):
    """Information about a parsed file."""

    path: str
    functions: List[str] = Field(default_factory=list)
    classes: List[str] = Field(default_factory=list)


class ParsedCodebaseInfo(BaseModel):
    """Summary of parsed codebase."""

    files: List[ParsedFileInfo] = Field(default_factory=list)
    total_files: int = 0
    total_functions: int = 0
    total_classes: int = 0
    languages: Dict[str, int] = Field(default_factory=dict)


class CodebaseSyncResult(BaseModel):
    """Result of codebase sync operation."""

    commit_sha: str
    changed: bool
    parsed_codebase: Optional[ParsedCodebaseInfo] = None
    changed_files: List[str] = Field(
        default_factory=list,
        description="File paths that changed between previous and current commit",
    )
