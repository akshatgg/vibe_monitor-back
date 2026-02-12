"""
LangChain tools for RCA agent to interact with GitHub repositories.
"""

import logging
import json
from typing import List, Optional

from langchain.tools import tool

from app.core.database import AsyncSessionLocal
from app.github.tools.router import (
    download_file_by_path,
    get_branch_recent_commits,
    get_repository_commits,
    get_repository_metadata,
    get_repository_tree,
    list_pull_requests,
    read_repository_file,
    search_code,
)
from app.github.tools.service import (
    get_default_branch,
    get_github_integration_with_token,
    get_owner_or_default,
)

logger = logging.getLogger(__name__)


def _format_tool_error(tool_name: str, error: Exception, context: str = "") -> str:
    """
    Format tool errors in a way that helps the LLM understand and recover.

    Returns actionable error messages without exposing internal secrets.
    """
    error_str = str(error)

    # Handle specific error types with helpful suggestions
    if "400" in error_str:
        logger.warning(f"Error in {tool_name}: {error_str}")
        return (
            f"⚠️ {tool_name}: Invalid request. "
            f"The parameters provided for {context or 'this request'} may be incorrect. "
            "Try using 'HEAD:' for the default branch or verify the input format."
        )
    if "404" in error_str:
        logger.warning(f"Error in {tool_name}: {error_str}")
        return (
            f"⚠️ {tool_name}: Resource not found. "
            f"The requested {context or 'resource'} doesn't exist or isn't accessible. "
            "Try using 'HEAD:' as the expression for the default branch, "
            "or verify the repository/file path is correct."
        )
    if "401" in error_str or "403" in error_str:
        logger.warning(f"Error in {tool_name}: {error_str}")
        return (
            f"⚠️ {tool_name}: Access denied. "
            "The GitHub integration may not have permission to access this resource. "
            "Try a different repository or check if the repository is private."
        )
    if "422" in error_str:
        logger.warning(f"Error in {tool_name}: {error_str}")
        return (
            f"⚠️ {tool_name}: Invalid input. "
            f"The {context or 'request'} contains invalid data. "
            "Check that file paths and branch names are correct."
        )
    if "rate limit" in error_str.lower():
        logger.warning(f"Error in {tool_name}: {error_str}")
        return (
            f"⚠️ {tool_name}: GitHub rate limit reached. "
            "Please wait a moment before trying again, or try a different approach."
        )
    if "timeout" in error_str.lower():
        logger.warning(f"Error in {tool_name}: {error_str}")
        return (
            f"⚠️ {tool_name}: Request timed out. "
            "The repository might be large. Try requesting a specific subdirectory instead."
        )

    # Generic fallback - unexpected error, include stack trace
    logger.exception(f"Error in {tool_name}: {error_str}")
    return (
        f"⚠️ {tool_name}: Unable to complete request. "
        "Try a different approach or use alternative tools to gather the information."
    )


def _format_repositories_response(response: dict) -> str:
    """Format repository list response for LLM consumption"""
    try:
        if not response.get("success"):
            return "Failed to fetch repositories."

        repos = response.get("repositories", [])
        if not repos:
            return "No repositories found."

        formatted = []
        for repo in repos[:20]:  # Limit to first 20
            name = repo.get("nameWithOwner", "unknown")
            description = repo.get("description", "No description")
            language = repo.get("primaryLanguage", {}).get("name", "N/A")
            is_private = "Private" if repo.get("isPrivate") else "Public"
            updated = repo.get("updatedAt", "Unknown")

            formatted.append(
                f"📦 **{name}** ({is_private})\n"
                f"   Language: {language}\n"
                f"   Description: {description}\n"
                f"   Last updated: {updated}"
            )

        summary = f"Found {len(repos)} repositories:\n\n" + "\n\n".join(formatted)
        if len(repos) > 20:
            summary += f"\n\n(Showing first 20 repositories. Total: {len(repos)})"

        return summary

    except Exception as e:
        logger.debug(f"Error formatting repositories response: {e}")
        return f"Error parsing repository list: {str(e)}"


