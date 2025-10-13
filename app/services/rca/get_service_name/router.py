"""
API endpoints for repository service discovery
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
import logging

from app.onboarding.services.auth_service import AuthService
from app.core.database import get_db
from .service import (
    extract_service_names_from_repo,
    save_repository_services,
    get_repository_services,
)
from .schemas import ScanRepositoryRequest, RepositoryServiceResponse

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

        # Save to database
        saved = await save_repository_services(
            workspace_id=workspace_id,
            repo_name=repo_name,
            services=services,
            db=db
        )

        return {
            "success": True,
            "repo_name": repo_name,
            "services": services,
            "saved": RepositoryServiceResponse.model_validate(saved)
        }

    except Exception as e:
        logger.error(f"Error scanning repository: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", response_model=List[RepositoryServiceResponse])
async def list_services(
    workspace_id: str = Query(..., description="Workspace ID"),
    repo_name: Optional[str] = Query(None, description="Filter by repo (owner/repo)"),
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all repository services in workspace

    Returns repository -> services mappings
    """
    try:
        services = await get_repository_services(
            workspace_id=workspace_id,
            repo_name=repo_name,
            db=db
        )

        return [RepositoryServiceResponse.model_validate(s) for s in services]

    except Exception as e:
        logger.error(f"Error listing services: {e}")
        raise HTTPException(status_code=500, detail=str(e))


