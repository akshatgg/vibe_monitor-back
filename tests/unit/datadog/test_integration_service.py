"""
Unit tests for Datadog Integration Service
Focus on pure functions and validation logic (no DB-heavy tests)
"""

import pytest
from pydantic import ValidationError


class TestGetDatadogDomain:
    """Tests for the get_datadog_domain pure function"""

    def test_us1_region(self):
        """Test US1 region maps to datadoghq.com"""
        from app.datadog.integration.service import get_datadog_domain

        assert get_datadog_domain("us1") == "datadoghq.com"

    def test_us3_region(self):
        """Test US3 region maps to us3.datadoghq.com"""
        from app.datadog.integration.service import get_datadog_domain

        assert get_datadog_domain("us3") == "us3.datadoghq.com"

    def test_us5_region(self):
        """Test US5 region maps to us5.datadoghq.com"""
        from app.datadog.integration.service import get_datadog_domain

        assert get_datadog_domain("us5") == "us5.datadoghq.com"

    def test_eu1_region(self):
        """Test EU1 region maps to datadoghq.eu"""
        from app.datadog.integration.service import get_datadog_domain

        assert get_datadog_domain("eu1") == "datadoghq.eu"

    def test_ap1_region(self):
        """Test AP1 region maps to ap1.datadoghq.com"""
        from app.datadog.integration.service import get_datadog_domain

        assert get_datadog_domain("ap1") == "ap1.datadoghq.com"

    def test_us1_fed_region(self):
        """Test US1-FED region maps to ddog-gov.com"""
        from app.datadog.integration.service import get_datadog_domain

        assert get_datadog_domain("us1-fed") == "ddog-gov.com"

    def test_uppercase_region(self):
        """Test uppercase region codes are handled"""
        from app.datadog.integration.service import get_datadog_domain

        assert get_datadog_domain("US1") == "datadoghq.com"
        assert get_datadog_domain("EU1") == "datadoghq.eu"

    def test_mixed_case_region(self):
        """Test mixed case region codes are handled"""
        from app.datadog.integration.service import get_datadog_domain

        assert get_datadog_domain("Us1") == "datadoghq.com"
        assert get_datadog_domain("Eu1") == "datadoghq.eu"

    def test_unknown_region_defaults_to_us1(self):
        """Test unknown region defaults to datadoghq.com (US1)"""
        from app.datadog.integration.service import get_datadog_domain

        assert get_datadog_domain("unknown") == "datadoghq.com"
        assert get_datadog_domain("invalid") == "datadoghq.com"
        assert get_datadog_domain("") == "datadoghq.com"


