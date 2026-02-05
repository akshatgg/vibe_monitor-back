"""
Code Parser Module - Parse and index repository codebases.

This module provides:
- CodeParserService: Main service for parsing repositories
- Language parsers: Python, JavaScript, TypeScript, Go, Java
- DB repositories: CRUD operations for parsed data

Usage:
    from app.code_parser import CodeParserService

    parser = CodeParserService(db_session)
    result = await parser.get_or_parse_repository(
        workspace_id="...",
        installation_id="...",
        repo_full_name="owner/repo",
        commit_sha="abc123...",
    )
"""

from app.code_parser.service import CodeParserService
from app.code_parser.repository import ParsedFileRepository, ParsedRepositoryRepository
from app.code_parser.parsers import ParserRegistry, get_parser_registry
from app.code_parser.schemas import (
    FunctionInfo,
    ClassInfo,
    ImportInfo,
    ParsedFileResult,
    ParsedFileData,
    ParsedRepositoryData,
)

__all__ = [
    "CodeParserService",
    "ParsedFileRepository",
    "ParsedRepositoryRepository",
    "ParserRegistry",
    "get_parser_registry",
    "FunctionInfo",
    "ClassInfo",
    "ImportInfo",
    "ParsedFileResult",
    "ParsedFileData",
    "ParsedRepositoryData",
]