def _format_file_content_response(response: dict) -> str:
    """Format file content response for LLM consumption."""
    try:
        if not response.get("success"):
            return json.dumps(
                {
                    "success": False,
                    "error": "Failed to read file",
                }
            )

        content = response.get("content", "") or ""
        file_path = response.get("file_path") or response.get("path") or "unknown"
        byte_size = response.get("byte_size")
        if byte_size is None:
            byte_size = response.get("size")
        if byte_size is None:
            try:
                byte_size = len(content.encode("utf-8"))
            except Exception:
                byte_size = 0

        sha = response.get("sha")
        encoding = response.get("encoding")
        decoded = response.get("content_decoded")

        language = _detect_language(file_path)
        parsed = None
        if content and language:
            try:
                from app.services.rca.tools.code_parser.tools import parse_code

                parsed = parse_code(code=content, language=language)
            except Exception:
                parsed = None

        excerpt_max_chars = 10000
        excerpt = content[:excerpt_max_chars] if content else ""
        if content and len(content) > excerpt_max_chars:
            excerpt = excerpt + "\n... (truncated excerpt)"

        return json.dumps(
            {
                "success": True,
                "file_path": file_path,
                "size_bytes": int(byte_size or 0),
                "language": language,
                "excerpt": excerpt,
                "sha": sha,
                "encoding": encoding,
                "content_decoded": decoded,
                "parsed": parsed,
            },
            indent=2,
        )

    except Exception as e:
        logger.debug(f"Error formatting file content: {e}")
        return json.dumps(
            {"success": False, "error": f"Error parsing file content: {str(e)}"}
        )


def _detect_language(file_path: str) -> Optional[str]:
    path = (file_path or "").lower()
    if path.endswith(".py"):
        return "python"
    if path.endswith(".js"):
        return "javascript"
    if path.endswith(".ts"):
        return "typescript"
    if path.endswith(".tsx"):
        return "typescript"
    if path.endswith(".jsx"):
        return "javascript"
    if path.endswith(".go"):
        return "go"
    if path.endswith(".java"):
        return "java"
    if path.endswith(".rb"):
        return "ruby"
    if path.endswith(".php"):
        return "php"
    return None


def _format_code_search_response(response: dict) -> str:
    """Format code search response for LLM consumption"""
    try:
        if not response.get("success"):
            return "Code search failed."

        total_count = response.get("total_count", 0)
        items = response.get("items", [])

        if total_count == 0:
            return "No code matches found for the search query."

        formatted = []
        for item in items[:15]:  # Limit to first 15 results
            path = item.get("path", "unknown")
            repo_name = item.get("repository", {}).get("full_name", "unknown")

            # Extract text matches
            text_matches = item.get("text_matches", [])
            match_snippets = []
            for match in text_matches[:2]:  # Show first 2 matches per file
                fragment = match.get("fragment", "")
                if fragment:
                    match_snippets.append(f"   `{fragment.strip()}`")

            formatted_item = f"📄 **{path}** (in {repo_name})"
            if match_snippets:
                formatted_item += "\n" + "\n".join(match_snippets)

            formatted.append(formatted_item)

        summary = f"Found {total_count} code matches:\n\n" + "\n\n".join(formatted)
        if total_count > 15:
            summary += f"\n\n(Showing first 15 results. Total matches: {total_count})"

        return summary

    except Exception as e:
        logger.debug(f"Error formatting code search response: {e}")
        return f"Error parsing code search results: {str(e)}"


def _format_commits_response(response: dict) -> str:
    """Format commits response for LLM consumption with PII sanitization."""
    try:
        if not response.get("success"):
            return "Failed to fetch commits."

        commits = response.get("commits", [])
        if not commits:
            return "No commits found."

        formatted = []
        for commit in commits[:20]:  # Limit to first 20 commits
            oid = commit.get("oid", "")[:8]  # Short hash
            message = commit.get("messageHeadline", "No message")
            # GitHub data is from a trusted source - pass through as-is
            # Author names are not masked here to maintain consistency with PIIMapper
            # If masking is needed, it will be done at entry point with PIIMapper
            author_data = commit.get("author", {})
            author_name = author_data.get("name", "Unknown")

            date = commit.get("committedDate", "Unknown date")
            additions = commit.get("additions", 0)
            deletions = commit.get("deletions", 0)

            formatted.append(
                f"🔹 **{oid}** - {message}\n"
                f"   Author: {author_name}\n"
                f"   Date: {date}\n"
                f"   Changes: +{additions}/-{deletions}"
            )

        summary = f"Found {len(commits)} commits:\n\n" + "\n\n".join(formatted)
        if len(commits) > 20:
            summary += "\n\n(Showing first 20 commits)"

        return summary

    except Exception as e:
        logger.debug(f"Error formatting commits response: {e}")
        return f"Error parsing commits: {str(e)}"


