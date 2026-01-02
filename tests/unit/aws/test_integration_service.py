"""
Unit tests for AWS Integration Service
Focus on pure functions and validation logic (no DB-heavy tests)
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestBypassLocalstack:
    """Tests for the _bypass_localstack context manager"""

    def test_bypass_removes_endpoint_url_when_set(self):
        """Test that AWS_ENDPOINT_URL is removed within the context"""
        from app.aws.Integration.service import AWSIntegrationService

        # Set the environment variable
        os.environ["AWS_ENDPOINT_URL"] = "http://localhost:4566"

        with AWSIntegrationService._bypass_localstack():
            # Inside context, env var should be removed
            assert "AWS_ENDPOINT_URL" not in os.environ

        # After context, env var should be restored
        assert os.environ.get("AWS_ENDPOINT_URL") == "http://localhost:4566"

        # Cleanup
        del os.environ["AWS_ENDPOINT_URL"]

    def test_bypass_does_nothing_when_not_set(self):
        """Test that nothing happens when AWS_ENDPOINT_URL is not set"""
        from app.aws.Integration.service import AWSIntegrationService

        # Ensure the env var is not set
        if "AWS_ENDPOINT_URL" in os.environ:
            del os.environ["AWS_ENDPOINT_URL"]

        with AWSIntegrationService._bypass_localstack():
            # Should still not be set
            assert "AWS_ENDPOINT_URL" not in os.environ

        # Should still not be set after context
        assert "AWS_ENDPOINT_URL" not in os.environ

    def test_bypass_restores_on_exception(self):
        """Test that AWS_ENDPOINT_URL is restored even if exception occurs"""
        from app.aws.Integration.service import AWSIntegrationService

        os.environ["AWS_ENDPOINT_URL"] = "http://localhost:4566"

        with pytest.raises(ValueError):
            with AWSIntegrationService._bypass_localstack():
                assert "AWS_ENDPOINT_URL" not in os.environ
                raise ValueError("Test exception")

        # Should be restored even after exception
        assert os.environ.get("AWS_ENDPOINT_URL") == "http://localhost:4566"

        # Cleanup
        del os.environ["AWS_ENDPOINT_URL"]


class TestCreateBotoClient:
    """Tests for the _create_boto_client static method"""

    @patch("app.aws.Integration.service.boto3")
    def test_create_client_without_credentials(self, mock_boto3):
        """Test client creation without explicit credentials"""
        from app.aws.Integration.service import AWSIntegrationService

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        result = AWSIntegrationService._create_boto_client(
            service_name="sts",
            region_name="us-west-1",
        )

        mock_boto3.client.assert_called_once_with(
            "sts",
            region_name="us-west-1",
        )
        assert result == mock_client

    @patch("app.aws.Integration.service.boto3")
    def test_create_client_with_credentials(self, mock_boto3):
        """Test client creation with explicit credentials"""
        from app.aws.Integration.service import AWSIntegrationService

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        result = AWSIntegrationService._create_boto_client(
            service_name="sts",
            region_name="us-east-1",
            access_key_id="AKIAIOSFODNN7EXAMPLE",
            secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            session_token="FwoGZXIvYXdzEBY...",
        )

        mock_boto3.client.assert_called_once_with(
            "sts",
            region_name="us-east-1",
            aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
            aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            aws_session_token="FwoGZXIvYXdzEBY...",
        )
        assert result == mock_client

    @patch("app.aws.Integration.service.boto3")
    def test_create_client_with_partial_credentials(self, mock_boto3):
        """Test client creation with partial credentials (only access key)"""
        from app.aws.Integration.service import AWSIntegrationService

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        result = AWSIntegrationService._create_boto_client(
            service_name="logs",
            region_name="eu-west-1",
            access_key_id="AKIAIOSFODNN7EXAMPLE",
        )

        mock_boto3.client.assert_called_once_with(
            "logs",
            region_name="eu-west-1",
            aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
        )
        assert result == mock_client


class TestAWSIntegrationVerifyResponse:
    """Tests for AWSIntegrationVerifyResponse schema"""

    def test_valid_response(self):
        """Test creating a valid verify response"""
        from app.aws.Integration.schemas import AWSIntegrationVerifyResponse

        response = AWSIntegrationVerifyResponse(
            is_valid=True,
            message="AWS role verified successfully",
            account_id="123456789012",
        )

        assert response.is_valid is True
        assert response.message == "AWS role verified successfully"
        assert response.account_id == "123456789012"

    def test_invalid_response(self):
        """Test creating an invalid verify response"""
        from app.aws.Integration.schemas import AWSIntegrationVerifyResponse

        response = AWSIntegrationVerifyResponse(
            is_valid=False,
            message="Access denied",
            account_id=None,
        )

        assert response.is_valid is False
        assert response.message == "Access denied"
        assert response.account_id is None


class TestAWSIntegrationCreate:
    """Tests for AWSIntegrationCreate schema"""

    def test_valid_create_request(self):
        """Test creating a valid integration request"""
        from app.aws.Integration.schemas import AWSIntegrationCreate

        request = AWSIntegrationCreate(
            role_arn="arn:aws:iam::123456789012:role/VibeMonitor",
            external_id="my-external-id",
            aws_region="us-west-2",
        )

        assert request.role_arn == "arn:aws:iam::123456789012:role/VibeMonitor"
        assert request.external_id == "my-external-id"
        assert request.aws_region == "us-west-2"

    def test_default_region(self):
        """Test that default region is us-west-1"""
        from app.aws.Integration.schemas import AWSIntegrationCreate

        request = AWSIntegrationCreate(
            role_arn="arn:aws:iam::123456789012:role/VibeMonitor",
        )

        assert request.aws_region == "us-west-1"
        assert request.external_id is None

    def test_optional_external_id(self):
        """Test that external_id is optional"""
        from app.aws.Integration.schemas import AWSIntegrationCreate

        request = AWSIntegrationCreate(
            role_arn="arn:aws:iam::123456789012:role/VibeMonitor",
            aws_region="eu-west-1",
        )

        assert request.external_id is None
        assert request.aws_region == "eu-west-1"
