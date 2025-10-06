from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import secrets
import logging

from ..services.github_app_service import GitHubAppService
from ..services.auth_service import AuthService
from ...core.database import get_db
from ...core.config import settings
from ...utils.token_processor import token_processor

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/github", tags=["github-app"])
github_app_service = GitHubAppService()
auth_service = AuthService()


@router.get("/status")
async def get_github_integration_status(
    workspace_id: str = Query(..., description="Workspace ID to check"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Check if workspace has GitHub App connected

    Returns integration details if connected, null if not
    """
    try:
        from ...models import GitHubIntegration

        result = await db.execute(
            select(GitHubIntegration).where(
                GitHubIntegration.workspace_id == workspace_id
            )
        )
        integration = result.scalar_one_or_none()

        if integration:
            return {
                "connected": True,
                "integration": {
                    "id": integration.id,
                    "github_username": integration.github_username,
                    "installation_id": integration.installation_id,
                    "last_synced_at": integration.last_synced_at
                }
            }
        else:
            return {
                "connected": False,
                "integration": None
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/repositories")
async def list_github_repositories(
    workspace_id: str = Query(..., description="Workspace ID"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all repositories accessible by the GitHub integration

    This endpoint demonstrates using the stored access token.
    Token is automatically refreshed if expired.
    """
    try:
        repos_data = await github_app_service.list_repositories(workspace_id, db)
        return {
            "success": True,
            "total_count": repos_data.get("total_count", 0),
            "repositories": repos_data.get("repositories", [])
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/install")
async def get_github_app_install_url(
    workspace_id: str = Query(..., description="Workspace ID where GitHub App will be installed"),
    user = Depends(auth_service.get_current_user)
):
    """
    Get GitHub App installation URL

    User clicks button → Gets URL → Redirects to GitHub → User installs → GitHub calls /callback

    Required: workspace_id - The workspace where the GitHub integration will be linked
    """
    try:
        # Create simple state with user_id and workspace_id separated by pipe
        state = f"{user.id}|{workspace_id}|{secrets.token_urlsafe(16)}"

        # Build callback URL with workspace_id as a query parameter
        callback_url = f"{settings.API_BASE_URL}/api/v1/github/callback?workspace_id={workspace_id}"

        github_install_url = f"https://github.com/apps/{settings.GITHUB_APP_NAME}/installations/new"
        full_url = f"{github_install_url}?state={state}&redirect_uri={callback_url}"

        return {
            "install_url": full_url,
            "message": "Redirect to this URL to install the GitHub App"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed: {str(e)}")


@router.delete("/disconnect")
async def disconnect_github_app(
    workspace_id: str = Query(..., description="Workspace ID to disconnect"),
    user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Disconnect GitHub App from workspace

    This will deactivate the integration in your database.
    User can manually uninstall from GitHub settings if needed.
    """
    try:
        from ...models import GitHubIntegration, Membership

        # Verify user has access to workspace
        membership_result = await db.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.workspace_id == workspace_id
            )
        )
        membership = membership_result.scalar_one_or_none()

        if not membership:
            raise HTTPException(
                status_code=403,
                detail="User does not have access to this workspace"
            )

        # Find active integration
        result = await db.execute(
            select(GitHubIntegration).where(
                GitHubIntegration.workspace_id == workspace_id
            )
        )
        integration = result.scalar_one_or_none()

        if not integration:
            raise HTTPException(
                status_code=404,
                detail="No active GitHub integration found for this workspace"
            )

        # Uninstall from GitHub via API
        try:
            await github_app_service.uninstall_github_app(integration.installation_id)
        except Exception as e:
            # If API call fails, still deactivate locally
            logger.warning(f"Failed to uninstall from GitHub: {str(e)}")

        # Delete integration from database
        await db.delete(integration)
        await db.commit()

        return {
            "success": True,
            "message": "GitHub App disconnected and uninstalled successfully"
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def github_app_installation_callback(
    installation_id: str = Query(...),
    setup_action: str = Query(...),
    state: Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None, description="Workspace ID (required for testing with JWT)"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """
    GitHub redirects here after installation

    Supports two auth methods:
    1. State parameter (used by GitHub callback)
    2. JWT token (for testing in Swagger - requires workspace_id query param)
    """
    try:
        user_id = None
        state_workspace_id = None

        # Try to get user_id from JWT token first (for Swagger testing)
        if credentials:
            try:
                payload = auth_service.verify_token(credentials.credentials, "access")
                user_id = payload.get("sub")
            except Exception:
                pass

        # If no JWT, try to get user_id and workspace_id from state (GitHub callback)
        if not user_id and state:
            try:
                # Parse simple state format: "user_id|workspace_id|token"
                parts = state.split("|")
                if len(parts) >= 2:
                    user_id = parts[0]
                    state_workspace_id = parts[1]
            except Exception:
                pass

        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Use query param workspace_id if provided, otherwise use state workspace_id
        final_workspace_id = workspace_id or state_workspace_id

        if not final_workspace_id:
            raise HTTPException(status_code=400, detail="workspace_id is required")

        # Validate that workspace exists and user has access
        from ...models import Workspace, Membership
        workspace_result = await db.execute(
            select(Workspace).where(Workspace.id == final_workspace_id)
        )
        workspace = workspace_result.scalar_one_or_none()

        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Check if user is a member of the workspace
        membership_result = await db.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.workspace_id == final_workspace_id
            )
        )
        membership = membership_result.scalar_one_or_none()

        if not membership:
            raise HTTPException(
                status_code=403,
                detail="User does not have access to this workspace"
            )

        installation_info = await github_app_service.get_installation_info_by_id(installation_id)

        integration = await github_app_service.create_or_update_app_integration_with_installation(
            workspace_id=final_workspace_id,
            installation_id=installation_id,
            installation_info=installation_info,
            db=db
        )

        # Get and store access token immediately after installation
        try:
            token_data = await github_app_service.get_installation_access_token(installation_id)
            from dateutil import parser as date_parser

            integration.access_token = token_processor.encrypt(token_data["token"])
            integration.token_expires_at = date_parser.isoparse(token_data["expires_at"])

            await db.commit()
            await db.refresh(integration)
        except Exception as e:
            # Log error but don't fail the installation
            logger.warning(f"Failed to get access token during installation: {str(e)}")

        return {
            "success": True,
            "message": f"GitHub App {setup_action}ed successfully!",
            "integration": {
                "id": integration.id,
                "github_username": integration.github_username,
                "installation_id": integration.installation_id
            }
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))