class TestDatadogIntegrationCreateSchema:
    """Tests for DatadogIntegrationCreate schema validators"""

    def test_valid_integration_create(self):
        """Test creating a valid integration request"""
        from app.datadog.integration.schemas import DatadogIntegrationCreate

        # Valid API key (32+ chars) and App key (40+ chars)
        request = DatadogIntegrationCreate(
            api_key="a" * 32,  # 32 character API key
            app_key="b" * 40,  # 40 character App key
            region="us1",
        )

        assert len(request.api_key) == 32
        assert len(request.app_key) == 40
        assert request.region == "us1"

    def test_api_key_too_short(self):
        """Test that API key shorter than 32 chars is rejected"""
        from app.datadog.integration.schemas import DatadogIntegrationCreate

        with pytest.raises(ValidationError) as exc_info:
            DatadogIntegrationCreate(
                api_key="short_key",  # Too short
                app_key="b" * 40,
                region="us1",
            )

        errors = exc_info.value.errors()
        assert any("too short" in str(e["msg"]).lower() for e in errors)

    def test_api_key_empty(self):
        """Test that empty API key is rejected"""
        from app.datadog.integration.schemas import DatadogIntegrationCreate

        with pytest.raises(ValidationError) as exc_info:
            DatadogIntegrationCreate(
                api_key="",
                app_key="b" * 40,
                region="us1",
            )

        errors = exc_info.value.errors()
        assert any("empty" in str(e["msg"]).lower() for e in errors)

    def test_api_key_whitespace_only(self):
        """Test that whitespace-only API key is rejected"""
        from app.datadog.integration.schemas import DatadogIntegrationCreate

        with pytest.raises(ValidationError) as exc_info:
            DatadogIntegrationCreate(
                api_key="   ",
                app_key="b" * 40,
                region="us1",
            )

        errors = exc_info.value.errors()
        assert len(errors) > 0

    def test_app_key_too_short(self):
        """Test that App key shorter than 40 chars is rejected"""
        from app.datadog.integration.schemas import DatadogIntegrationCreate

        with pytest.raises(ValidationError) as exc_info:
            DatadogIntegrationCreate(
                api_key="a" * 32,
                app_key="short_app_key",  # Too short
                region="us1",
            )

        errors = exc_info.value.errors()
        assert any("too short" in str(e["msg"]).lower() for e in errors)

    def test_app_key_empty(self):
        """Test that empty App key is rejected"""
        from app.datadog.integration.schemas import DatadogIntegrationCreate

        with pytest.raises(ValidationError) as exc_info:
            DatadogIntegrationCreate(
                api_key="a" * 32,
                app_key="",
                region="us1",
            )

        errors = exc_info.value.errors()
        assert any("empty" in str(e["msg"]).lower() for e in errors)

    def test_invalid_region(self):
        """Test that invalid region is rejected"""
        from app.datadog.integration.schemas import DatadogIntegrationCreate

        with pytest.raises(ValidationError) as exc_info:
            DatadogIntegrationCreate(
                api_key="a" * 32,
                app_key="b" * 40,
                region="invalid_region",
            )

        errors = exc_info.value.errors()
        assert any("invalid" in str(e["msg"]).lower() for e in errors)

    def test_all_valid_regions(self):
        """Test that all valid regions are accepted"""
        from app.datadog.integration.schemas import DatadogIntegrationCreate

        valid_regions = ["us1", "us3", "us5", "eu1", "ap1", "us1-fed"]

        for region in valid_regions:
            request = DatadogIntegrationCreate(
                api_key="a" * 32,
                app_key="b" * 40,
                region=region,
            )
            assert request.region == region

    def test_region_case_insensitive(self):
        """Test that region validation is case-insensitive"""
        from app.datadog.integration.schemas import DatadogIntegrationCreate

        request = DatadogIntegrationCreate(
            api_key="a" * 32,
            app_key="b" * 40,
            region="US1",  # Uppercase
        )

        # Should be normalized to lowercase
        assert request.region == "us1"

    def test_api_key_stripped(self):
        """Test that API key is stripped of whitespace"""
        from app.datadog.integration.schemas import DatadogIntegrationCreate

        request = DatadogIntegrationCreate(
            api_key="  " + "a" * 32 + "  ",  # With whitespace
            app_key="b" * 40,
            region="us1",
        )

        assert request.api_key == "a" * 32
        assert len(request.api_key) == 32

    def test_app_key_stripped(self):
        """Test that App key is stripped of whitespace"""
        from app.datadog.integration.schemas import DatadogIntegrationCreate

        request = DatadogIntegrationCreate(
            api_key="a" * 32,
            app_key="  " + "b" * 40 + "  ",  # With whitespace
            region="us1",
        )

        assert request.app_key == "b" * 40
        assert len(request.app_key) == 40


class TestDatadogIntegrationResponseSchema:
    """Tests for DatadogIntegrationResponse schema"""

    def test_valid_response(self):
        """Test creating a valid response"""
        from datetime import datetime, timezone

        from app.datadog.integration.schemas import DatadogIntegrationResponse

        response = DatadogIntegrationResponse(
            id="integration-123",
            workspace_id="workspace-456",
            region="us1",
            last_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        assert response.id == "integration-123"
        assert response.workspace_id == "workspace-456"
        assert response.region == "us1"

    def test_optional_fields(self):
        """Test that optional fields can be None"""
        from datetime import datetime, timezone

        from app.datadog.integration.schemas import DatadogIntegrationResponse

        response = DatadogIntegrationResponse(
            id="integration-123",
            workspace_id="workspace-456",
            region="eu1",
            last_verified_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=None,
        )

        assert response.last_verified_at is None
        assert response.updated_at is None


class TestDatadogIntegrationStatusResponse:
    """Tests for DatadogIntegrationStatusResponse schema"""

    def test_connected_status(self):
        """Test connected status with integration"""
        from datetime import datetime, timezone

        from app.datadog.integration.schemas import (
            DatadogIntegrationResponse,
            DatadogIntegrationStatusResponse,
        )

        integration = DatadogIntegrationResponse(
            id="integration-123",
            workspace_id="workspace-456",
            region="us1",
            last_verified_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=None,
        )

        status = DatadogIntegrationStatusResponse(
            is_connected=True,
            integration=integration,
        )

        assert status.is_connected is True
        assert status.integration is not None
        assert status.integration.id == "integration-123"

    def test_disconnected_status(self):
        """Test disconnected status without integration"""
        from app.datadog.integration.schemas import DatadogIntegrationStatusResponse

        status = DatadogIntegrationStatusResponse(
            is_connected=False,
            integration=None,
        )

        assert status.is_connected is False
        assert status.integration is None
