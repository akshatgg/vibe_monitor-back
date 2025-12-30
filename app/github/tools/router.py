import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.google.service import AuthService
from ...core.config import settings
from ...core.database import get_db
from .service import (
    execute_github_graphql,
    execute_github_rest_api,
    get_default_branch,
    get_github_integration_with_token,
    get_owner_or_default,
    verify_workspace_access,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github-tools", tags=["github-tools"])
auth_service = AuthService()


# ==================== STANDALONE FUNCTIONS ====================
# These functions can be called directly without FastAPI dependencies
# =========================================================


async def list_repositories_graphql(
    workspace_id: str, first: int, after: Optional[str], user_id: str, db: AsyncSession
):
    """
    List all repositories using GitHub GraphQL API

    This function uses GraphQL to fetch repositories that the authenticated user can access.
    Supports pagination through the 'after' cursor parameter.
    """
    # Verify user has access to this workspace
    await verify_workspace_access(user_id, workspace_id, db)

    # Get integration and access token
    _, access_token = await get_github_integration_with_token(workspace_id, db)

    # GraphQL query
    query = """
    query ViewerRepositoriesAll(
      $first: Int = 100,
      $after: String,
      $affiliations: [RepositoryAffiliation!] = [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]
    ) {
      viewer {
        login
        name
        repositories(
          first: $first
          after: $after
          affiliations: $affiliations
          orderBy: { field: UPDATED_AT, direction: DESC }
        ) {
          nodes {
            name
            nameWithOwner
            description
            isPrivate
            visibility
            isFork
            createdAt
            updatedAt
            primaryLanguage { name color }
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    """

    variables = {
        "first": first,
        "after": after,
        "affiliations": ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"],
    }

    # Execute GraphQL query
    data = await execute_github_graphql(query, variables, access_token)

    viewer_data = data.get("data", {}).get("viewer", {})
    repos_data = viewer_data.get("repositories", {})

    return {
        "success": True,
        "viewer": {"login": viewer_data.get("login"), "name": viewer_data.get("name")},
        "repositories": repos_data.get("nodes", []),
        "pageInfo": repos_data.get("pageInfo", {}),
    }


async def get_repository_tree(
    workspace_id: str,
    name: str,
    owner: Optional[str],
    expression: str,
    user_id: str,
    db: AsyncSession,
):
    """
    Read repository files and directory structure using GitHub GraphQL API

    This function fetches repository tree structure, files, and their contents.
    """
    # Verify user has access to this workspace
    await verify_workspace_access(user_id, workspace_id, db)

    # Get integration and access token
    integration, access_token = await get_github_integration_with_token(
        workspace_id, db
    )

    # Use GitHub integration username as default owner if not provided
    owner = get_owner_or_default(owner, integration)

    # GraphQL query for repository tree
    query = """
    query RepoTree(
      $owner: String!
      $name: String!
      $expression: String!
    ) {
      repository(owner: $owner, name: $name) {
        object(expression: $expression) {
          ... on Tree {
            entries {
              name
              type
              object {
                __typename

                ... on Tree { entries { name type } }
              }
            }
          }
          ... on Blob { byteSize text }
        }
      }
    }
    """

    variables = {"owner": owner, "name": name, "expression": expression}

    # Execute GraphQL query
    data = await execute_github_graphql(query, variables, access_token)

    repository_data = data.get("data", {}).get("repository", {})
    object_data = repository_data.get("object")

    if not object_data:
        raise HTTPException(
            status_code=404,
            detail=f"Expression '{expression}' not found in repository {owner}/{name}",
        )

    return {
        "success": True,
        "owner": owner,
        "name": name,
        "expression": expression,
        "data": object_data,
    }


async def read_repository_file(
    workspace_id: str,
    name: str,
    file_path: str,
    owner: Optional[str],
    branch: str,
    user_id: str,
    db: AsyncSession,
):
    """
    Read a specific file from a repository using GitHub GraphQL API

    This function reads file contents (code, configs, manifests, OpenAPI, logs, etc.).
    Expression is built from branch and file_path (e.g., "HEAD:package.json")
    """
    # Verify user has access to this workspace
    await verify_workspace_access(user_id, workspace_id, db)

    # Get integration and access token
    integration, access_token = await get_github_integration_with_token(
        workspace_id, db
    )

    # Use GitHub integration username as default owner if not provided
    owner = get_owner_or_default(owner, integration)

    # Build expression from branch and file_path
    expression = f"{branch}:{file_path}"

    # GraphQL query for reading file
    query = """
    query ReadFile($owner: String!, $name: String!, $expression: String!) {
      repository(owner: $owner, name: $name) {
        object(expression: $expression) {
          __typename
          ... on Blob {
            byteSize
            text
          }
        }
      }
    }
    """

    variables = {"owner": owner, "name": name, "expression": expression}

    # Execute GraphQL query
    data = await execute_github_graphql(query, variables, access_token)

    repository_data = data.get("data", {}).get("repository", {})
    object_data = repository_data.get("object")

    if not object_data:
        raise HTTPException(
            status_code=404,
            detail=f"File '{file_path}' not found in repository {owner}/{name} on branch {branch}",
        )

    # Check if it's a blob (file)
    if object_data.get("__typename") != "Blob":
        raise HTTPException(
            status_code=400,
            detail=f"'{file_path}' is not a file (type: {object_data.get('__typename')})",
        )

    return {
        "success": True,
        "owner": owner,
        "name": name,
        "branch": branch,
        "file_path": file_path,
        "expression": expression,
        "byte_size": object_data.get("byteSize"),
        "content": object_data.get("text"),
    }


async def get_branch_recent_commits(
    workspace_id: str,
    name: str,
    owner: Optional[str],
    ref: str,
    first: int,
    after: Optional[str],
    user_id: str,
    db: AsyncSession,
):
    """
    Get recent commits from a specific branch using GitHub GraphQL API

    This function fetches recent commit history from a specified branch reference.
    """
    # Verify user has access to this workspace
    await verify_workspace_access(user_id, workspace_id, db)

    # Get integration and access token
    integration, access_token = await get_github_integration_with_token(
        workspace_id, db
    )

    # Use GitHub integration username as default owner if not provided
    owner = get_owner_or_default(owner, integration)

    # GraphQL query for branch recent commits
    query = """
    query BranchRecentCommits(
      $owner: String!
      $name: String!
      $ref: String! = "refs/heads/main"
      $first: Int = 20
      $after: String
    ) {
      repository(owner: $owner, name: $name) {
        branch: ref(qualifiedName: $ref) {
          target {
            ... on Commit {
              recent: history(first: $first, after: $after) {
                pageInfo {
                  hasNextPage
                  endCursor
                }
                nodes {
                  oid
                  committedDate
                  messageHeadline
                  url
                  author {
                    name
                    email
                    user {
                      login
                    }
                  }
                  additions
                  deletions
                  changedFiles
                }
              }
            }
          }
        }
      }
    }
    """

    variables = {
        "owner": owner,
        "name": name,
        "ref": ref,
        "first": first,
        "after": after,
    }

    # Execute GraphQL query
    data = await execute_github_graphql(query, variables, access_token)

    repository_data = data.get("data", {}).get("repository", {})
    branch_data = repository_data.get("branch")

    if not branch_data:
        raise HTTPException(
            status_code=404,
            detail=f"Branch reference '{ref}' not found in repository {owner}/{name}",
        )

    target_data = branch_data.get("target", {})
    recent_data = target_data.get("recent", {})

    return {
        "success": True,
        "owner": owner,
        "name": name,
        "ref": ref,
        "commits": recent_data.get("nodes", []),
        "pageInfo": recent_data.get("pageInfo", {}),
    }


async def get_repository_commits(
    workspace_id: str,
    name: str,
    owner: Optional[str],
    first: int,
    after: Optional[str],
    user_id: str,
    db: AsyncSession,
):
    """
    Get all commit history for a repository using GitHub GraphQL API

    This function fetches all commits from the repository's default branch.
    """
    # Verify user has access to this workspace
    await verify_workspace_access(user_id, workspace_id, db)

    # Get integration and access token
    integration, access_token = await get_github_integration_with_token(
        workspace_id, db
    )

    # Use GitHub integration username as default owner if not provided
    owner = get_owner_or_default(owner, integration)

    # GraphQL query for all repository commits
    query = """
    query RepoHistory(
      $owner: String!
      $name: String!
      $first: Int = 50
      $after: String
    ) {
      repository(owner: $owner, name: $name) {
        defaultBranchRef {
          name
          target {
            ... on Commit {
              history(first: $first, after: $after) {
                pageInfo {
                  hasNextPage
                  endCursor
                }
                nodes {
                  oid
                  messageHeadline
                  committedDate
                  url
                  author {
                    name
                    email
                    user {
                      login
                    }
                  }
                  additions
                  deletions
                  changedFiles
                }
              }
            }
          }
        }
      }
    }
    """

    variables = {"owner": owner, "name": name, "first": first, "after": after}

    # Execute GraphQL query
    data = await execute_github_graphql(query, variables, access_token)

    repository_data = data.get("data", {}).get("repository", {})
    default_branch_ref = repository_data.get("defaultBranchRef")

    if not default_branch_ref:
        raise HTTPException(
            status_code=404,
            detail=f"No default branch found for repository {owner}/{name}",
        )

    branch_name = default_branch_ref.get("name")
    target_data = default_branch_ref.get("target", {})
    history_data = target_data.get("history", {})

    return {
        "success": True,
        "owner": owner,
        "name": name,
        "default_branch": branch_name,
        "commits": history_data.get("nodes", []),
        "pageInfo": history_data.get("pageInfo", {}),
    }


async def list_pull_requests(
    workspace_id: str,
    name: str,
    owner: Optional[str],
    states: Optional[List[str]],
    first: int,
    after: Optional[str],
    user_id: str,
    db: AsyncSession,
):
    """
    List Pull Requests for a repository using GitHub GraphQL API

    This function fetches pull requests with various states (OPEN, CLOSED, MERGED).
    """
    # Verify user has access to this workspace
    await verify_workspace_access(user_id, workspace_id, db)

    # Get integration and access token
    integration, access_token = await get_github_integration_with_token(
        workspace_id, db
    )

    # Use GitHub integration username as default owner if not provided
    owner = get_owner_or_default(owner, integration)

    # If states not provided or empty, use all states
    if not states:
        states = ["OPEN", "CLOSED", "MERGED"]
    else:
        # Validate states
        valid_states = ["OPEN", "CLOSED", "MERGED"]
        for state in states:
            if state.upper() not in valid_states:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid state: {state}. Valid states are: {', '.join(valid_states)}",
                )

        # Convert states to uppercase
        states = [state.upper() for state in states]

    # GraphQL query for listing Pull Requests
    query = """
    query ListPRs(
      $owner: String!
      $name: String!
      $states: [PullRequestState!] = [OPEN]
      $first: Int = 20
      $after: String
    ) {
      repository(owner: $owner, name: $name) {
        pullRequests(first: $first, after: $after, states: $states, orderBy: {field: UPDATED_AT, direction: DESC}) {
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            number
            title
            url
            state
            createdAt
            updatedAt
            mergedAt
            author {
              login
            }
            headRefName
            baseRefName
            reviewDecision
            mergeable
            labels(first: 10) {
              nodes {
                name
              }
            }
            files(first: 1) {
              totalCount
            }
            comments(first: 1) {
              totalCount
            }
            commits(first: 1) {
              totalCount
            }
          }
        }
      }
    }
    """

    variables = {
        "owner": owner,
        "name": name,
        "states": states,
        "first": first,
        "after": after,
    }

    # Execute GraphQL query
    data = await execute_github_graphql(query, variables, access_token)

    repository_data = data.get("data", {}).get("repository", {})
    pull_requests_data = repository_data.get("pullRequests", {})

    return {
        "success": True,
        "owner": owner,
        "name": name,
        "states": states,
        "pull_requests": pull_requests_data.get("nodes", []),
        "pageInfo": pull_requests_data.get("pageInfo", {}),
    }


