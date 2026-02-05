"""
Code Analysis Tools for LLM Analyzer.

Tools for inspecting parsed codebase: reading files, searching functions/classes.
"""

import json
import logging
from typing import Optional

from langchain_core.tools import tool

from app.health_review_system.llm_analyzer.tools.base import get_analysis_context

logger = logging.getLogger(__name__)


@tool
def read_file(file_path: str) -> str:
    """
    Read the structure of a specific file from the parsed codebase.

    Returns the file's functions, classes, and imports.
    Use this to understand what a file contains before investigating further.

    Args:
        file_path: Path of the file to read (e.g., "src/api/routes.py")

    Returns:
        File structure including functions, classes, and imports, or error message if not found.
    """
    try:
        context = get_analysis_context()
        file_info = context.get_file(file_path)

        if not file_info:
            # Try partial match
            if context.codebase and context.codebase.files:
                for f in context.codebase.files:
                    if file_path in f.path or f.path.endswith(file_path):
                        file_info = f
                        break

        if not file_info:
            return f"File not found: {file_path}. Use list_files() to see available files."

        result = {
            "path": file_info.path,
            "functions": file_info.functions,
            "classes": file_info.classes,
            "function_count": len(file_info.functions),
            "class_count": len(file_info.classes),
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.exception(f"Error in read_file: {e}")
        return f"Error reading file: {str(e)}"


@tool
def search_functions(query: str, exact_match: bool = False) -> str:
    """
    Search for functions by name across all parsed files.

    Use this to find where specific functionality is implemented.

    Args:
        query: Function name or partial name to search for
        exact_match: If True, only return exact name matches

    Returns:
        JSON list of matching functions with their file paths.
    """
    try:
        context = get_analysis_context()

        if not context.codebase or not context.codebase.files:
            return "No codebase data available."

        results = []
        query_lower = query.lower()

        for file_info in context.codebase.files:
            for func_name in file_info.functions:
                if exact_match:
                    if func_name == query:
                        results.append({
                            "function": func_name,
                            "file": file_info.path,
                        })
                else:
                    if query_lower in func_name.lower():
                        results.append({
                            "function": func_name,
                            "file": file_info.path,
                        })

        if not results:
            return f"No functions found matching '{query}'."

        return json.dumps(results, indent=2)

    except Exception as e:
        logger.exception(f"Error in search_functions: {e}")
        return f"Error searching functions: {str(e)}"


@tool
def search_classes(query: str, exact_match: bool = False) -> str:
    """
    Search for classes by name across all parsed files.

    Use this to find where data models or service classes are defined.

    Args:
        query: Class name or partial name to search for
        exact_match: If True, only return exact name matches

    Returns:
        JSON list of matching classes with their file paths.
    """
    try:
        context = get_analysis_context()

        if not context.codebase or not context.codebase.files:
            return "No codebase data available."

        results = []
        query_lower = query.lower()

        for file_info in context.codebase.files:
            for class_name in file_info.classes:
                if exact_match:
                    if class_name == query:
                        results.append({
                            "class": class_name,
                            "file": file_info.path,
                        })
                else:
                    if query_lower in class_name.lower():
                        results.append({
                            "class": class_name,
                            "file": file_info.path,
                        })

        if not results:
            return f"No classes found matching '{query}'."

        return json.dumps(results, indent=2)

    except Exception as e:
        logger.exception(f"Error in search_classes: {e}")
        return f"Error searching classes: {str(e)}"


@tool
def get_function_details(file_path: str, function_name: str) -> str:
    """
    Get detailed information about a specific function.

    Use this after finding a function with search_functions() to get more details.

    Args:
        file_path: Path to the file containing the function
        function_name: Name of the function to inspect

    Returns:
        Function details or error message if not found.
    """
    try:
        context = get_analysis_context()
        file_info = context.get_file(file_path)

        if not file_info:
            return f"File not found: {file_path}"

        if function_name not in file_info.functions:
            return f"Function '{function_name}' not found in {file_path}. Available functions: {file_info.functions}"

        # Return what we know about the function
        result = {
            "function": function_name,
            "file": file_path,
            "exists": True,
            "note": "Full function body not available in parsed data. Consider checking logs for this function's behavior.",
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.exception(f"Error in get_function_details: {e}")
        return f"Error getting function details: {str(e)}"


@tool
def search_files(query: str, exact_match: bool = False) -> str:
    """
    Search for files by name or path pattern.

    Use this to find specific files like routers, models, services, etc.

    Args:
        query: File name or path fragment to search for (e.g., "router.py", "models", "api/")
        exact_match: If True, only return files whose path exactly matches the query

    Returns:
        JSON list of matching files with their function/class counts.
    """
    try:
        context = get_analysis_context()

        if not context.codebase or not context.codebase.files:
            return "No codebase data available."

        query_lower = query.lower()
        results = []

        for file_info in context.codebase.files:
            if exact_match:
                if file_info.path == query:
                    results.append({
                        "path": file_info.path,
                        "functions": file_info.functions,
                        "classes": file_info.classes,
                    })
            else:
                if query_lower in file_info.path.lower():
                    results.append({
                        "path": file_info.path,
                        "functions": len(file_info.functions),
                        "classes": len(file_info.classes),
                    })

        if not results:
            return f"No files found matching '{query}'. Use list_files() to see all available files."

        return json.dumps({
            "total_matching": len(results),
            "files": results[:30],
        }, indent=2)

    except Exception as e:
        logger.exception(f"Error in search_files: {e}")
        return f"Error searching files: {str(e)}"


@tool
def list_files(language: Optional[str] = None, limit: int = 50) -> str:
    """
    List all parsed files in the codebase.

    Use this to understand the codebase structure before diving into specific files.

    Args:
        language: Optional filter by language (e.g., "python", "javascript")
        limit: Maximum number of files to return (default 50)

    Returns:
        JSON list of files with their function/class counts.
    """
    try:
        context = get_analysis_context()

        if not context.codebase or not context.codebase.files:
            return "No codebase data available."

        files = context.codebase.files

        # Filter by language if specified
        # Note: ParsedFileInfo doesn't have language, so we infer from extension
        if language:
            lang_lower = language.lower()
            extension_map = {
                "python": [".py"],
                "javascript": [".js", ".jsx", ".mjs"],
                "typescript": [".ts", ".tsx"],
                "go": [".go"],
                "java": [".java"],
            }
            extensions = extension_map.get(lang_lower, [])
            if extensions:
                files = [f for f in files if any(f.path.endswith(ext) for ext in extensions)]

        results = []
        for f in files[:limit]:
            results.append({
                "path": f.path,
                "functions": len(f.functions),
                "classes": len(f.classes),
            })

        summary = {
            "total_files": len(context.codebase.files),
            "shown": len(results),
            "files": results,
        }

        if context.codebase.languages:
            summary["languages"] = context.codebase.languages

        return json.dumps(summary, indent=2)

    except Exception as e:
        logger.exception(f"Error in list_files: {e}")
        return f"Error listing files: {str(e)}"
