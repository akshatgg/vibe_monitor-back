"""
Account management router for deletion preview and execution.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.auth.services.google_auth_service import AuthService
from app.auth.services.credential_auth_service import CredentialAuthService
from app.auth.services.account_service import AccountService
from app.auth.schemas.account_schemas import (
    AccountProfileResponse,
    DeletionPreviewResponse,
    AccountDeleteRequest,
    AccountDeleteResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account", tags=["account"])

# Initialize services
auth_service = AuthService()
credential_auth_service = CredentialAuthService(jwt_service=auth_service)
account_service = AccountService(credential_auth_service=credential_auth_service)


@router.get("/", response_model=AccountProfileResponse)
async def get_account_profile(
    current_user=Depends(auth_service.get_current_user),
) -> AccountProfileResponse:
    """
    Get the current user's account profile.

    Returns basic profile information including name, email, and verification status.
    """
    return AccountProfileResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        is_verified=current_user.is_verified,
        created_at=current_user.created_at,
    )


@router.get("/deletion-preview", response_model=DeletionPreviewResponse)
async def get_deletion_preview(
    current_user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeletionPreviewResponse:
    """
    Preview what will happen when deleting account.

    Returns information about:
    - Whether deletion is allowed
    - Workspaces that block deletion (sole owner with other members)
    - Workspaces that will be deleted (where user is sole member)
    - Workspaces user will be removed from (co-owner or member)

    This endpoint does NOT delete anything, it only shows what would happen.
    """
    try:
        return await account_service.get_deletion_preview(
            user_id=current_user.id,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get deletion preview: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to get deletion preview. Please try again later.",
        )


@router.delete("/", response_model=AccountDeleteResponse)
async def delete_account(
    request: AccountDeleteRequest,
    current_user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountDeleteResponse:
    """
    Delete the current user's account.

    **WARNING: This action is IRREVERSIBLE. All data will be permanently deleted.**

    Requirements:
    - `confirmation`: Must be 'DELETE' or user's email address
    - `password`: Required for credential-based (password) accounts, not for OAuth accounts

    The deletion will:
    1. Check for blocking workspaces (sole owner with other members)
    2. Delete workspaces where user is sole member
    3. Remove user from workspaces where they're co-owner or member
    4. Delete all user data (tokens, verifications, emails, chat sessions)
    5. Delete the user account

    Returns summary of deleted and left workspaces.
    """
    try:
        return await account_service.delete_account(
            user_id=current_user.id,
            confirmation=request.confirmation,
            password=request.password,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete account: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete account. Please try again later.",
        )