def _format_pull_requests_response(response: dict) -> str:
    """Format pull requests response for LLM consumption with PII sanitization."""
    try:
        if not response.get("success"):
            return "Failed to fetch pull requests."

        prs = response.get("pull_requests", [])
        if not prs:
            return "No pull requests found."

        formatted = []
        for pr in prs[:15]:  # Limit to first 15 PRs
            number = pr.get("number", "")
            title = pr.get("title", "No title")
            state = pr.get("state", "UNKNOWN")
            # GitHub data is from a trusted source - pass through as-is
            # Author usernames are public GitHub data, consistent with commit authors
            # If masking is needed, it will be done at entry point with PIIMapper
            author_login = pr.get("author", {}).get("login", "Unknown")
            created = pr.get("createdAt", "Unknown")
            head_ref = pr.get("headRefName", "unknown")
            base_ref = pr.get("baseRefName", "unknown")

            formatted.append(
                f"🔀 **PR #{number}** - {title}\n"
                f"   Status: {state}\n"
                f"   Author: {author_login}\n"
                f"   Branch: {head_ref} → {base_ref}\n"
                f"   Created: {created}"
            )

        summary = f"Found {len(prs)} pull requests:\n\n" + "\n\n".join(formatted)
        if len(prs) > 15:
            summary += "\n\n(Showing first 15 pull requests)"

        return summary

    except Exception as e:
        logger.debug(f"Error formatting pull requests response: {e}")
        return f"Error parsing pull requests: {str(e)}"



