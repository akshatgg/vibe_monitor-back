"""
LangChain tools for RCA agent to interact with GitHub repositories
"""

import logging
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
    list_repositories_graphql,
    read_repository_file,
    search_code,
)

logger = logging.getLogger(__name__)


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
        logger.error(f"Error formatting repositories response: {e}")
        return f"Error parsing repository list: {str(e)}"


def _format_file_content_response(response: dict) -> str:
    """Format file content response for LLM consumption"""
    try:
        if not response.get("success"):
            return "Failed to read file."

        content = response.get("content", "")
        file_path = response.get("file_path", "unknown")
        byte_size = response.get("byte_size", 0)

        if not content:
            return f"File '{file_path}' is empty."

        # Truncate very large files
        max_chars = 10000
        if len(content) > max_chars:
            content = (
                content[:max_chars]
                + f"\n\n... (truncated, total size: {byte_size} bytes)"
            )

        return f"File: {file_path}\nSize: {byte_size} bytes\n\n```\n{content}\n```"

    except Exception as e:
        logger.error(f"Error formatting file content: {e}")
        return f"Error parsing file content: {str(e)}"


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
        logger.error(f"Error formatting code search response: {e}")
        return f"Error parsing code search results: {str(e)}"


def _format_commits_response(response: dict) -> str:
    """Format commits response for LLM consumption"""
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
            author = commit.get("author", {}).get("name", "Unknown")
            date = commit.get("committedDate", "Unknown date")
            additions = commit.get("additions", 0)
            deletions = commit.get("deletions", 0)

            formatted.append(
                f"🔹 **{oid}** - {message}\n"
                f"   Author: {author}\n"
                f"   Date: {date}\n"
                f"   Changes: +{additions}/-{deletions}"
            )

        summary = f"Found {len(commits)} commits:\n\n" + "\n\n".join(formatted)
        if len(commits) > 20:
            summary += "\n\n(Showing first 20 commits)"

        return summary

    except Exception as e:
        logger.error(f"Error formatting commits response: {e}")
        return f"Error parsing commits: {str(e)}"


def _format_pull_requests_response(response: dict) -> str:
    """Format pull requests response for LLM consumption"""
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
            author = pr.get("author", {}).get("login", "Unknown")
            created = pr.get("createdAt", "Unknown")
            head_ref = pr.get("headRefName", "unknown")
            base_ref = pr.get("baseRefName", "unknown")

            formatted.append(
                f"🔀 **PR #{number}** - {title}\n"
                f"   Status: {state}\n"
                f"   Author: {author}\n"
                f"   Branch: {head_ref} → {base_ref}\n"
                f"   Created: {created}"
            )

        summary = f"Found {len(prs)} pull requests:\n\n" + "\n\n".join(formatted)
        if len(prs) > 15:
            summary += "\n\n(Showing first 15 pull requests)"

        return summary

    except Exception as e:
        logger.error(f"Error formatting pull requests response: {e}")
        return f"Error parsing pull requests: {str(e)}"


@tool
async def list_repositories_tool(
    workspace_id: str,
    first: int = 50,
    after: Optional[str] = None,
) -> str:
    """
    List GitHub repositories accessible in the workspace.

    Use this tool to discover available repositories for code analysis or investigation.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        first: Number of repositories to fetch (default: 50)
        after: Cursor for pagination (optional)

    Returns:
        Formatted list of repositories with names, descriptions, and languages

    Example:
        list_repositories_tool(first=20)
    """
    try:
        async with AsyncSessionLocal() as db:
            # Use a dummy user_id since we're in agent context
            # The workspace_id is pre-bound, so we just need a valid user
            # In practice, the workspace itself provides the authorization
            response = await list_repositories_graphql(
                workspace_id=workspace_id,
                first=first,
                after=after,
                user_id="rca-agent",  # Placeholder for agent context
                db=db,
            )

        return _format_repositories_response(response)

    except Exception as e:
        logger.error(f"Error in list_repositories_tool: {e}")
        return f"Error fetching repositories: {str(e)}"


