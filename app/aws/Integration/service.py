"""
AWS Integration Service
Handles CRUD operations and credential management for AWS integrations
Uses STS AssumeRole for temporary credentials instead of long-term access keys
Implements two-stage authentication: Host -> Owner Role -> Client Role
"""
import os
import uuid
import logging
from typing import Optional, Dict, Any
from contextlib import contextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
import boto3
from botocore.exceptions import ClientError

from app.models import AWSIntegration
from app.utils.token_processor import token_processor
from app.core.config import settings
from .schemas import (
    AWSIntegrationCreate,
    AWSIntegrationResponse,
    AWSIntegrationVerifyResponse,
)

logger = logging.getLogger(__name__)


class AWSIntegrationService:
    """Service for managing AWS integrations using STS AssumeRole"""

    # Cache for owner role credentials (to avoid repeated assumptions)
    _owner_credentials_cache: Optional[Dict[str, Any]] = None
    _owner_credentials_expiration: Optional[datetime] = None

    @staticmethod
    @contextmanager
    def _bypass_localstack():
        """
        Context manager to temporarily remove AWS_ENDPOINT_URL environment variable
        This ensures boto3 connects to real AWS services (STS, CloudWatch) instead of LocalStack
        LocalStack is only used for SQS in this project
        """
        original_endpoint = os.environ.get('AWS_ENDPOINT_URL')
        if original_endpoint:
            del os.environ['AWS_ENDPOINT_URL']
        try:
            yield
        finally:
            if original_endpoint:
                os.environ['AWS_ENDPOINT_URL'] = original_endpoint

    @staticmethod
    def _create_boto_session(
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        session_token: Optional[str] = None,
        region_name: str = "us-east-1"
    ) -> boto3.Session:
        """
        Create a boto3 session with explicit configuration
        Use with _bypass_localstack() context manager to ensure real AWS connection

        Args:
            access_key_id: AWS Access Key ID
            secret_access_key: AWS Secret Access Key
            session_token: AWS Session Token (for temporary credentials)
            region_name: AWS Region

        Returns:
            boto3.Session configured with provided credentials
        """
        return boto3.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            aws_session_token=session_token,
            region_name=region_name
        )

    @staticmethod
    async def assume_owner_role(region: str = "us-east-1") -> Dict[str, Any]:
        """
        Assume the owner role (first stage of two-stage authentication)
        Caches credentials to avoid repeated assumptions
        Should only be called in dev/development environment

        Args:
            region: AWS Region

        Returns:
            Dict containing temporary owner role credentials

        Raises:
            Exception: If owner role assumption fails
        """
        # Check cache first (refresh if expiring within 5 minutes)
        now = datetime.now(timezone.utc)
        if (AWSIntegrationService._owner_credentials_cache
            and AWSIntegrationService._owner_credentials_expiration
            and AWSIntegrationService._owner_credentials_expiration > now + timedelta(minutes=5)):
            return AWSIntegrationService._owner_credentials_cache

        try:
            # Bypass LocalStack to connect to real AWS STS
            with AWSIntegrationService._bypass_localstack():
                # Create session with host credentials (from environment or ECS task role)
                session = AWSIntegrationService._create_boto_session(
                    access_key_id=settings.AWS_ACCESS_KEY_ID,
                    secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=region
                )

                # Connect to real AWS STS (LocalStack endpoint bypassed)
                sts_client = session.client("sts")

                # Prepare AssumeRole parameters for owner role
                assume_role_params = {
                    "RoleArn": settings.OWNER_ROLE_ARN,
                    "RoleSessionName": settings.OWNER_ROLE_SESSION_NAME,
                    "DurationSeconds": settings.OWNER_ROLE_DURATION_SECONDS,
                }

                # Add ExternalId if configured
                if settings.OWNER_ROLE_EXTERNAL_ID:
                    assume_role_params["ExternalId"] = settings.OWNER_ROLE_EXTERNAL_ID

                # Assume the owner role
                response = sts_client.assume_role(**assume_role_params)
                credentials = response["Credentials"]

            # Cache the credentials
            owner_credentials = {
                "access_key_id": credentials["AccessKeyId"],
                "secret_access_key": credentials["SecretAccessKey"],
                "session_token": credentials["SessionToken"],
                "expiration": credentials["Expiration"],
            }

            AWSIntegrationService._owner_credentials_cache = owner_credentials
            AWSIntegrationService._owner_credentials_expiration = credentials["Expiration"]

            return owner_credentials

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            raise Exception(f"Failed to assume owner role: {error_code} - {error_message}")
        except Exception as e:
            raise Exception(f"Failed to assume owner role: {str(e)}")

    @staticmethod
    async def assume_role(
        role_arn: str,
        region: str = "us-east-1",
        duration_seconds: int = 3600,
        external_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Assume an IAM role and get temporary credentials using STS
        Implements two-stage authentication: Host -> Owner Role -> Client Role

        Args:
            role_arn: AWS IAM Role ARN to assume (client role)
            region: AWS Region
            duration_seconds: Duration for temporary credentials (default 3600 = 1 hour)
            external_id: Optional external ID for cross-account access security

        Returns:
            Dict containing temporary credentials and expiration

        Raises:
            Exception: If role assumption fails
        """
        try:
            # Check if running in dev/development environment
            if settings.ENVIRONMENT and settings.ENVIRONMENT.lower() in ["dev", "development"]:
                # DEV: Two-stage authentication (Host -> Owner Role -> Client Role)
                # Bypass LocalStack to connect to real AWS STS
                with AWSIntegrationService._bypass_localstack():
                    owner_credentials = await AWSIntegrationService.assume_owner_role(region)
                    session = AWSIntegrationService._create_boto_session(
                        access_key_id=owner_credentials["access_key_id"],
                        secret_access_key=owner_credentials["secret_access_key"],
                        session_token=owner_credentials["session_token"],
                        region_name=region
                    )
                    # Connect to real AWS STS (LocalStack endpoint bypassed)
                    sts_client = session.client("sts")
            else:
                # PRODUCTION: Direct authentication using ECS Task IAM Role (Host -> Client Role)
                # Don't pass credentials - let boto3 automatically use ECS task role
                session = AWSIntegrationService._create_boto_session(
                    region_name=region
                )
                # Connect to real AWS STS 
                sts_client = session.client("sts")

                # Prepare AssumeRole parameters for client role
                assume_role_params = {
                    "RoleArn": role_arn,
                    "RoleSessionName": "vibe-monitor-client-session",
                    "DurationSeconds": duration_seconds,
                }

                # Add ExternalId if provided
                if external_id:
                    assume_role_params["ExternalId"] = external_id

                # Assume the client role
                response = sts_client.assume_role(**assume_role_params)
                credentials = response["Credentials"]

            return {
                "access_key_id": credentials["AccessKeyId"],
                "secret_access_key": credentials["SecretAccessKey"],
                "session_token": credentials["SessionToken"],
                "expiration": credentials["Expiration"],
            }

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            raise Exception(f"Failed to assume client role: {error_code} - {error_message}")
        except Exception as e:
            raise Exception(f"Failed to assume client role: {str(e)}")

    @staticmethod
    async def verify_role_and_permissions(
        role_arn: str, region: str = "us-east-1", external_id: Optional[str] = None
    ) -> AWSIntegrationVerifyResponse:
        """
        Verify that the role can be assumed and has CloudWatch access
        Uses thread-safe boto3 session approach

        Args:
            role_arn: AWS IAM Role ARN (client role)
            region: AWS Region
            external_id: Optional external ID for client role

        Returns:
            AWSIntegrationVerifyResponse with verification result
        """
        account_id = None

        try:
            # Step 1: Try to assume the role (two-stage: owner -> client)
            credentials = await AWSIntegrationService.assume_role(role_arn, region, external_id=external_id)

            # Step 2: Verify CloudWatch Logs access with temporary client credentials
            # Bypass LocalStack to connect to real AWS CloudWatch
            with AWSIntegrationService._bypass_localstack():
                session = AWSIntegrationService._create_boto_session(
                    access_key_id=credentials["access_key_id"],
                    secret_access_key=credentials["secret_access_key"],
                    session_token=credentials["session_token"],
                    region_name=region
                )

                # Test CloudWatch Logs access (always uses real AWS)
                logs_client = session.client("logs")
                logs_client.describe_log_groups(limit=1)

            # Extract account ID from role ARN (format: arn:aws:iam::123456789012:role/RoleName)
            account_id = role_arn.split(":")[4]

            # All verifications passed
            return AWSIntegrationVerifyResponse(
                is_valid=True,
                message="AWS role verified successfully with CloudWatch access",
                account_id=account_id,
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))

            if error_code == "AccessDeniedException" or error_code == "AccessDenied":
                return AWSIntegrationVerifyResponse(
                    is_valid=False,
                    message=f"Access Error: Missing permissions - {error_message}. Required: sts:AssumeRole, logs:DescribeLogGroups, cloudwatch:*, xray:*",
                    account_id=account_id,
                )
            return AWSIntegrationVerifyResponse(
                is_valid=False,
                message=f"Verification Error: {error_code} - {error_message}",
                account_id=account_id,
            )
        except Exception as e:
            return AWSIntegrationVerifyResponse(
                is_valid=False,
                message=f"Verification Error: {str(e)}",
                account_id=account_id,
            )

    async def create_aws_integration(
        self,
        db: AsyncSession,
        workspace_id: str,
        integration_data: AWSIntegrationCreate,
    ) -> AWSIntegrationResponse:
        """
        Create a new AWS integration for a workspace using IAM role ARN

        Args:
            db: Database session
            workspace_id: Workspace ID
            integration_data: AWS integration data (role_arn, region)

        Returns:
            AWSIntegrationResponse

        Raises:
            ValueError: If integration already exists or role is invalid
        """
        # Check if integration already exists for this workspace
        result = await db.execute(
            select(AWSIntegration).where(
                AWSIntegration.workspace_id == workspace_id,
                AWSIntegration.is_active.is_(True),
            )
        )
        existing_integration = result.scalar_one_or_none()

        if existing_integration:
            raise ValueError(
                "An active AWS integration already exists for this workspace"
            )

        region = integration_data.aws_region if integration_data.aws_region else "us-east-1"

        # Verify role and permissions before saving
        verification = await self.verify_role_and_permissions(
            integration_data.role_arn,
            region,
            integration_data.external_id,
        )

        if not verification.is_valid:
            raise ValueError(f"Invalid AWS role: {verification.message}")

        # Assume role to get temporary credentials
        credentials = await self.assume_role(
            integration_data.role_arn,
            region,
            external_id=integration_data.external_id
        )

        # Encrypt temporary credentials and external_id (if provided)
        encrypted_access_key = token_processor.encrypt(credentials["access_key_id"])
        encrypted_secret_key = token_processor.encrypt(credentials["secret_access_key"])
        encrypted_session_token = token_processor.encrypt(credentials["session_token"])
        encrypted_external_id = token_processor.encrypt(integration_data.external_id) if integration_data.external_id else None

        # Create new integration
        integration = AWSIntegration(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            role_arn=integration_data.role_arn,
            external_id=encrypted_external_id,
            access_key_id=encrypted_access_key,
            secret_access_key=encrypted_secret_key,
            session_token=encrypted_session_token,
            credentials_expiration=credentials["expiration"],
            aws_region=region,
            is_active=True,
            last_verified_at=datetime.now(timezone.utc),
        )

        db.add(integration)
        await db.commit()
        await db.refresh(integration)

        return AWSIntegrationResponse(
            id=integration.id,
            workspace_id=integration.workspace_id,
            role_arn=integration.role_arn,
            has_external_id=integration.external_id is not None,
            aws_region=integration.aws_region,
            is_active=integration.is_active,
            credentials_expiration=integration.credentials_expiration,
            last_verified_at=integration.last_verified_at,
            created_at=integration.created_at,
            updated_at=integration.updated_at,
        )

    async def get_aws_integration(
        self, db: AsyncSession, workspace_id: str
    ) -> Optional[AWSIntegrationResponse]:
        """
        Get AWS integration for a workspace
        Automatically refreshes credentials if they are expired or about to expire

        Args:
            db: Database session
            workspace_id: Workspace ID

        Returns:
            AWSIntegrationResponse or None if not found
        """
        result = await db.execute(
            select(AWSIntegration).where(
                AWSIntegration.workspace_id == workspace_id,
                AWSIntegration.is_active.is_(True),
            )
        )
        integration = result.scalar_one_or_none()

        if not integration:
            return None

        # Check if credentials are expired or about to expire (within 5 minutes)
        now = datetime.now(timezone.utc)
        expiration_threshold = now + timedelta(minutes=5)

        if integration.credentials_expiration <= expiration_threshold:
            # Refresh credentials by assuming role again
            try:
                # Decrypt external_id if present
                external_id = token_processor.decrypt(integration.external_id) if integration.external_id else None

                credentials = await self.assume_role(
                    integration.role_arn,
                    integration.aws_region,
                    external_id=external_id
                )

                # Update with new encrypted credentials
                integration.access_key_id = token_processor.encrypt(credentials["access_key_id"])
                integration.secret_access_key = token_processor.encrypt(credentials["secret_access_key"])
                integration.session_token = token_processor.encrypt(credentials["session_token"])
                integration.credentials_expiration = credentials["expiration"]
                integration.last_verified_at = now

                await db.commit()
                await db.refresh(integration)

            except Exception as e:
                logger.error(
                    f"Failed to refresh AWS credentials for workspace {workspace_id}: {str(e)}",
                    exc_info=True,
                    extra={
                        "workspace_id": workspace_id,
                        "role_arn": integration.role_arn,
                        "expiration": integration.credentials_expiration,
                    }
                )
                raise Exception(f"Failed to refresh expired AWS credentials: {str(e)}")

        return AWSIntegrationResponse(
            id=integration.id,
            workspace_id=integration.workspace_id,
            role_arn=integration.role_arn,
            has_external_id=integration.external_id is not None,
            aws_region=integration.aws_region,
            is_active=integration.is_active,
            credentials_expiration=integration.credentials_expiration,
            last_verified_at=integration.last_verified_at,
            created_at=integration.created_at,
            updated_at=integration.updated_at,
        )

    async def get_decrypted_credentials(
        self, db: AsyncSession, workspace_id: str
    ) -> Optional[Dict[str, str]]:
        """
        Get decrypted AWS credentials for a workspace
        Automatically refreshes if expired

        Args:
            db: Database session
            workspace_id: Workspace ID

        Returns:
            Dict with access_key_id, secret_access_key, session_token, region or None
        """
        result = await db.execute(
            select(AWSIntegration).where(
                AWSIntegration.workspace_id == workspace_id,
                AWSIntegration.is_active.is_(True),
            )
        )
        integration = result.scalar_one_or_none()

        if not integration:
            return None

        # Check if credentials need refresh (same logic as get_aws_integration)
        now = datetime.now(timezone.utc)
        expiration_threshold = now + timedelta(minutes=5)

        if integration.credentials_expiration <= expiration_threshold:
            # Refresh credentials
            try:
                # Decrypt external_id if present
                external_id = token_processor.decrypt(integration.external_id) if integration.external_id else None

                credentials = await self.assume_role(
                    integration.role_arn,
                    integration.aws_region,
                    external_id=external_id
                )

                # Update with new encrypted credentials
                integration.access_key_id = token_processor.encrypt(credentials["access_key_id"])
                integration.secret_access_key = token_processor.encrypt(credentials["secret_access_key"])
                integration.session_token = token_processor.encrypt(credentials["session_token"])
                integration.credentials_expiration = credentials["expiration"]
                integration.last_verified_at = now

                await db.commit()
                await db.refresh(integration)

            except Exception as e:
                logger.error(
                    f"Failed to refresh AWS credentials for workspace {workspace_id}: {str(e)}",
                    exc_info=True,
                    extra={
                        "workspace_id": workspace_id,
                        "role_arn": integration.role_arn,
                        "expiration": integration.credentials_expiration,
                    }
                )
                raise Exception(f"Failed to refresh expired AWS credentials: {str(e)}")

        # Decrypt and return credentials
        return {
            "access_key_id": token_processor.decrypt(integration.access_key_id),
            "secret_access_key": token_processor.decrypt(integration.secret_access_key),
            "session_token": token_processor.decrypt(integration.session_token),
            "region": integration.aws_region,
        }

    async def delete_aws_integration(
        self, db: AsyncSession, workspace_id: str
    ) -> bool:
        """
        Delete (soft delete) an AWS integration

        Args:
            db: Database session
            workspace_id: Workspace ID

        Returns:
            bool: True if deleted, False if not found
        """
        result = await db.execute(
            select(AWSIntegration).where(
                AWSIntegration.workspace_id == workspace_id,
                AWSIntegration.is_active.is_(True),
            )
        )
        integration = result.scalar_one_or_none()

        if not integration:
            return False

        integration.is_active = False
        await db.commit()
        return True


# Create service instance
aws_integration_service = AWSIntegrationService()
