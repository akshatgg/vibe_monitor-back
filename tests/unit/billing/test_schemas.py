"""
Unit tests for billing schemas.
Tests validation rules, computed properties, and model configuration.
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from app.billing.schemas import (
    PlanResponse,
    SubscribeToProRequest,
    CancelSubscriptionRequest,
    UpdateServiceCountRequest,
    UsageLimitsResponse,
    UsageResponse,
)
from app.workspace.client_workspace_services.schemas import (
    FREE_TIER_SERVICE_LIMIT,
    ServiceCreate,
    ServiceUpdate,
    ServiceResponse,
    ServiceCountResponse,
)
from app.models import PlanType


class TestConstants:
    """Tests for billing constants."""

    def test_free_tier_service_limit(self):
        """FREE_TIER_SERVICE_LIMIT should be 5."""
        assert FREE_TIER_SERVICE_LIMIT == 5


class TestServiceCreate:
    """Tests for ServiceCreate schema validation."""

    def test_valid_service_create(self):
        """Valid service creation data should pass validation."""
        data = ServiceCreate(name="api-service", repository_name="org/repo")
        assert data.name == "api-service"
        assert data.repository_name == "org/repo"

    def test_name_required(self):
        """Name is required."""
        with pytest.raises(ValidationError) as exc_info:
            ServiceCreate(repository_name="org/repo")  # type: ignore
        assert "name" in str(exc_info.value)

    def test_repository_name_required(self):
        """Repository name is required."""
        with pytest.raises(ValidationError) as exc_info:
            ServiceCreate(name="api-service")  # type: ignore
        assert "repository_name" in str(exc_info.value)

    def test_name_min_length(self):
        """Name must be at least 1 character."""
        with pytest.raises(ValidationError) as exc_info:
            ServiceCreate(name="", repository_name="org/repo")
        assert "min_length" in str(exc_info.value).lower() or "at least 1" in str(
            exc_info.value
        )

    def test_name_max_length(self):
        """Name must be at most 255 characters."""
        long_name = "a" * 256
        with pytest.raises(ValidationError) as exc_info:
            ServiceCreate(name=long_name, repository_name="org/repo")
        assert "max_length" in str(exc_info.value).lower() or "255" in str(
            exc_info.value
        )

    def test_repository_name_min_length(self):
        """Repository name must be at least 1 character."""
        with pytest.raises(ValidationError) as exc_info:
            ServiceCreate(name="api-service", repository_name="")
        assert "min_length" in str(exc_info.value).lower() or "at least 1" in str(
            exc_info.value
        )


class TestServiceUpdate:
    """Tests for ServiceUpdate schema validation."""

    def test_all_fields_optional(self):
        """All fields should be optional."""
        data = ServiceUpdate()
        assert data.name is None
        assert data.repository_name is None
        assert data.enabled is None

    def test_partial_update_name_only(self):
        """Can update just the name."""
        data = ServiceUpdate(name="new-name")
        assert data.name == "new-name"
        assert data.repository_name is None
        assert data.enabled is None

    def test_partial_update_enabled_only(self):
        """Can update just enabled status."""
        data = ServiceUpdate(enabled=False)
        assert data.name is None
        assert data.enabled is False

    def test_name_validation_when_provided(self):
        """Name validation applies when value is provided."""
        with pytest.raises(ValidationError):
            ServiceUpdate(name="")  # Empty string should fail


class TestServiceCountResponse:
    """Tests for ServiceCountResponse schema."""

    def test_default_values(self):
        """Default values should match free tier."""
        data = ServiceCountResponse(current_count=3)
        assert data.limit == FREE_TIER_SERVICE_LIMIT
        assert data.can_add_more is True
        assert data.is_paid is False

    def test_custom_values(self):
        """Custom values should override defaults."""
        data = ServiceCountResponse(
            current_count=10, limit=20, can_add_more=True, is_paid=True
        )
        assert data.current_count == 10
        assert data.limit == 20
        assert data.can_add_more is True
        assert data.is_paid is True


class TestPlanResponse:
    """Tests for PlanResponse schema and computed properties."""

    def test_base_price_dollars_property(self):
        """base_price_dollars should convert cents to dollars."""
        data = PlanResponse(
            id="plan-1",
            name="Pro",
            plan_type=PlanType.PRO,
            base_service_count=10,
            base_price_cents=3000,  # $30.00
            additional_service_price_cents=500,  # $5.00
            rca_session_limit_daily=100,
            is_active=True,
        )
        assert data.base_price_dollars == 30.0

    def test_additional_service_price_dollars_property(self):
        """additional_service_price_dollars should convert cents to dollars."""
        data = PlanResponse(
            id="plan-1",
            name="Pro",
            plan_type=PlanType.PRO,
            base_service_count=10,
            base_price_cents=3000,
            additional_service_price_cents=550,  # $5.50
            rca_session_limit_daily=100,
            is_active=True,
        )
        assert data.additional_service_price_dollars == 5.5

    def test_zero_price_conversion(self):
        """Zero cents should convert to zero dollars."""
        data = PlanResponse(
            id="plan-1",
            name="Free",
            plan_type=PlanType.FREE,
            base_service_count=5,
            base_price_cents=0,
            additional_service_price_cents=0,
            rca_session_limit_daily=10,
            is_active=True,
        )
        assert data.base_price_dollars == 0.0
        assert data.additional_service_price_dollars == 0.0

    def test_fractional_dollar_amounts(self):
        """Fractional amounts should be calculated correctly."""
        data = PlanResponse(
            id="plan-1",
            name="Pro",
            plan_type=PlanType.PRO,
            base_service_count=10,
            base_price_cents=2999,  # $29.99
            additional_service_price_cents=199,  # $1.99
            rca_session_limit_daily=100,
            is_active=True,
        )
        assert data.base_price_dollars == 29.99
        assert data.additional_service_price_dollars == 1.99


class TestSubscribeToProRequest:
    """Tests for SubscribeToProRequest schema validation."""

    def test_valid_urls(self):
        """Valid URLs should pass validation."""
        data = SubscribeToProRequest(
            success_url="https://app.example.com/success",
            cancel_url="https://app.example.com/cancel",
        )
        assert data.success_url == "https://app.example.com/success"
        assert data.cancel_url == "https://app.example.com/cancel"

    def test_urls_required(self):
        """Both URLs are required."""
        with pytest.raises(ValidationError):
            SubscribeToProRequest()  # type: ignore


class TestCancelSubscriptionRequest:
    """Tests for CancelSubscriptionRequest schema."""

    def test_default_immediate_false(self):
        """immediate should default to False."""
        data = CancelSubscriptionRequest()
        assert data.immediate is False

    def test_immediate_can_be_true(self):
        """immediate can be set to True."""
        data = CancelSubscriptionRequest(immediate=True)
        assert data.immediate is True


class TestUpdateServiceCountRequest:
    """Tests for UpdateServiceCountRequest schema validation."""

    def test_valid_service_count(self):
        """Valid service count should pass."""
        data = UpdateServiceCountRequest(service_count=10)
        assert data.service_count == 10

    def test_zero_service_count_allowed(self):
        """Zero service count should be allowed (ge=0)."""
        data = UpdateServiceCountRequest(service_count=0)
        assert data.service_count == 0

    def test_negative_service_count_rejected(self):
        """Negative service count should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            UpdateServiceCountRequest(service_count=-1)
        assert "greater than or equal" in str(exc_info.value).lower()


