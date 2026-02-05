"""
CodebaseSync Tools - Functions for LLMAnalyzer to navigate and inspect codebase.

These tools provide access to repository content, preferring the local database
cache for fast access, with fallback to GitHub API when needed.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.code_parser import CodeParserService
from app.github.tools.router import (
    get_repository_tree,
    read_repository_file,
    search_code,
)
from app.health_review_system.codebase_sync.schemas import ParsedCodebaseInfo

logger = logging.getLogger(__name__)


# ==================== DB-BASED TOOLS (FAST, NO API CALLS) ====================


async def read_file_from_db(
    workspace_id: str,
    repo_full_name: str,
    file_path: str,
    db: AsyncSession,
) -> Optional[str]:
    """
    Read file content from local database (fast, no GitHub API call).

    This reads from the parsed codebase cache. Use this when the repository
    has been parsed and you want fast access to file contents.

    Args:
        workspace_id: Workspace ID
        repo_full_name: Full repository name (owner/repo)
        file_path: Path to file within repository
        db: Database session

    Returns:
        File content as string, or None if not found in cache
    """
    try:
        code_parser = CodeParserService(db)
        content = await code_parser.get_file_content(workspace_id, repo_full_name, file_path)

        if content:
            logger.debug(f"Read file from DB cache: {file_path}")
            return content

        return None

    except Exception as e:
        logger.warning(f"Failed to read file from DB: {file_path}: {e}")
        return None


async def search_function_in_db(
    workspace_id: str,
    repo_full_name: str,
    function_name: str,
    db: AsyncSession,
    exact_match: bool = False,
) -> List[Dict[str, Any]]:
    """
    Search for a function by name in the local database.

    Args:
        workspace_id: Workspace ID
        repo_full_name: Full repository name (owner/repo)
        function_name: Function name to search for
        db: Database session
        exact_match: If True, require exact name match

    Returns:
        List of matching functions with file info and line numbers
    """
    try:
        code_parser = CodeParserService(db)
        results = await code_parser.search_function(
            workspace_id, repo_full_name, function_name, exact_match
        )

        logger.debug(f"Found {len(results)} functions matching '{function_name}'")
        return results

    except Exception as e:
        logger.warning(f"Failed to search functions in DB: {e}")
        return []


async def search_class_in_db(
    workspace_id: str,
    repo_full_name: str,
    class_name: str,
    db: AsyncSession,
    exact_match: bool = False,
) -> List[Dict[str, Any]]:
    """
    Search for a class by name in the local database.

    Args:
        workspace_id: Workspace ID
        repo_full_name: Full repository name (owner/repo)
        class_name: Class name to search for
        db: Database session
        exact_match: If True, require exact name match

    Returns:
        List of matching classes with file info and line numbers
    """
    try:
        code_parser = CodeParserService(db)
        results = await code_parser.search_class(
            workspace_id, repo_full_name, class_name, exact_match
        )

        logger.debug(f"Found {len(results)} classes matching '{class_name}'")
        return results

    except Exception as e:
        logger.warning(f"Failed to search classes in DB: {e}")
        return []


async def get_file_structure_from_db(
    workspace_id: str,
    repo_full_name: str,
    file_path: str,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    """
    Get file structure (functions, classes, imports) without content.

    This is useful for understanding file structure without loading full content.

    Args:
        workspace_id: Workspace ID
        repo_full_name: Full repository name (owner/repo)
        file_path: Path to file within repository
        db: Database session

    Returns:
        File structure dict or None if not found
    """
    try:
        code_parser = CodeParserService(db)
        structure = await code_parser.get_file_structure(workspace_id, repo_full_name, file_path)

        if structure:
            logger.debug(f"Got file structure from DB: {file_path}")

        return structure

    except Exception as e:
        logger.warning(f"Failed to get file structure from DB: {e}")
        return None


async def list_files_from_db(
    workspace_id: str,
    repo_full_name: str,
    db: AsyncSession,
    language: Optional[str] = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """
    List all parsed files for a repository from the database.

    Args:
        workspace_id: Workspace ID
        repo_full_name: Full repository name (owner/repo)
        db: Database session
        language: Optional language filter (e.g., "python", "javascript")
        limit: Maximum number of results

    Returns:
        List of file info dictionaries
    """
    try:
        code_parser = CodeParserService(db)
        files = await code_parser.list_files(workspace_id, repo_full_name, language, limit)

        logger.debug(f"Listed {len(files)} files from DB for {repo_full_name}")
        return files

    except Exception as e:
        logger.warning(f"Failed to list files from DB: {e}")
        return []


# ==================== HYBRID TOOLS (DB FIRST, FALLBACK TO GITHUB) ====================


async def read_file(
    workspace_id: str,
    repo_full_name: str,
    file_path: str,
    db: AsyncSession,
    branch: str = "HEAD",
) -> Optional[str]:
    """
    Read a specific file from the repository.

    This function tries the local database cache first for fast access,
    then falls back to GitHub API if not found in cache.

    Args:
        workspace_id: Workspace ID
        repo_full_name: Full repository name (owner/repo)
        file_path: Path to file within repository
        db: Database session
        branch: Branch or ref to read from (default: HEAD)

    Returns:
        File content as string, or None if file not found
    """
    # Try DB cache first (fast)
    content = await read_file_from_db(workspace_id, repo_full_name, file_path, db)
    if content:
        return content

    # Fallback to GitHub API
    logger.debug(f"File not in DB cache, fetching from GitHub: {file_path}")

    parts = repo_full_name.split("/")
    if len(parts) != 2:
        logger.error(f"Invalid repo name format: {repo_full_name}")
        return None

    owner, repo_name = parts

    try:
        response = await read_repository_file(
            workspace_id=workspace_id,
            name=repo_name,
            file_path=file_path,
            owner=owner,
            branch=branch,
            user_id="health-review-system",
            db=db,
        )

        if response and response.get("content"):
            return response["content"]

        return None

    except Exception as e:
        logger.exception(f"Failed to read file {file_path}: {e}")
        return None


# ==================== GITHUB-ONLY TOOLS ====================


async def search_in_code(
    workspace_id: str,
    repo_full_name: str,
    query: str,
    db: AsyncSession,
    per_page: int = 30,
) -> List[Dict[str, Any]]:
    """
    Search for code patterns in the repository using GitHub Code Search.

    Note: This always uses GitHub API as it requires full-text search capability.

    Args:
        workspace_id: Workspace ID
        repo_full_name: Full repository name (owner/repo)
        query: Search query (supports GitHub code search syntax)
        db: Database session
        per_page: Number of results per page

    Returns:
        List of search results with file paths and matched content
    """
    parts = repo_full_name.split("/")
    if len(parts) != 2:
        logger.error(f"Invalid repo name format: {repo_full_name}")
        return []

    owner, repo_name = parts

    try:
        response = await search_code(
            workspace_id=workspace_id,
            search_query=query,
            owner=owner,
            repo=repo_name,
            per_page=per_page,
            page=1,
            user_id="health-review-system",
            db=db,
        )

        if response and "items" in response:
            return response["items"]

        return []

    except Exception as e:
        logger.exception(f"Failed to search code for '{query}': {e}")
        return []


async def get_file_tree(
    workspace_id: str,
    repo_full_name: str,
    db: AsyncSession,
    path: str = "",
    branch: str = "HEAD",
) -> List[Dict[str, Any]]:
    """
    Get the file tree (directory listing) for a repository path.

    Note: This uses GitHub API for live directory listing.

    Args:
        workspace_id: Workspace ID
        repo_full_name: Full repository name (owner/repo)
        db: Database session
        path: Path within repository (empty for root)
        branch: Branch or ref (default: HEAD)

    Returns:
        List of file/directory entries with name, type, and path
    """
    parts = repo_full_name.split("/")
    if len(parts) != 2:
        logger.error(f"Invalid repo name format: {repo_full_name}")
        return []

    owner, repo_name = parts

    try:
        expression = f"{branch}:{path}" if path else branch

        response = await get_repository_tree(
            workspace_id=workspace_id,
            name=repo_name,
            expression=expression,
            owner=owner,
            user_id="health-review-system",
            db=db,
        )

        if response and "entries" in response:
            return response["entries"]

        return []

    except Exception as e:
        logger.exception(f"Failed to get file tree for {path}: {e}")
        return []


# ==================== IN-MEMORY TOOLS (FOR PARSED CODEBASE DATA) ====================


def list_functions_from_parsed(
    parsed_codebase: ParsedCodebaseInfo,
    file_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List functions from parsed codebase data.

    Args:
        parsed_codebase: Parsed codebase info from CodeParserService
        file_path: Optional filter by file path

    Returns:
        List of function information dictionaries
    """
    functions = []

    for file_info in parsed_codebase.files:
        if file_path and file_info.path != file_path:
            continue

        for func_name in file_info.functions:
            functions.append({
                "name": func_name,
                "file": file_info.path,
            })

    return functions


