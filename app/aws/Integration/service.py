"""
AWS Integration Service
Handles CRUD operations and credential management for AWS integrations
"""
import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
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
    """Service for managing AWS integrations"""

    @staticmethod
    def _mask_access_key(access_key_id: str) -> str:
        """Mask AWS Access Key ID for display"""
        if len(access_key_id) <= 8:
            return "****"
        return access_key_id[:4] + "*" * (len(access_key_id) - 8) + access_key_id[-4:]

    @staticmethod
    async def verify_aws_credentials(
        access_key_id: str, secret_access_key: str, region: str = "us-east-1"
    ) -> AWSIntegrationVerifyResponse:
        """
        Verify AWS credentials and CloudWatch Logs access

        Args:
            access_key_id: AWS Access Key ID
            secret_access_key: AWS Secret Access Key
            region: AWS Region

        Returns:
            AWSIntegrationVerifyResponse with verification result
        """
        account_id = None

        try:
            # Step 1: Verify credentials using STS
            sts_client = boto3.client(
                "sts",
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                region_name=region,
            )

            # Make a test call to get caller identity
            sts_response = sts_client.get_caller_identity()
            account_id = sts_response.get("Account")

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))

            # Handle authentication errors
            if error_code in ["InvalidClientTokenId", "SignatureDoesNotMatch"]:
                return AWSIntegrationVerifyResponse(
                    is_valid=False,
                    message="Authentication Error: Invalid AWS Access Key ID or Secret Access Key. Please check your credentials.",
                )
            elif error_code == "AccessDenied":
                return AWSIntegrationVerifyResponse(
                    is_valid=False,
                    message=f"Authentication Error: Access denied for STS service - {error_message}",
                )
            else:
                return AWSIntegrationVerifyResponse(
                    is_valid=False,
                    message=f"Authentication Error: {error_code} - {error_message}",
                )
        except Exception as e:
            return AWSIntegrationVerifyResponse(
                is_valid=False,
                message=f"Authentication Error: Unable to verify credentials - {str(e)}"
            )

        # Step 2: Verify CloudWatch Logs access (covers logs, metrics, and traces)
        try:
            logs_client = boto3.client(
                "logs",
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                region_name=region,
            )
            # Test CloudWatch Logs access
            logs_client.describe_log_groups(limit=1)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))

            if error_code == "AccessDeniedException" or error_code == "AccessDenied":
                return AWSIntegrationVerifyResponse(
                    is_valid=False,
                    message="CloudWatch Access Error: Missing permissions for CloudWatch. Required permissions: logs:DescribeLogGroups, cloudwatch:*, xray:*",
                    account_id=account_id,
                )
            return AWSIntegrationVerifyResponse(
                is_valid=False,
                message=f"CloudWatch Access Error: {error_code} - {error_message}",
                account_id=account_id,
            )
        except Exception as e:
            return AWSIntegrationVerifyResponse(
                is_valid=False,
                message=f"CloudWatch Access Error: {str(e)}",
                account_id=account_id,
            )

        # All verifications passed
        return AWSIntegrationVerifyResponse(
            is_valid=True,
            message="AWS credentials verified successfully with CloudWatch access",
            account_id=account_id,
        )

    async def create_aws_integration(
        self,
        db: AsyncSession,
        workspace_id: str,
        integration_data: AWSIntegrationCreate,
    ) -> AWSIntegrationResponse:
        """
        Create a new AWS integration for a workspace

        Args:
            db: Database session
            workspace_id: Workspace ID
            integration_data: AWS integration data

        Returns:
            AWSIntegrationResponse

        Raises:
            ValueError: If integration already exists or credentials are invalid
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

        # Verify credentials before saving
        verification = await self.verify_aws_credentials(
            integration_data.aws_access_key_id,
            integration_data.aws_secret_access_key,
            integration_data.aws_region if integration_data.aws_region else "us-east-1",
        )

        if not verification.is_valid:
            raise ValueError(f"Invalid AWS credentials: {verification.message}")

        # Encrypt credentials
        encrypted_access_key = token_processor.encrypt(
            integration_data.aws_access_key_id
        )
        encrypted_secret_key = token_processor.encrypt(
            integration_data.aws_secret_access_key
        )

        # Create new integration
        integration = AWSIntegration(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            aws_access_key_id=encrypted_access_key,
            aws_secret_access_key=encrypted_secret_key,
            aws_region=integration_data.aws_region,
            is_active=True,
            last_verified_at=datetime.now(timezone.utc),
        )

        db.add(integration)
        await db.commit()
        await db.refresh(integration)

        return AWSIntegrationResponse(
            id=integration.id,
            workspace_id=integration.workspace_id,
            aws_region=integration.aws_region,
            is_active=integration.is_active,
            last_verified_at=integration.last_verified_at,
            created_at=integration.created_at,
            updated_at=integration.updated_at,
            aws_access_key_id_masked=self._mask_access_key(
                integration_data.aws_access_key_id
            ),
        )

    async def get_aws_integration(
        self, db: AsyncSession, workspace_id: str
    ) -> Optional[AWSIntegrationResponse]:
        """
        Get AWS integration for a workspace

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

        # Decrypt access key for masking
        decrypted_access_key = token_processor.decrypt(integration.aws_access_key_id)

        return AWSIntegrationResponse(
            id=integration.id,
            workspace_id=integration.workspace_id,
            aws_region=integration.aws_region,
            is_active=integration.is_active,
            last_verified_at=integration.last_verified_at,
            created_at=integration.created_at,
            updated_at=integration.updated_at,
            aws_access_key_id_masked=self._mask_access_key(decrypted_access_key),
        )

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