class TestUsageLimitsResponse:
    """Tests for UsageLimitsResponse schema and computed properties."""

    def test_estimated_monthly_cost_dollars_property(self):
        """estimated_monthly_cost_dollars should convert cents to dollars."""
        data = UsageLimitsResponse(
            plan_name="Pro",
            plan_type=PlanType.PRO,
            base_service_count=10,
            current_service_count=15,
            billable_service_count=5,
            daily_rca_limit=100,
            daily_rca_used=25,
            daily_rca_remaining=75,
            is_paid=True,
            estimated_monthly_cost_cents=5500,  # $55.00
        )
        assert data.estimated_monthly_cost_dollars == 55.0

    def test_zero_cost(self):
        """Zero cost should convert correctly."""
        data = UsageLimitsResponse(
            plan_name="Free",
            plan_type=PlanType.FREE,
            base_service_count=5,
            current_service_count=3,
            billable_service_count=0,
            daily_rca_limit=10,
            daily_rca_used=5,
            daily_rca_remaining=5,
            is_paid=False,
            estimated_monthly_cost_cents=0,
        )
        assert data.estimated_monthly_cost_dollars == 0.0


class TestServiceResponse:
    """Tests for ServiceResponse schema."""

    def test_from_attributes_config(self):
        """model_config should have from_attributes=True."""
        assert ServiceResponse.model_config.get("from_attributes") is True

    def test_optional_fields(self):
        """Optional fields should allow None."""
        data = ServiceResponse(
            id="svc-1",
            workspace_id="ws-1",
            name="test-service",
            enabled=True,
        )
        assert data.repository_id is None
        assert data.repository_name is None
        assert data.created_at is None
        assert data.updated_at is None


class TestUsageResponse:
    """Tests for UsageResponse schema."""

    def test_all_fields(self):
        """All fields should be settable."""
        now = datetime.now(timezone.utc)
        data = UsageResponse(
            plan_name="Pro",
            plan_type="pro",
            is_paid=True,
            service_count=15,
            service_limit=10,  # Pro base count (can exceed with $5/each additional)
            services_remaining=0,  # max(0, 10-15) = 0 (over base, paying for 5 additional)
            can_add_service=True,  # Pro can always add more services
            rca_sessions_today=25,
            rca_session_limit_daily=100,
            rca_sessions_remaining=75,
            can_start_rca=True,
            subscription_status="active",
            current_period_end=now,
        )
        assert data.service_limit == 10
        assert data.services_remaining == 0
        assert data.can_add_service is True

    def test_free_tier_limits(self):
        """Free tier should have limits set."""
        data = UsageResponse(
            plan_name="Free",
            plan_type="free",
            is_paid=False,
            service_count=3,
            service_limit=5,
            services_remaining=2,
            can_add_service=True,
            rca_sessions_today=8,
            rca_session_limit_daily=10,
            rca_sessions_remaining=2,
            can_start_rca=True,
        )
        assert data.service_limit == 5
        assert data.services_remaining == 2
