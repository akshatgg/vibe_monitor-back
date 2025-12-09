"""
API endpoints for repository service discovery
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.auth.services.google_auth_service import AuthService
from app.core.database import get_db
from .service import (
    extract_service_names_from_repo,
)
from .schemas import ScanRepositoryRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repository-services", tags=["repository-services"])
auth_service = AuthService()


@router.post("/scan")
async def scan_repository(
    workspace_id: str = Query(..., description="Workspace ID"),
    request: ScanRepositoryRequest = None,
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Scan a repository to extract service names

    Analyzes Dockerfile, main.py, package.json, etc. to find service names
    using deterministic regex patterns (no LLM).

    Owner is automatically fetched from GitHub integration in database.
    """
    try:
        # Get owner from database
        from app.github.tools.service import get_github_integration_with_token
        integration, _ = await get_github_integration_with_token(workspace_id, db)
        owner = integration.github_username

        # Extract service names
        services = await extract_service_names_from_repo(
            workspace_id=workspace_id,
            repo=request.repo,
            user_id=user.id,
            db=db
        )

        # Build full repo name
        repo_name = f"{owner}/{request.repo}"

        return {
            "success": True,
            "repo_name": repo_name,
            "services": services
        }

    except Exception as e:
        logger.error(f"Error scanning repository: {e}")
        raise HTTPException(status_code=500, detail=str(e))

