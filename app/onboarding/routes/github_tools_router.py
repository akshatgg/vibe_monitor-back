from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
import logging

from ..services.auth_service import AuthService
from ..services.github_tools_service import (
    get_github_integration_with_token,
    execute_github_graphql,
    execute_github_rest_api,
    get_owner_or_default,
    verify_workspace_access
)
from ...core.database import get_db
 

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github-tools", tags=["github-tools"])
auth_service = AuthService()


@router.post("/repositories")
async def list_repositories_graphql(
    workspace_id: str = Query(..., description="Workspace ID"),
    first: int = Query(50, description="Number of repositories to fetch"),
    after: Optional[str] = Query(None, description="Cursor for pagination"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all repositories using GitHub GraphQL API

    This endpoint uses GraphQL to fetch repositories that the authenticated user can access.
    Supports pagination through the 'after' cursor parameter.
    """
    try:
        # Verify user has access to this workspace
        await verify_workspace_access(user.id, workspace_id, db)

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
            "affiliations": ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"]
        }

        # Execute GraphQL query
        data = await execute_github_graphql(query, variables, access_token)

        viewer_data = data.get("data", {}).get("viewer", {})
        repos_data = viewer_data.get("repositories", {})

        return {
            "success": True,
            "viewer": {
                "login": viewer_data.get("login"),
                "name": viewer_data.get("name")
            },
            "repositories": repos_data.get("nodes", []),
            "pageInfo": repos_data.get("pageInfo", {})
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL repository listing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/repository/tree")
async def get_repository_tree(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    owner: Optional[str] = Query(None, description="Repository owner (defaults to GitHub integration username)"),
    expression: str = Query("main:", description="Git expression (e.g., 'main:', 'HEAD:', 'main:src/')"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Read repository files and directory structure using GitHub GraphQL API

    This endpoint fetches repository tree structure, files, and their contents.
    Equivalent to REST API: GET /repos/{o}/{r}/contents/{path}, GET /git/trees/{sha}?recursive=1

    Args:
        workspace_id: Workspace ID
        name: Repository name (e.g., "PPS-Soln")
        owner: Repository owner (optional, defaults to GitHub integration username)
        expression: Git expression (e.g., "main:", "HEAD:", "main:src/")
    """
    try:
        # Verify user has access to this workspace
        await verify_workspace_access(user.id, workspace_id, db)

        # Get integration and access token
        integration, access_token = await get_github_integration_with_token(workspace_id, db)

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

        variables = {
            "owner": owner,
            "name": name,
            "expression": expression
        }

        # Execute GraphQL query
        data = await execute_github_graphql(query, variables, access_token)

        repository_data = data.get("data", {}).get("repository", {})
        object_data = repository_data.get("object")

        if not object_data:
            raise HTTPException(
                status_code=404,
                detail=f"Expression '{expression}' not found in repository {owner}/{name}"
            )

        return {
            "success": True,
            "owner": owner,
            "name": name,
            "expression": expression,
            "data": object_data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL repository tree fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/repository/read-file")
async def read_repository_file(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    file_path: str = Query(..., description="File path (e.g., 'package.json', 'src/app/main.py')"),
    owner: Optional[str] = Query(None, description="Repository owner (defaults to GitHub integration username)"),
    branch: str = Query("HEAD", description="Branch name (default: HEAD)"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Read a specific file from a repository using GitHub GraphQL API

    This endpoint reads file contents (code, configs, manifests, OpenAPI, logs, etc.).
    Expression is built from branch and file_path (e.g., "HEAD:package.json")

    Args:
        workspace_id: Workspace ID
        name: Repository name (e.g., "itax_next_main")
        file_path: File path (e.g., "package.json", "src/app/main.py")
        owner: Repository owner (optional, defaults to GitHub integration username)
        branch: Branch name (default: HEAD)
    """
    try:
        # Verify user has access to this workspace
        await verify_workspace_access(user.id, workspace_id, db)

        # Get integration and access token
        integration, access_token = await get_github_integration_with_token(workspace_id, db)

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

        variables = {
            "owner": owner,
            "name": name,
            "expression": expression
        }

        # Execute GraphQL query
        data = await execute_github_graphql(query, variables, access_token)

        repository_data = data.get("data", {}).get("repository", {})
        object_data = repository_data.get("object")

        if not object_data:
            raise HTTPException(
                status_code=404,
                detail=f"File '{file_path}' not found in repository {owner}/{name} on branch {branch}"
            )
        # Check if it's a blob (file)
        if object_data.get("__typename") != "Blob":
            raise HTTPException(
                status_code=400,
                detail=f"'{file_path}' is not a file (type: {object_data.get('__typename')})"
            )

        return {
            "success": True,
            "owner": owner,
            "name": name,
            "branch": branch,
            "file_path": file_path,
            "expression": expression,
            "byte_size": object_data.get("byteSize"),
            "content": object_data.get("text")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL file read failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/repository/context")
async def get_branch_recent_commits(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    owner: Optional[str] = Query(None, description="Repository owner (defaults to GitHub integration username)"),
    ref: str = Query("refs/heads/main", description="Branch reference (default: refs/heads/main)"),
    first: int = Query(20, description="Number of commits to fetch (default: 20)"),
    after: Optional[str] = Query(None, description="Cursor for pagination"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get recent commits from a specific branch using GitHub GraphQL API

    This endpoint fetches recent commit history from a specified branch reference.

    Args:
        workspace_id: Workspace ID
        name: Repository name
        owner: Repository owner (optional, defaults to GitHub integration username)
        ref: Branch reference (default: refs/heads/main)
        first: Number of commits to fetch (default: 20)
        after: Cursor for pagination
    """
    try:
        # Verify user has access to this workspace
        await verify_workspace_access(user.id, workspace_id, db)

        # Get integration and access token
        integration, access_token = await get_github_integration_with_token(workspace_id, db)

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
            "after": after
        }

        # Execute GraphQL query
        data = await execute_github_graphql(query, variables, access_token)

        repository_data = data.get("data", {}).get("repository", {})
        branch_data = repository_data.get("branch")

        if not branch_data:
            raise HTTPException(
                status_code=404,
                detail=f"Branch reference '{ref}' not found in repository {owner}/{name}"
            )

        target_data = branch_data.get("target", {})
        recent_data = target_data.get("recent", {})

        return {
            "success": True,
            "owner": owner,
            "name": name,
            "ref": ref,
            "commits": recent_data.get("nodes", []),
            "pageInfo": recent_data.get("pageInfo", {})
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL branch commits fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/repository/commits")
async def get_repository_commits(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    owner: Optional[str] = Query(None, description="Repository owner (defaults to GitHub integration username)"),
    first: int = Query(50, description="Number of commits to fetch (default: 50)"),
    after: Optional[str] = Query(None, description="Cursor for pagination"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all commit history for a repository using GitHub GraphQL API

    This endpoint fetches all commits from the repository's default branch.

    Args:
        workspace_id: Workspace ID
        name: Repository name
        owner: Repository owner (optional, defaults to GitHub integration username)
        first: Number of commits to fetch (default: 50)
        after: Cursor for pagination
    """
    try:
        # Verify user has access to this workspace
        await verify_workspace_access(user.id, workspace_id, db)

        # Get integration and access token
        integration, access_token = await get_github_integration_with_token(workspace_id, db)

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

        variables = {
            "owner": owner,
            "name": name,
            "first": first,
            "after": after
        }

        # Execute GraphQL query
        data = await execute_github_graphql(query, variables, access_token)

        repository_data = data.get("data", {}).get("repository", {})
        default_branch_ref = repository_data.get("defaultBranchRef")

        if not default_branch_ref:
            raise HTTPException(
                status_code=404,
                detail=f"No default branch found for repository {owner}/{name}"
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
            "pageInfo": history_data.get("pageInfo", {})
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL repository commits fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/repository/pull-requests")
async def list_pull_requests(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    owner: Optional[str] = Query(None, description="Repository owner (defaults to GitHub integration username)"),
    states: Optional[List[str]] = Query(None, description="PR states: OPEN, CLOSED, MERGED (if not provided, shows all)"),
    first: int = Query(20, description="Number of PRs to fetch (default: 20)"),
    after: Optional[str] = Query(None, description="Cursor for pagination"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List Pull Requests for a repository using GitHub GraphQL API

    This endpoint fetches pull requests with various states (OPEN, CLOSED, MERGED).
    If states parameter is not provided, it returns all PRs regardless of state.
    Returns PR details including author, dates, review status, labels, and file counts.

    Args:
        workspace_id: Workspace ID
        name: Repository name
        owner: Repository owner (optional, defaults to GitHub integration username)
        states: PR states to filter (optional, if not provided shows all states)
        first: Number of PRs to fetch (default: 20)
        after: Cursor for pagination
    """
    try:
        # Verify user has access to this workspace
        await verify_workspace_access(user.id, workspace_id, db)

        # Get integration and access token
        integration, access_token = await get_github_integration_with_token(workspace_id, db)

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
                        detail=f"Invalid state: {state}. Valid states are: {', '.join(valid_states)}"
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
            "after": after
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
            "pageInfo": pull_requests_data.get("pageInfo", {})
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL pull requests fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/repository/metadata")
async def get_repository_metadata(
    workspace_id: str = Query(..., description="Workspace ID"),
    name: str = Query(..., description="Repository name"),
    owner: Optional[str] = Query(None, description="Repository owner (defaults to GitHub integration username)"),
    first: int = Query(12, description="Number of languages to fetch (default: 12)"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get repository metadata including languages and topics using GitHub GraphQL API

    This endpoint fetches repository metadata including:
    - Languages with their size (bytes) and color, ordered by size
    - Topics/tags associated with the repository

    Args:
        workspace_id: Workspace ID
        name: Repository name
        owner: Repository owner (optional, defaults to GitHub integration username)
        first: Number of languages to fetch (default: 12)
    """
    try:
        # Verify user has access to this workspace
        await verify_workspace_access(user.id, workspace_id, db)

        # Get integration and access token
        integration, access_token = await get_github_integration_with_token(workspace_id, db)

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

        variables = {
            "owner": owner,
            "name": name,
            "first": first
        }

        # Execute GraphQL query
        data = await execute_github_graphql(query, variables, access_token)

        repository_data = data.get("data", {}).get("repository", {})

        if not repository_data:
            raise HTTPException(
                status_code=404,
                detail=f"Repository {owner}/{name} not found"
            )

        languages_data = repository_data.get("languages", {})
        topics_data = repository_data.get("repositoryTopics", {})

        # Extract topic names
        topics = [node.get("topic", {}).get("name") for node in topics_data.get("nodes", []) if node.get("topic")]

        return {
            "success": True,
            "owner": owner,
            "name": name,
            "languages": {
                "edges": languages_data.get("edges", []),
                "total_size": languages_data.get("totalSize", 0),
                "total_count": languages_data.get("totalCount", 0)
            },
            "topics": topics
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GraphQL repository metadata fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/repository/download-file")
async def download_file_by_path(
    workspace_id: str = Query(..., description="Workspace ID"),
    repo: str = Query(..., description="Repository name"),
    file_path: str = Query(..., description="File path in repository (e.g., 'src/main.py')"),
    owner: Optional[str] = Query(None, description="Repository owner (defaults to GitHub integration username)"),
    ref: Optional[str] = Query(None, description="Branch/tag/commit ref (optional, defaults to default branch)"),
    decode_content: bool = Query(True, description="Auto-decode base64 content to UTF-8 string (default: True)"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Download/fetch file content from a repository using GitHub Contents API

    This endpoint fetches the full content of a file from a GitHub repository.
    Use this after getting file locations from /search/code to download the actual files.

    Args:
        workspace_id: Workspace ID
        repo: Repository name (e.g., 'itax_next_main')
        file_path: File path in repository (e.g., 'src/main.py', 'README.md')
        owner: Repository owner (optional, defaults to GitHub integration username)
        ref: Branch/tag/commit reference (optional, defaults to repo's default branch)
        decode_content: Auto-decode base64 to UTF-8 string (default: True)

    Returns:
        File metadata and content (decoded if decode_content=True, otherwise base64)

    Example usage:
        After code search returns: {"path": "src/main.py", "repository": {"name": "myrepo"}}
        Call: /repository/download-file?workspace_id=X&repo=myrepo&file_path=src/main.py
    """
    try:
        # Verify user has access to this workspace
        await verify_workspace_access(user.id, workspace_id, db)

        # Get integration and access token
        integration, access_token = await get_github_integration_with_token(workspace_id, db)

        # Use GitHub integration username as default owner if not provided
        owner = get_owner_or_default(owner, integration)

        # Build endpoint URL
        endpoint = f"/repos/{owner}/{repo}/contents/{file_path}"

        # Add ref parameter if provided
        params = {}
        if ref:
            params["ref"] = ref

        # Execute REST API call to get file content
        data = await execute_github_rest_api(
            endpoint=endpoint,
            access_token=access_token,
            method="GET",
            params=params if params else None
        )

        # Check if it's a file (not a directory)
        if data.get("type") != "file":
            raise HTTPException(
                status_code=400,
                detail=f"'{file_path}' is not a file (type: {data.get('type')})"
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
            "encoding": data.get("encoding", "base64")
        }

        # Decode content if requested
        if decode_content and data.get("content"):
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
            # Return raw base64 content
            response_data["content"] = data.get("content", "")
            response_data["content_decoded"] = False

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File download failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/code")
async def search_code(
    workspace_id: str = Query(..., description="Workspace ID"),
    search_query: str = Query(..., description="Search query (e.g., 'import', 'function', etc.)"),
    owner: Optional[str] = Query(None, description="Repository owner/org (defaults to GitHub integration username)"),
    repo: Optional[str] = Query(None, description="Repository name (optional, if not provided searches entire org)"),
    per_page: int = Query(100, description="Number of results per page (default: 100, max: 100)"),
    page: int = Query(1, description="Page number for pagination (default: 1)"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Search code in the organization or specific repository using GitHub Code Search API

    This endpoint uses GitHub's REST API Code Search to find code across repositories.
    You can search across all repos in an org/user, or limit the search to a specific repository.

    Args:
        workspace_id: Workspace ID
        search_query: Search term (e.g., 'import', 'function', etc.)
        owner: Repository owner/org (optional, defaults to GitHub integration username)
        repo: Repository name (optional, if not provided searches entire org)
        per_page: Number of results per page (default: 100, max: 100)
        page: Page number for pagination (default: 1)

    Example queries:
        - Search for 'import' in all files across org: search_query='import'
        - Search in specific repo: search_query='import', repo='Duracore'
    """
    try:
        # Verify user has access to this workspace
        await verify_workspace_access(user.id, workspace_id, db)

        # Get integration and access token
        integration, access_token = await get_github_integration_with_token(workspace_id, db)

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
            "page": page
        }

        # Execute REST API call
        data = await execute_github_rest_api(
            endpoint="/search/code",
            access_token=access_token,
            method="GET",
            params=params
        )

        return {
            "success": True,
            "owner": owner,
            "repo": repo,
            "search_query": search_query,
            "query_string": search_string,
            "total_count": data.get("total_count", 0),
            "incomplete_results": data.get("incomplete_results", False),
            "items": data.get("items", [])
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Code search failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