async def get_repository_metadata(
    workspace_id: str,
    name: str,
    owner: Optional[str],
    first: int,
    user_id: str,
    db: AsyncSession,
):
    """
    Get repository metadata including languages and topics using GitHub GraphQL API

    This function fetches repository metadata including:
    - Languages with their size (bytes) and color, ordered by size
    - Topics/tags associated with the repository
    """
    # Verify user has access to this workspace
    await verify_workspace_access(user_id, workspace_id, db)

    # Get integration and access token
    integration, access_token = await get_github_integration_with_token(
        workspace_id, db
    )

    # Use GitHub integration username as default owner if not provided
    owner = get_owner_or_default(owner, integration)

    # GraphQL query for repository metadata (languages and topics)
    query = """
    query LangEdges($owner: String!, $name: String!, $first: Int = 12) {
      repository(owner: $owner, name: $name) {
        languages(first: $first, orderBy: { field: SIZE, direction: DESC }) {
          edges {
            size
            node {
              name
              color
            }
          }
          totalSize
          totalCount
        }
        repositoryTopics(first: 20) {
          nodes {
            topic {
              name
            }
          }
        }
      }
    }
    """

    variables = {"owner": owner, "name": name, "first": first}

    # Execute GraphQL query
    data = await execute_github_graphql(query, variables, access_token)

    repository_data = data.get("data", {}).get("repository", {})

    if not repository_data:
        raise HTTPException(
            status_code=404, detail=f"Repository {owner}/{name} not found"
        )

    languages_data = repository_data.get("languages", {})
    topics_data = repository_data.get("repositoryTopics", {})

    # Extract topic names
    topics = [
        node.get("topic", {}).get("name")
        for node in topics_data.get("nodes", [])
        if node.get("topic")
    ]

    return {
        "success": True,
        "owner": owner,
        "name": name,
        "languages": {
            "edges": languages_data.get("edges", []),
            "total_size": languages_data.get("totalSize", 0),
            "total_count": languages_data.get("totalCount", 0),
        },
        "topics": topics,
    }


