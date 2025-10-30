"""
AWS Integration Service
Handles CRUD operations and credential management for AWS integrations
Uses STS AssumeRole for temporary credentials instead of long-term access keys
"""
import os
import uuid
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
import boto3
from botocore.exceptions import ClientError

from app.models import AWSIntegration
from app.utils.token_processor import token_processor
from .schemas import (
    AWSIntegrationCreate,
    AWSIntegrationResponse,
    AWSIntegrationVerifyResponse,
)


class AWSIntegrationService:
    """Service for managing AWS integrations using STS AssumeRole"""

    @staticmethod
    async def assume_role(
        role_arn: str,
        region: str = "us-east-1",
        duration_seconds: int = 3600,
        external_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Assume an IAM role and get temporary credentials using STS

        Args:
            role_arn: AWS IAM Role ARN to assume
            region: AWS Region
            duration_seconds: Duration for temporary credentials (default 3600 = 1 hour)
            external_id: Optional external ID for cross-account access security

        Returns:
            Dict containing temporary credentials and expiration

        Raises:
            Exception: If role assumption fails
        """
        try:
            # Create STS client (will use default credentials from environment/EC2 role)
            # Force real AWS by temporarily removing LocalStack endpoint
            
            original_endpoint = os.environ.get('AWS_ENDPOINT_URL')

            # Temporarily remove AWS_ENDPOINT_URL to bypass LocalStack
            if 'AWS_ENDPOINT_URL' in os.environ:
                del os.environ['AWS_ENDPOINT_URL']

            try:
                sts_client = boto3.client("sts", region_name=region)

                # Prepare AssumeRole parameters
                assume_role_params = {
                    "RoleArn": role_arn,
                    "RoleSessionName": "vibe-monitor-session",
                    "DurationSeconds": duration_seconds,
                }

                # Add ExternalId if provided
                if external_id:
                    assume_role_params["ExternalId"] = external_id

                # Assume the role
                response = sts_client.assume_role(**assume_role_params)
            finally:
                # Restore original endpoint for other services (like SQS)
                if original_endpoint:
                    os.environ['AWS_ENDPOINT_URL'] = original_endpoint

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
            raise Exception(f"Failed to assume role: {error_code} - {error_message}")
        except Exception as e:
            raise Exception(f"Failed to assume role: {str(e)}")

    @staticmethod
    async def verify_role_and_permissions(
        role_arn: str, region: str = "us-east-1", external_id: Optional[str] = None
    ) -> AWSIntegrationVerifyResponse:
        """
        Verify that the role can be assumed and has CloudWatch access

        Args:
            role_arn: AWS IAM Role ARN
            region: AWS Region

        Returns:
            AWSIntegrationVerifyResponse with verification result
        """
        account_id = None

        try:
            # Step 1: Try to assume the role
            credentials = await AWSIntegrationService.assume_role(role_arn, region, external_id=external_id)

            # Step 2: Verify CloudWatch Logs access with temporary credentials
            # Always use real AWS for CloudWatch, never LocalStack
            
            original_endpoint = os.environ.get('AWS_ENDPOINT_URL')

            # Temporarily remove AWS_ENDPOINT_URL to bypass LocalStack
            if 'AWS_ENDPOINT_URL' in os.environ:
                del os.environ['AWS_ENDPOINT_URL']

            try:
                logs_client = boto3.client(
                    "logs",
                    aws_access_key_id=credentials["access_key_id"],
                    aws_secret_access_key=credentials["secret_access_key"],
                    aws_session_token=credentials["session_token"],
                    region_name=region,
                )

                # Test CloudWatch Logs access
                logs_client.describe_log_groups(limit=1)
            finally:
                # Restore original endpoint for other services (like SQS)
                if original_endpoint:
                    os.environ['AWS_ENDPOINT_URL'] = original_endpoint

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
                AWSIntegration.is_active == True,
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
                AWSIntegration.is_active == True,
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
                # Log error but still return current integration info
                print(f"Failed to refresh credentials: {str(e)}")

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
                AWSIntegration.is_active == True,
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
                print(f"Failed to refresh credentials: {str(e)}")
                # Continue with existing credentials if refresh fails

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
                AWSIntegration.is_active == True,
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
