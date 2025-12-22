from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.auth.services.google_auth_service import AuthService
from app.auth.services.credential_auth_service import CredentialAuthService
from app.auth.schemas.credential_auth_schemas import (
    SignupRequest,
    SignupResponse,
    LoginRequest,
    LoginResponse,
    VerifyEmailRequest,
    ResendVerificationRequest,
    ForgotPasswordRequest,
    ResendPasswordResetRequest,
    ResetPasswordRequest,
    MessageResponse,
)

router = APIRouter(prefix="/auth", tags=["credential-authentication"])

# Initialize services
jwt_service = AuthService()
credential_service = CredentialAuthService(jwt_service)


@router.post(
    "/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED
)
async def signup(request: SignupRequest, db: AsyncSession = Depends(get_db)):
    """
    Register a new user with email and password.

    - Creates user account with unverified status
    - Sends verification email
    - Creates personal workspace
    - User must verify email before they can log in (consistent with login behavior)
    """
    try:
        response, user = await credential_service.signup(
            email=request.email, password=request.password, name=request.name, db=db
        )

        return SignupResponse(
            message=response["message"],
            email=response["email"],
            is_verified=response["is_verified"],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Signup failed: {str(e)}",
        )


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate user with email and password.

    - Verifies credentials
    - Returns JWT tokens
    - Includes verification status in response
    """
    try:
        return await credential_service.login(
            email=request.email, password=request.password, db=db
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}",
        )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(request: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    """
    Verify user email with token from verification link.

    - Validates token
    - Updates user is_verified status
    - Marks token as used
    """
    try:
        return await credential_service.verify_email(token=request.token, db=db)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Email verification failed: {str(e)}",
        )


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    request: ResendVerificationRequest, db: AsyncSession = Depends(get_db)
):
    """
    Resend verification email to user.

    - Invalidates old tokens
    - Generates new token
    - Sends verification email
    """
    try:
        return await credential_service.resend_verification_email(
            email=request.email, db=db
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resend verification email: {str(e)}",
        )


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    request: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """
    Request password reset link.

    - Validates user exists
    - Generates reset token
    - Sends password reset email
    """
    try:
        return await credential_service.forgot_password(email=request.email, db=db)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process password reset request: {str(e)}",
        )


@router.post("/resend-password-reset", response_model=MessageResponse)
async def resend_password_reset(
    request: ResendPasswordResetRequest, db: AsyncSession = Depends(get_db)
):
    """
    Resend password reset email to user.

    - Invalidates old password reset tokens
    - Generates new reset token
    - Sends password reset email

    This endpoint is useful when the previous reset link has expired (1 hour expiry).
    """
    try:
        return await credential_service.forgot_password(email=request.email, db=db)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resend password reset email: {str(e)}",
        )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    request: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """
    Reset user password with token.

    - Validates reset token
    - Updates password
    - Invalidates all refresh tokens for security
    """
    try:
        return await credential_service.reset_password(
            token=request.token, new_password=request.new_password, db=db
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Password reset failed: {str(e)}",
        )