async def download_file_by_path(
    workspace_id: str,
    repo: str,
    file_path: str,
    owner: Optional[str],
    ref: str,
    user_id: str,
    db: AsyncSession,
):
    """
    Download/fetch file content from a repository using GitHub Contents API

    This function fetches the full content of a file from a GitHub repository.
    Content is automatically decoded from base64 to UTF-8 string.

    Args:
        workspace_id: Workspace ID
        repo: Repository name
        file_path: Path to file in repository
        owner: Repository owner (optional, defaults to integration username)
        ref: Branch/tag/commit reference (mandatory - passed from endpoint with default branch)
        user_id: User ID
        db: Database session
    """
    # Verify user has access to this workspace
    await verify_workspace_access(user_id, workspace_id, db)

    # Get integration and access token
    integration, access_token = await get_github_integration_with_token(
        workspace_id, db
    )

    # Use GitHub integration username as default owner if not provided
    owner = get_owner_or_default(owner, integration)

    # Build endpoint URL
    endpoint = f"/repos/{owner}/{repo}/contents/{file_path}"

    # Add ref parameter
    params = {"ref": ref}

    # Execute REST API call to get file content
    data = await execute_github_rest_api(
        endpoint=endpoint,
        access_token=access_token,
        method="GET",
        params=params if params else None,
    )

    # Check if it's a file (not a directory)
    if data.get("type") != "file":
        raise HTTPException(
            status_code=400,
            detail=f"'{file_path}' is not a file (type: {data.get('type')})",
        )

    # Prepare response
    response_data = {
        "success": True,
        "owner": owner,
        "repo": repo,
        "file_path": file_path,
        "name": data.get("name"),
        "size": data.get("size"),
        "sha": data.get("sha"),
        "url": data.get("url"),
        "html_url": data.get("html_url"),
        "download_url": data.get("download_url"),
        "encoding": data.get("encoding", "base64"),
    }

    # Always decode content from base64 to UTF-8
    if data.get("content"):
        import base64

        try:
            # Remove newlines and decode base64
            content_base64 = data.get("content", "").replace("\n", "")
            decoded_content = base64.b64decode(content_base64).decode("utf-8")
            response_data["content"] = decoded_content
            response_data["content_decoded"] = True
        except Exception as e:
            # If decoding fails, return base64
            logger.warning(f"Failed to decode content for {file_path}: {str(e)}")
            response_data["content"] = data.get("content", "")
            response_data["content_decoded"] = False
            response_data["decode_error"] = str(e)
    else:
        response_data["content"] = ""
        response_data["content_decoded"] = False

    return response_data


