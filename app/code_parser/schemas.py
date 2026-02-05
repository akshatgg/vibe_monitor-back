"""
Pydantic schemas for code parser module.

Defines schemas for parsed code structures (functions, classes, imports).
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class FunctionInfo(BaseModel):
    """Information about a parsed function."""

    name: str = Field(..., description="Function name")
    line_start: int = Field(..., description="Starting line number (1-indexed)")
    line_end: Optional[int] = Field(None, description="Ending line number (1-indexed)")
    params: List[str] = Field(default_factory=list, description="Parameter names")
    decorators: List[str] = Field(default_factory=list, description="Decorator names")
    is_async: bool = Field(default=False, description="Whether the function is async")
    return_type: Optional[str] = Field(None, description="Return type annotation")
    docstring: Optional[str] = Field(None, description="Function docstring (first 500 chars)")

    class Config:
        extra = "ignore"


class ClassInfo(BaseModel):
    """Information about a parsed class."""

    name: str = Field(..., description="Class name")
    line_start: int = Field(..., description="Starting line number (1-indexed)")
    line_end: Optional[int] = Field(None, description="Ending line number (1-indexed)")
    methods: List[str] = Field(default_factory=list, description="Method names")
    bases: List[str] = Field(default_factory=list, description="Base class names")
    decorators: List[str] = Field(default_factory=list, description="Decorator names")
    docstring: Optional[str] = Field(None, description="Class docstring (first 500 chars)")

    class Config:
        extra = "ignore"


class ImportInfo(BaseModel):
    """Information about an import statement."""

    module: str = Field(..., description="Module being imported")
    names: List[str] = Field(default_factory=list, description="Imported names (from X import a, b)")
    alias: Optional[str] = Field(None, description="Import alias (import X as Y)")
    is_relative: bool = Field(default=False, description="Whether this is a relative import")

    class Config:
        extra = "ignore"


class ParsedFileResult(BaseModel):
    """Result of parsing a single file."""

    functions: List[FunctionInfo] = Field(default_factory=list, description="Parsed functions")
    classes: List[ClassInfo] = Field(default_factory=list, description="Parsed classes")
    imports: List[ImportInfo] = Field(default_factory=list, description="Parsed imports")
    line_count: int = Field(default=0, description="Total number of lines in the file")
    parse_error: Optional[str] = Field(None, description="Error message if parsing failed")

    class Config:
        extra = "ignore"


class ParsedFileData(BaseModel):
    """Complete data for a parsed file, including content."""

    file_path: str = Field(..., description="Path to the file in the repository")
    language: str = Field(..., description="Detected language")
    content: Optional[str] = Field(None, description="Full file content")
    content_hash: Optional[str] = Field(None, description="SHA-256 hash of content")
    size_bytes: int = Field(default=0, description="File size in bytes")
    line_count: int = Field(default=0, description="Number of lines")
    functions: List[FunctionInfo] = Field(default_factory=list)
    classes: List[ClassInfo] = Field(default_factory=list)
    imports: List[ImportInfo] = Field(default_factory=list)
    is_parsed: bool = Field(default=True, description="Whether parsing succeeded")
    parse_error: Optional[str] = Field(None, description="Parse error message if failed")

    class Config:
        extra = "ignore"


class ParsedRepositoryData(BaseModel):
    """Complete parsed repository data."""

    workspace_id: str
    repo_full_name: str
    default_branch: Optional[str] = None
    commit_sha: str
    status: str = "COMPLETED"
    total_files: int = 0
    parsed_files: int = 0
    skipped_files: int = 0
    total_functions: int = 0
    total_classes: int = 0
    total_imports: int = 0
    languages: dict = Field(default_factory=dict)
    parse_errors: List[dict] = Field(default_factory=list)
    files: List[ParsedFileData] = Field(default_factory=list)

    class Config:
        extra = "ignore"