@tool
async def read_repository_file_tool(
    workspace_id: str,
    repo_name: str,
    file_path: str,
    owner: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> str:
    """
    Read a specific file from a GitHub repository.

    Use this tool to examine configuration files, code, manifests, logs, or documentation.
    Essential for investigating deployment configurations, environment settings, or recent code changes.

    ⚠️ CRITICAL: repo_name is the GITHUB REPOSITORY name, NOT the service name!
    Use the SERVICE→REPOSITORY mapping to translate. Example:
    - If service is "marketplace-service" and mapping shows {"marketplace-service": "marketplace"}
    - Use repo_name="marketplace", NOT repo_name="marketplace-service"

    **CRITICAL: For Environment-Specific Investigations:**
    When investigating code deployed in a specific environment, ALWAYS use the deployed commit_sha
    from the environment context. This ensures you're reading the ACTUAL deployed code, not HEAD.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        repo_name: GitHub repository name from SERVICE→REPOSITORY mapping (NOT the service name!)
        file_path: Path to the file (e.g., "docker-compose.yml", "src/config.py")
        owner: Repository owner (defaults to workspace's GitHub username)
        commit_sha: Commit SHA or branch name to read from (default: HEAD). Use deployed commit SHA for environment investigations.

    Returns:
        File content with syntax highlighting

    Examples:
        # Read from HEAD (latest code)
        read_repository_file_tool(repo_name="marketplace", file_path="app.py")

        # Read from deployed commit (for environment-specific investigation)
        read_repository_file_tool(repo_name="marketplace", file_path="app.py", commit_sha="ab2f9b1c")
    """
    try:
        async with AsyncSessionLocal() as db:
            # Use commit_sha if provided, otherwise default to HEAD
            ref = commit_sha if commit_sha else "HEAD"

            response = await read_repository_file(
                workspace_id=workspace_id,
                name=repo_name,
                file_path=file_path,
                owner=owner,
                branch=ref,  # 'branch' parameter accepts commit SHA too
                user_id="rca-agent",
                db=db,
            )

            content = response.get("content")
            byte_size = response.get("byte_size")
            if (content is None or content == "") and int(byte_size or 0) > 0:
                integration, _ = await get_github_integration_with_token(
                    workspace_id, db
                )
                resolved_owner = get_owner_or_default(owner, integration)
                fallback_ref = ref
                if not fallback_ref or str(fallback_ref).upper() == "HEAD":
                    fallback_ref = await get_default_branch(
                        workspace_id, repo_name, resolved_owner, db
                    )

                response = await download_file_by_path(
                    workspace_id=workspace_id,
                    repo=repo_name,
                    file_path=file_path,
                    owner=owner,
                    ref=str(fallback_ref),
                    user_id="rca-agent",
                    db=db,
                )
                response["note"] = (
                    "GraphQL blob text unavailable; used Contents API fallback"
                )

        return _format_file_content_response(response)

    except Exception as e:
        return _format_tool_error("read_repository_file", e, f"file '{file_path}'")


@tool
async def search_code_tool(
    workspace_id: str,
    search_query: str,
    repo: Optional[str] = None,
    owner: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> str:
    """
    Search for code across GitHub repositories.

    Use this tool to find specific code patterns, function calls, configuration values,
    or error messages across your codebase. Critical for understanding how features are implemented
    or where specific logic resides.

    ⚠️ CRITICAL: repo is the GITHUB REPOSITORY name, NOT the service name!
    Use the SERVICE→REPOSITORY mapping to translate.

    **LIMITATION:** GitHub's code search API only searches the default branch (HEAD), not specific commits.
    If you need to read specific files from a deployed commit, use read_repository_file_tool with commit_sha instead.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        search_query: Code search query (e.g., "timeout", "database", "api_key")
        repo: GitHub repository name from SERVICE→REPOSITORY mapping (NOT the service name!)
        owner: Repository owner (defaults to workspace's GitHub username)
        per_page: Results per page (default: 30, max: 100)
        page: Page number for pagination (default: 1)

    Returns:
        Formatted list of code matches with file paths and snippets

    Example:
        search_code_tool(search_query="connection timeout", repo="marketplace")
    """
    try:
        async with AsyncSessionLocal() as db:
            response = await search_code(
                workspace_id=workspace_id,
                search_query=search_query,
                owner=owner,
                repo=repo,
                per_page=per_page,
                page=page,
                user_id="rca-agent",
                db=db,
            )

        return _format_code_search_response(response)

    except Exception as e:
        return _format_tool_error("search_code", e, "code search")


@tool
async def get_repository_commits_tool(
    workspace_id: str,
    repo_name: str,
    owner: Optional[str] = None,
    first: int = 30,
    after: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> str:
    """
    Get commit history for a repository.

    Use this tool to investigate recent changes, identify when issues were introduced,
    or understand deployment history. Essential for correlating incidents with code changes.

    ⚠️ CRITICAL: repo_name is the GITHUB REPOSITORY name, NOT the service name!
    Use the SERVICE→REPOSITORY mapping to translate.

    **WHEN ASKING ABOUT DEPLOYED CODE:**
    If the user asks about code that's deployed in an environment (e.g., "commits on deployed code",
    "what changed in test environment"), you MUST:
    1. Check the deployed commit SHA from the environment context
    2. Use the commit_sha parameter to fetch commits UP TO that deployment
    3. This ensures you show only commits that are actually deployed, not future commits

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        repo_name: GitHub repository name from SERVICE→REPOSITORY mapping (NOT the service name!)
        owner: Repository owner (defaults to workspace's GitHub username)
        first: Number of commits to fetch (default: 30)
        after: Cursor for pagination (optional)
        commit_sha: Optional commit SHA to start from (use for deployed code queries)

    Returns:
        Formatted list of commits with messages, authors, dates, and change statistics

    Examples:
        # Get latest commits from HEAD
        get_repository_commits_tool(repo_name="marketplace", first=20)

        # Get commits up to a deployed commit (for environment-specific queries)
        get_repository_commits_tool(repo_name="marketplace", first=5, commit_sha="ab2f9b1c")
    """
    try:
        async with AsyncSessionLocal() as db:
            response = await get_repository_commits(
                workspace_id=workspace_id,
                name=repo_name,
                owner=owner,
                first=first,
                after=after,
                user_id="rca-agent",
                db=db,
                commit_sha=commit_sha,
            )

        return _format_commits_response(response)

    except Exception as e:
        return _format_tool_error("get_repository_commits", e, "commit history")


@tool
async def list_pull_requests_tool(
    workspace_id: str,
    repo_name: str,
    owner: Optional[str] = None,
    states: Optional[List[str]] = None,
    first: int = 20,
    after: Optional[str] = None,
) -> str:
    """
    List pull requests for a repository.

    Use this tool to identify recent deployments, ongoing development work,
    or investigate which PRs might have introduced issues.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        repo_name: GitHub repository name from SERVICE→REPOSITORY mapping (NOT the service name!)
        owner: Repository owner (defaults to workspace's GitHub username)
        states: PR states to filter by - ["OPEN", "CLOSED", "MERGED"] (default: all states)
        first: Number of PRs to fetch (default: 20)
        after: Cursor for pagination (optional)

    Returns:
        Formatted list of pull requests with status, authors, and branch info

    Example:
        list_pull_requests_tool(repo_name="marketplace", states=["MERGED"], first=10)
    """
    try:
        async with AsyncSessionLocal() as db:
            response = await list_pull_requests(
                workspace_id=workspace_id,
                name=repo_name,
                owner=owner,
                states=states,
                first=first,
                after=after,
                user_id="rca-agent",
                db=db,
            )

        return _format_pull_requests_response(response)

    except Exception as e:
        return _format_tool_error("list_pull_requests", e, "pull requests")




def _format_tree_response(response: dict) -> str:
    """Format repository tree response for LLM consumption with secret sanitization."""
    try:
        if not response.get("success"):
            return "Failed to fetch repository tree."

        data = response.get("data", {})
        expression = response.get("expression", "unknown")

        # Check if it's a blob (file) or tree (directory)
        if data.get("__typename") == "Blob":
            # It's a file
            byte_size = data.get("byteSize", 0)
            text = data.get("text", "")

            if not text:
                return f"File at expression '{expression}' is empty."

            # Truncate very large files
            max_chars = 10000
            if len(text) > max_chars:
                text = (
                    text[:max_chars]
                    + f"\n\n... (truncated, total size: {byte_size} bytes)"
                )

            return f"File: {expression}\nSize: {byte_size} bytes\n\n```\n{text}\n```"

        # It's a tree (directory)
        entries = data.get("entries", [])
        if not entries:
            return f"Directory at expression '{expression}' is empty."

        formatted = []
        for entry in entries[:100]:  # Limit to first 100 entries
            name = entry.get("name", "unknown")
            entry_type = entry.get("type", "unknown")
            icon = "📁" if entry_type == "tree" else "📄"

            formatted.append(f"{icon} {name} ({entry_type})")

        summary = f"Directory tree for '{expression}':\n\n" + "\n".join(formatted)
        if len(entries) > 100:
            summary += f"\n\n(Showing first 100 entries. Total: {len(entries)})"

        return summary

    except Exception as e:
        logger.debug(f"Error formatting tree response: {e}")
        return f"Error parsing repository tree: {str(e)}"


def _format_metadata_response(response: dict) -> str:
    """Format repository metadata response for LLM consumption"""
    try:
        if not response.get("success"):
            return "Failed to fetch repository metadata."

        repo_name = response.get("name", "unknown")
        owner = response.get("owner", "unknown")
        languages_data = response.get("languages", {})
        topics = response.get("topics", [])

        formatted = [f"Repository: {owner}/{repo_name}\n"]

        # Format languages
        edges = languages_data.get("edges", [])
        total_size = languages_data.get("total_size", 0)

        if edges:
            formatted.append("**Languages:**")
            for edge in edges[:10]:  # Show top 10 languages
                size = edge.get("size", 0)
                node = edge.get("node", {})
                name = node.get("name", "Unknown")

                # Calculate percentage
                percentage = (size / total_size * 100) if total_size > 0 else 0

                formatted.append(f"  • {name}: {percentage:.1f}% ({size:,} bytes)")

            formatted.append(
                f"\nTotal: {total_size:,} bytes across {languages_data.get('total_count', 0)} languages"
            )
        else:
            formatted.append("**Languages:** None detected")

        # Format topics
        if topics:
            formatted.append(f"\n**Topics:** {', '.join(topics)}")
        else:
            formatted.append("\n**Topics:** None")

        return "\n".join(formatted)

    except Exception as e:
        logger.debug(f"Error formatting metadata response: {e}")
        return f"Error parsing repository metadata: {str(e)}"


@tool
async def get_repository_tree_tool(
    workspace_id: str,
    repo_name: str,
    expression: str = "HEAD:",
    owner: Optional[str] = None,
) -> str:
    """
    Read repository files and directory structure.

    Use this tool to explore repository structure, find file locations,
    or understand the codebase organization. The expression parameter lets you
    navigate directories and view file contents.

    Use deployed commit SHA in expression for environment-specific investigations.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        repo_name: GitHub repository name from SERVICE→REPOSITORY mapping
        expression: Git expression to query (default: "HEAD:")
            - "HEAD:" or "main:" - Root/branch directory
            - "abc123:" - Specific commit directory
            - "HEAD:src/" - Subdirectory
            - "HEAD:src/config.py" - Specific file
        owner: Repository owner (defaults to workspace's GitHub username)

    Returns:
        Directory listing or file content depending on expression

    Example:
        get_repository_tree_tool(repo_name="marketplace", expression="ab2f9b1c:src/")
    """
    try:
        async with AsyncSessionLocal() as db:
            response = await get_repository_tree(
                workspace_id=workspace_id,
                name=repo_name,
                expression=expression,
                owner=owner,
                user_id="rca-agent",
                db=db,
            )

        return _format_tree_response(response)

    except Exception as e:
        return _format_tool_error("get_repository_tree", e, f"path '{expression}'")


@tool
async def get_branch_recent_commits_tool(
    workspace_id: str,
    repo_name: str,
    ref: str = "refs/heads/main",
    owner: Optional[str] = None,
    first: int = 20,
) -> str:
    """
    Get recent commits from a specific branch.

    Use this to investigate changes on a specific branch,
    particularly useful for comparing feature branches or release branches
    to understand what changes are about to be deployed.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        repo_name: GitHub repository name from SERVICE→REPOSITORY mapping
        ref: Branch reference (default: "refs/heads/main")
            - "refs/heads/main" - Main branch
            - "refs/heads/develop" - Develop branch
            - "refs/heads/feature/new-auth" - Feature branch
        owner: Repository owner (defaults to workspace's GitHub username)
        first: Number of commits to fetch (default: 20)

    Returns:
        Formatted list of recent commits from the specified branch

    Example:
        get_branch_recent_commits_tool(repo_name="marketplace", ref="refs/heads/develop", first=10)
    """
    try:
        async with AsyncSessionLocal() as db:
            response = await get_branch_recent_commits(
                workspace_id=workspace_id,
                name=repo_name,
                ref=ref,
                owner=owner,
                first=first,
                after=None,
                user_id="rca-agent",
                db=db,
            )

        return _format_commits_response(response)

    except Exception as e:
        return _format_tool_error("get_branch_recent_commits", e, f"branch '{ref}'")


@tool
async def get_repository_metadata_tool(
    workspace_id: str,
    repo_name: str,
    owner: Optional[str] = None,
    first: int = 12,
) -> str:
    """
    Get repository metadata including languages and topics.

    Use this to understand what technologies a repository uses (programming languages,
    frameworks) or to identify repositories by their topics/tags.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        repo_name: GitHub repository name from SERVICE→REPOSITORY mapping
        owner: Repository owner (defaults to workspace's GitHub username)
        first: Number of languages to fetch (default: 12)

    Returns:
        Repository languages with percentages and topics/tags

    Example:
        get_repository_metadata_tool(repo_name="marketplace")
    """
    try:
        async with AsyncSessionLocal() as db:
            response = await get_repository_metadata(
                workspace_id=workspace_id,
                name=repo_name,
                owner=owner,
                first=first,
                user_id="rca-agent",
                db=db,
            )

        return _format_metadata_response(response)

    except Exception as e:
        return _format_tool_error("get_repository_metadata", e, "repository metadata")