async def search_code(
    workspace_id: str,
    search_query: str,
    owner: Optional[str],
    repo: Optional[str],
    per_page: int,
    page: int,
    user_id: str,
    db: AsyncSession,
):
    """
    Search code in the organization or specific repository using GitHub Code Search API

    This function uses GitHub's REST API Code Search to find code across repositories.
    """
    # Verify user has access to this workspace
    await verify_workspace_access(user_id, workspace_id, db)

    # Get integration and access token
    integration, access_token = await get_github_integration_with_token(
        workspace_id, db
    )

    # Use GitHub integration username as default owner if not provided
    owner = get_owner_or_default(owner, integration)

    # Build search query string
    if repo:
        # Search in specific repository
        search_string = f"{search_query} in:file repo:{owner}/{repo}"
    else:
        # Search across all repositories for the user/org
        search_string = f"{search_query} in:file user:{owner}"

    # Prepare query parameters
    params = {
        "q": search_string,
        "per_page": min(per_page, 100),  # GitHub max is 100
        "page": page,
    }

    # Execute REST API call
    data = await execute_github_rest_api(
        endpoint="/search/code", access_token=access_token, method="GET", params=params
    )

    # Filter items to only include required fields
    filtered_items = []
    for item in data.get("items", []):
        filtered_item = {
            "name": item.get("name"),
            "path": item.get("path"),
            "sha": item.get("sha"),
            "repository": {
                "name": item.get("repository", {}).get("name"),
                "id": item.get("repository", {}).get("id"),
                "full_name": item.get("repository", {}).get("full_name"),
                "private": item.get("repository", {}).get("private"),
            },
            "text_matches": [
                {"fragment": match.get("fragment"), "matches": match.get("matches", [])}
                for match in item.get("text_matches", [])
            ],
        }
        filtered_items.append(filtered_item)

    return {
        "success": True,
        "owner": owner,
        "repo": repo,
        "search_query": search_query,
        "query_string": search_string,
        "total_count": data.get("total_count", 0),
        "incomplete_results": data.get("incomplete_results", False),
        "items": filtered_items,
    }