def list_classes_from_parsed(
    parsed_codebase: ParsedCodebaseInfo,
    file_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List classes from parsed codebase data.

    Args:
        parsed_codebase: Parsed codebase info from CodeParserService
        file_path: Optional filter by file path

    Returns:
        List of class information dictionaries
    """
    classes = []

    for file_info in parsed_codebase.files:
        if file_path and file_info.path != file_path:
            continue

        for class_name in file_info.classes:
            classes.append({
                "name": class_name,
                "file": file_info.path,
            })

    return classes


def find_function_by_name(
    parsed_codebase: ParsedCodebaseInfo,
    function_name: str,
) -> Optional[Dict[str, Any]]:
    """
    Find a function by name in the parsed codebase.

    Args:
        parsed_codebase: Parsed codebase info
        function_name: Name of function to find

    Returns:
        Dict with function info and file path, or None if not found
    """
    for file_info in parsed_codebase.files:
        if function_name in file_info.functions:
            return {
                "name": function_name,
                "file": file_info.path,
            }

    return None


def find_class_by_name(
    parsed_codebase: ParsedCodebaseInfo,
    class_name: str,
) -> Optional[Dict[str, Any]]:
    """
    Find a class by name in the parsed codebase.

    Args:
        parsed_codebase: Parsed codebase info
        class_name: Name of class to find

    Returns:
        Dict with class info and file path, or None if not found
    """
    for file_info in parsed_codebase.files:
        if class_name in file_info.classes:
            return {
                "name": class_name,
                "file": file_info.path,
            }

    return None


def get_files_by_language(
    parsed_codebase: ParsedCodebaseInfo,
    language: str,
) -> List[str]:
    """
    Get file paths filtered by language/extension.

    Args:
        parsed_codebase: Parsed codebase info
        language: Language or extension to filter (e.g., "python", ".py")

    Returns:
        List of file paths matching the language
    """
    language_lower = language.lower()

    # Extension mappings
    extension_map = {
        "python": [".py"],
        "javascript": [".js", ".jsx", ".mjs"],
        "typescript": [".ts", ".tsx"],
        "go": [".go"],
        "java": [".java"],
        "ruby": [".rb"],
    }

    extensions = extension_map.get(language_lower, [f".{language_lower}"])

    matching_files = []
    for file_info in parsed_codebase.files:
        for ext in extensions:
            if file_info.path.endswith(ext):
                matching_files.append(file_info.path)
                break

    return matching_files


# ==================== TOOL DEFINITIONS FOR LANGGRAPH ====================


def get_codebase_tools_definitions() -> List[Dict[str, Any]]:
    """
    Get tool definitions for binding to LangGraph agent.

    Returns:
        List of tool definitions in OpenAI function format
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the contents of a specific file from the repository. Uses local cache for fast access.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to the file within the repository (e.g., 'src/main.py')",
                        },
                    },
                    "required": ["file_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_function",
                "description": "Search for a function by name across all files in the repository.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "function_name": {
                            "type": "string",
                            "description": "Name of the function to search for",
                        },
                        "exact_match": {
                            "type": "boolean",
                            "description": "If true, require exact name match. Default false.",
                            "default": False,
                        },
                    },
                    "required": ["function_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_class",
                "description": "Search for a class by name across all files in the repository.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "class_name": {
                            "type": "string",
                            "description": "Name of the class to search for",
                        },
                        "exact_match": {
                            "type": "boolean",
                            "description": "If true, require exact name match. Default false.",
                            "default": False,
                        },
                    },
                    "required": ["class_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_file_structure",
                "description": "Get the structure of a file (functions, classes, imports) without loading full content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to the file within the repository",
                        },
                    },
                    "required": ["file_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List all parsed files in the repository, optionally filtered by language.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "language": {
                            "type": "string",
                            "description": "Optional language filter (e.g., 'python', 'javascript')",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_code",
                "description": "Search for code patterns using GitHub Code Search. Use for full-text search.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (supports GitHub code search syntax)",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    ]