@tool
async def read_repository_file_tool(
    workspace_id: str,
    repo_name: str,
    file_path: str,
    owner: Optional[str] = None,
    branch: str = "HEAD",
) -> str:
    """
    Read a specific file from a GitHub repository.

    Use this tool to examine configuration files, code, manifests, logs, or documentation.
    Essential for investigating deployment configurations, environment settings, or recent code changes.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        repo_name: Repository name (e.g., "my-api-service")
        file_path: Path to the file (e.g., "docker-compose.yml", "src/config.py")
        owner: Repository owner (defaults to workspace's GitHub username)
        branch: Branch name (default: "HEAD" for current branch)

    Returns:
        File content with syntax highlighting

    Example:
        read_repository_file_tool(repo_name="api-service", file_path="Dockerfile", branch="main")
    """
    try:
        async with AsyncSessionLocal() as db:
            response = await read_repository_file(
                workspace_id=workspace_id,
                name=repo_name,
                file_path=file_path,
                owner=owner,
                branch=branch,
                user_id="rca-agent",
                db=db,
            )

        return _format_file_content_response(response)

    except Exception as e:
        logger.error(f"Error in read_repository_file_tool: {e}")
        return f"Error reading file '{file_path}': {str(e)}"


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

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        search_query: Code search query (e.g., "timeout", "database", "api_key")
        repo: Specific repository name (optional, searches all repos if not provided)
        owner: Repository owner (defaults to workspace's GitHub username)
        per_page: Results per page (default: 30, max: 100)
        page: Page number for pagination (default: 1)

    Returns:
        Formatted list of code matches with file paths and snippets

    Example:
        search_code_tool(search_query="connection timeout", repo="api-service")
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
        logger.error(f"Error in search_code_tool: {e}")
        return f"Error searching code: {str(e)}"


@tool
async def get_repository_commits_tool(
    workspace_id: str,
    repo_name: str,
    owner: Optional[str] = None,
    first: int = 30,
    after: Optional[str] = None,
) -> str:
    """
    Get recent commit history for a repository.

    Use this tool to investigate recent changes, identify when issues were introduced,
    or understand deployment history. Essential for correlating incidents with code changes.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        repo_name: Repository name
        owner: Repository owner (defaults to workspace's GitHub username)
        first: Number of commits to fetch (default: 30)
        after: Cursor for pagination (optional)

    Returns:
        Formatted list of commits with messages, authors, dates, and change statistics

    Example:
        get_repository_commits_tool(repo_name="api-service", first=20)
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
            )

        return _format_commits_response(response)

    except Exception as e:
        logger.error(f"Error in get_repository_commits_tool: {e}")
        return f"Error fetching commits: {str(e)}"


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
        repo_name: Repository name
        owner: Repository owner (defaults to workspace's GitHub username)
        states: PR states to filter by - ["OPEN", "CLOSED", "MERGED"] (default: all states)
        first: Number of PRs to fetch (default: 20)
        after: Cursor for pagination (optional)

    Returns:
        Formatted list of pull requests with status, authors, and branch info

    Example:
        list_pull_requests_tool(repo_name="api-service", states=["MERGED"], first=10)
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
        logger.error(f"Error in list_pull_requests_tool: {e}")
        return f"Error fetching pull requests: {str(e)}"


@tool
async def download_file_tool(
    workspace_id: str,
    repo_name: str,
    file_path: str,
    owner: Optional[str] = None,
    ref: Optional[str] = None,
) -> str:
    """
    Download and read a file from a GitHub repository using the Contents API.

    Alternative to read_repository_file_tool that uses REST API instead of GraphQL.
    Useful for fetching binary files or when GraphQL access is limited.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        repo_name: Repository name
        file_path: Path to the file in the repository
        owner: Repository owner (defaults to workspace's GitHub username)
        ref: Branch, tag, or commit ref (defaults to default branch)

    Returns:
        File content (automatically decoded from base64 to UTF-8)

    Example:
        download_file_tool(repo_name="api-service", file_path="config/app.yaml")
    """
    try:
        async with AsyncSessionLocal() as db:
            response = await download_file_by_path(
                workspace_id=workspace_id,
                repo=repo_name,
                file_path=file_path,
                owner=owner,
                ref=ref,
                user_id="rca-agent",
                db=db,
            )

        return _format_file_content_response(response)

    except Exception as e:
        logger.error(f"Error in download_file_tool: {e}")
        return f"Error downloading file '{file_path}': {str(e)}"


def _format_tree_response(response: dict) -> str:
    """Format repository tree response for LLM consumption"""
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
        logger.error(f"Error formatting tree response: {e}")
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
        logger.error(f"Error formatting metadata response: {e}")
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

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        repo_name: Repository name
        expression: Git expression to query (default: "HEAD:")
            - "HEAD:" - Root directory of default branch
            - "main:" - Root directory of main branch
            - "HEAD:src/" - Contents of src directory
            - "HEAD:src/config.py" - Specific file content
        owner: Repository owner (defaults to workspace's GitHub username)

    Returns:
        Directory listing or file content depending on expression

    Example:
        get_repository_tree_tool(repo_name="api-service", expression="HEAD:src/")
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
        logger.error(f"Error in get_repository_tree_tool: {e}")
        return f"Error fetching repository tree for expression '{expression}': {str(e)}"


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
        repo_name: Repository name
        ref: Branch reference (default: "refs/heads/main")
            - "refs/heads/main" - Main branch
            - "refs/heads/develop" - Develop branch
            - "refs/heads/feature/new-auth" - Feature branch
        owner: Repository owner (defaults to workspace's GitHub username)
        first: Number of commits to fetch (default: 20)

    Returns:
        Formatted list of recent commits from the specified branch

    Example:
        get_branch_recent_commits_tool(repo_name="api-service", ref="refs/heads/develop", first=10)
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
        logger.error(f"Error in get_branch_recent_commits_tool: {e}")
        return f"Error fetching commits from branch '{ref}': {str(e)}"


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
    frameworks) or to identify repositories by their topics/tags. Helpful for
    understanding the tech stack when investigating issues.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        repo_name: Repository name
        owner: Repository owner (defaults to workspace's GitHub username)
        first: Number of languages to fetch (default: 12)

    Returns:
        Repository languages with percentages and topics/tags

    Example:
        get_repository_metadata_tool(repo_name="api-service")
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
        logger.error(f"Error in get_repository_metadata_tool: {e}")
        return f"Error fetching repository metadata: {str(e)}"