# ==================== FASTAPI ROUTER WRAPPER FUNCTIONS ====================
# These wrap the standalone functions with FastAPI dependencies
# =======================================================================


async def list_repositories_graphql_endpoint(
    workspace_id: str = Query(..., description="Workspace ID"),
    first: int = Query(50, description="Number of repositories to fetch"),
    after: Optional[str] = Query(None, description="Cursor for pagination"),
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all repositories using GitHub GraphQL API - FastAPI endpoint"""
    try:
        return await list_repositories_graphql(workspace_id, first, after, user.id, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL repository listing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def get_repository_tree_endpoint(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    owner: Optional[str] = Query(
        None, description="Repository owner (defaults to GitHub integration username)"
    ),
    expression: Optional[str] = Query(
        None,
        description="Git expression (e.g., 'main:', 'HEAD:', 'main:src/'). Defaults to '<default-branch>:'",
    ),
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read repository files and directory structure - FastAPI endpoint"""
    try:
        integration, _ = await get_github_integration_with_token(workspace_id, db)
        resolved_owner = get_owner_or_default(owner, integration)

        if not expression:
            default_branch = await get_default_branch(
                workspace_id, name, resolved_owner, db
            )
            expression = f"{default_branch}:"

        return await get_repository_tree(
            workspace_id, name, owner, expression, user.id, db
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL repository tree fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def read_repository_file_endpoint(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    file_path: str = Query(
        ..., description="File path (e.g., 'package.json', 'src/app/main.py')"
    ),
    owner: Optional[str] = Query(
        None, description="Repository owner (defaults to GitHub integration username)"
    ),
    branch: Optional[str] = Query(
        None,
        description="Branch/tag/commit ref (defaults to repository's default branch)",
    ),
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read a specific file from a repository - FastAPI endpoint"""
    try:
        integration, _ = await get_github_integration_with_token(workspace_id, db)
        resolved_owner = get_owner_or_default(owner, integration)

        if not branch:
            branch = await get_default_branch(workspace_id, name, resolved_owner, db)

        return await read_repository_file(
            workspace_id, name, file_path, owner, branch, user.id, db
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL file read failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def get_branch_recent_commits_endpoint(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    owner: Optional[str] = Query(
        None, description="Repository owner (defaults to GitHub integration username)"
    ),
    ref: Optional[str] = Query(
        None, description="Branch reference (defaults to 'refs/heads/<default-branch>')"
    ),
    first: int = Query(20, description="Number of commits to fetch (default: 20)"),
    after: Optional[str] = Query(None, description="Cursor for pagination"),
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recent commits from a specific branch - FastAPI endpoint"""
    try:
        integration, _ = await get_github_integration_with_token(workspace_id, db)
        resolved_owner = get_owner_or_default(owner, integration)

        if not ref:
            default_branch = await get_default_branch(
                workspace_id, name, resolved_owner, db
            )
            ref = f"refs/heads/{default_branch}"

        return await get_branch_recent_commits(
            workspace_id, name, owner, ref, first, after, user.id, db
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL branch commits fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def get_repository_commits_endpoint(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    owner: Optional[str] = Query(
        None, description="Repository owner (defaults to GitHub integration username)"
    ),
    first: int = Query(50, description="Number of commits to fetch (default: 50)"),
    after: Optional[str] = Query(None, description="Cursor for pagination"),
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all commit history for a repository - FastAPI endpoint"""
    try:
        return await get_repository_commits(
            workspace_id, name, owner, first, after, user.id, db
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL repository commits fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def list_pull_requests_endpoint(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    owner: Optional[str] = Query(
        None, description="Repository owner (defaults to GitHub integration username)"
    ),
    states: Optional[List[str]] = Query(
        None, description="PR states: OPEN, CLOSED, MERGED (if not provided, shows all)"
    ),
    first: int = Query(20, description="Number of PRs to fetch (default: 20)"),
    after: Optional[str] = Query(None, description="Cursor for pagination"),
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List Pull Requests for a repository - FastAPI endpoint"""
    try:
        return await list_pull_requests(
            workspace_id, name, owner, states, first, after, user.id, db
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL pull requests fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def get_repository_metadata_endpoint(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    owner: Optional[str] = Query(
        None, description="Repository owner (defaults to GitHub integration username)"
    ),
    first: int = Query(12, description="Number of languages to fetch (default: 12)"),
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get repository metadata including languages and topics - FastAPI endpoint"""
    try:
        return await get_repository_metadata(
            workspace_id, name, owner, first, user.id, db
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL repository metadata fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def download_file_by_path_endpoint(
    workspace_id: str = Query(..., description="Workspace ID"),
    repo: str = Query(..., description="Repository name"),
    file_path: str = Query(
        ..., description="File path in repository (e.g., 'src/main.py')"
    ),
    owner: Optional[str] = Query(
        None, description="Repository owner (defaults to GitHub integration username)"
    ),
    ref: Optional[str] = Query(
        None,
        description="Branch/tag/commit ref (defaults to repository's default branch)",
    ),
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download/fetch file content from a repository - FastAPI endpoint"""
    try:
        integration, _ = await get_github_integration_with_token(workspace_id, db)
        resolved_owner = get_owner_or_default(owner, integration)

        if not ref:
            ref = await get_default_branch(workspace_id, repo, resolved_owner, db)

        return await download_file_by_path(
            workspace_id, repo, file_path, owner, ref, user.id, db
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File download failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def search_code_endpoint(
    workspace_id: str = Query(..., description="Workspace ID"),
    search_query: str = Query(
        ..., description="Search query (e.g., 'import', 'function', etc.)"
    ),
    owner: Optional[str] = Query(
        None,
        description="Repository owner/org (defaults to GitHub integration username)",
    ),
    repo: Optional[str] = Query(
        None,
        description="Repository name (optional, if not provided searches entire org)",
    ),
    per_page: int = Query(
        100, description="Number of results per page (default: 100, max: 100)"
    ),
    page: int = Query(1, description="Page number for pagination (default: 1)"),
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search code in the organization or specific repository - FastAPI endpoint"""
    try:
        return await search_code(
            workspace_id, search_query, owner, repo, per_page, page, user.id, db
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Code search failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== CONDITIONAL ROUTE REGISTRATION ====================
# Register routes only in local development
# In deployed envs (dev/prod), standalone functions remain available for LLM usage
# =======================================================================

if settings.is_local:
    logger.info(f"ENVIRONMENT={settings.ENVIRONMENT}: Registering GitHub tools routes")

    # Register all routes for local development/testing
    router.add_api_route(
        "/repositories",
        list_repositories_graphql_endpoint,
        methods=["POST"],
        response_model=None,
    )

    router.add_api_route(
        "/repository/tree",
        get_repository_tree_endpoint,
        methods=["POST"],
        response_model=None,
    )

    router.add_api_route(
        "/repository/read-file",
        read_repository_file_endpoint,
        methods=["POST"],
        response_model=None,
    )

    router.add_api_route(
        "/repository/context",
        get_branch_recent_commits_endpoint,
        methods=["POST"],
        response_model=None,
    )

    router.add_api_route(
        "/repository/commits",
        get_repository_commits_endpoint,
        methods=["POST"],
        response_model=None,
    )

    router.add_api_route(
        "/repository/pull-requests",
        list_pull_requests_endpoint,
        methods=["POST"],
        response_model=None,
    )

    router.add_api_route(
        "/repository/metadata",
        get_repository_metadata_endpoint,
        methods=["POST"],
        response_model=None,
    )

    router.add_api_route(
        "/repository/download-file",
        download_file_by_path_endpoint,
        methods=["POST"],
        response_model=None,
    )

    router.add_api_route(
        "/search/code", search_code_endpoint, methods=["POST"], response_model=None
    )
else:
    logger.info(
        f"ENVIRONMENT={settings.ENVIRONMENT}: GitHub tools routes disabled (functions available for LLM usage)"
    )
