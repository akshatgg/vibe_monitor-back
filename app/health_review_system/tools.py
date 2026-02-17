"""
Tools for the health review verification agent.

These tools let the LLM read file content from the parsed_files table
(already fetched from GitHub) without making additional API calls.
Tools are bound with repository_id and db at graph creation time —
the LLM only sees file_path / query / pattern parameters.
"""

import logging
from typing import Optional

from langchain_core.tools import tool
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import ParsedFile

logger = logging.getLogger(__name__)



@tool
async def read_file(
    file_path: str,
    repository_id: str = "",
    db: Optional[AsyncSession] = None,
) -> str:
    """Read the full content of a file from the parsed repository.

    Use this to read source files like main.py, middleware files,
    instrumentation files, or any file you need to inspect.

    Args:
        file_path: Path to the file within the repository (e.g., 'app/main.py')
    """
    if not db or not repository_id:
        return "Error: tool not properly configured"

    logger.info(f"[LLM][read_file] Reading: {file_path}")

    result = await db.execute(
        select(ParsedFile.content, ParsedFile.language, ParsedFile.line_count).where(
            ParsedFile.repository_id == repository_id,
            ParsedFile.file_path == file_path,
        )
    )
    row = result.first()

    if not row or not row[0]:
        logger.info(f"[LLM][read_file] Not found: {file_path}")
        return f"File not found: {file_path}"

    content = row[0]
    language = row[1]
    line_count = row[2]

    # Truncate very large files to stay within context limits
    max_chars = 15000
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars] + f"\n\n... [truncated at {max_chars} chars, file has {line_count} lines]"

    logger.info(
        f"[LLM][read_file] Found: {file_path} ({language}, {line_count} lines, "
        f"{len(content)} chars{', truncated' if truncated else ''})"
    )
    return f"=== {file_path} ({language}, {line_count} lines) ===\n{content}"


@tool
async def search_files(
    query: str,
    repository_id: str = "",
    db: Optional[AsyncSession] = None,
) -> str:
    """Search parsed files for a keyword in their content.

    Returns matching file paths with a snippet of the matching line.
    Use this to find files containing middleware registration, metrics setup,
    event listeners, or other patterns.

    Args:
        query: Keyword to search for in file content (e.g., 'add_middleware', 'HTTPMetrics')
    """
    if not db or not repository_id:
        return "Error: tool not properly configured"

    logger.info(f"[LLM][search_files] Searching for: '{query}'")

    limit = settings.HEALTH_REVIEW_SEARCH_RESULTS_LIMIT

    # Use ILIKE for case-insensitive search with context
    result = await db.execute(
        text("""
            SELECT file_path, language, line_count,
                   substring(content from position(lower(:query) in lower(content)) - 50 for 200) as snippet
            FROM parsed_files
            WHERE repository_id = :repo_id
              AND content ILIKE :pattern
            ORDER BY file_path
            LIMIT :lim
        """),
        {
            "repo_id": repository_id,
            "query": query,
            "pattern": f"%{query}%",
            "lim": limit,
        },
    )
    rows = result.fetchall()

    if not rows:
        logger.info(f"[LLM][search_files] No results for: '{query}'")
        return f"No files found containing '{query}'"

    logger.info(f"[LLM][search_files] Found {len(rows)} files for: '{query}'")
    lines = [f"Found {len(rows)} file(s) containing '{query}':\n"]
    for row in rows:
        snippet = (row[3] or "").strip().replace("\n", " ")
        lines.append(f"  {row[0]} ({row[1]}, {row[2]} lines)")
        if snippet:
            lines.append(f"    ...{snippet}...")
    return "\n".join(lines)


@tool
async def list_files(
    pattern: str,
    repository_id: str = "",
    db: Optional[AsyncSession] = None,
) -> str:
    """List file paths matching a pattern in the repository.

    Use this to find middleware files, config files, or instrumentation modules.
    Supports SQL LIKE patterns: use % for wildcards.

    Args:
        pattern: Path pattern to match (e.g., '%middleware%', 'app/core/%', '%/main.py')
    """
    if not db or not repository_id:
        return "Error: tool not properly configured"

    logger.info(f"[LLM][list_files] Pattern: '{pattern}'")

    # Convert glob-style patterns to SQL LIKE
    sql_pattern = pattern.replace("*", "%")

    result = await db.execute(
        select(ParsedFile.file_path, ParsedFile.language, ParsedFile.line_count)
        .where(
            ParsedFile.repository_id == repository_id,
            ParsedFile.file_path.ilike(sql_pattern),
        )
        .order_by(ParsedFile.file_path)
        .limit(50)
    )
    rows = result.fetchall()

    if not rows:
        logger.info(f"[LLM][list_files] No matches for: '{pattern}'")
        return f"No files matching pattern '{pattern}'"

    logger.info(f"[LLM][list_files] Found {len(rows)} files for: '{pattern}'")
    lines = [f"Found {len(rows)} file(s) matching '{pattern}':\n"]
    for row in rows:
        lines.append(f"  {row[0]} ({row[1]}, {row[2]} lines)")
    return "\n".join(lines)
