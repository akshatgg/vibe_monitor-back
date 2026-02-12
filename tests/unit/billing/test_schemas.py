"""
Unit tests for billing schemas.
Tests validation rules, Field constraints, and edge cases for AIU-based schemas.
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from app.billing.schemas import (
    PlanResponse,
    SubscribeToProRequest,
    CancelSubscriptionRequest,
    UpdateServiceCountRequest,
    UsageResponse,
)
from app.models import PlanType


class TestPlanResponse:
    """Tests for PlanResponse schema."""

    def test_valid_plan_response(self):
        """Valid plan data should pass validation."""
        plan = PlanResponse(
            id="plan-123",
            name="Pro",
            plan_type=PlanType.PRO,
            stripe_price_id="price_123",
            base_service_count=3,
            base_price_cents=3000,
            additional_service_price_cents=500,
            aiu_limit_weekly_base=3_000_000,
            aiu_limit_weekly_per_service=500_000,
            is_active=True,
        )
        assert plan.name == "Pro"
        assert plan.base_price_dollars == 30.0
        assert plan.additional_service_price_dollars == 5.0

    def test_price_conversion_to_dollars(self):
        """Cents should convert to dollars correctly."""
        plan = PlanResponse(
            id="plan-123",
            name="Pro",
            plan_type=PlanType.PRO,
            base_service_count=3,
            base_price_cents=3000,
            additional_service_price_cents=500,
            aiu_limit_weekly_base=3_000_000,
            aiu_limit_weekly_per_service=500_000,
            is_active=True,
        )
        assert plan.base_price_dollars == 30.0
        assert plan.additional_service_price_dollars == 5.0


class TestSubscribeToProRequest:
    """Tests for SubscribeToProRequest schema."""

    def test_valid_request(self):
        """Valid subscription request should pass validation."""
        request = SubscribeToProRequest(
            success_url="https://app.example.com/billing?success=true",
            cancel_url="https://app.example.com/billing?canceled=true",
        )
        assert request.success_url == "https://app.example.com/billing?success=true"

    def test_missing_urls_rejected(self):
        """Missing required URLs should be rejected."""
        with pytest.raises(ValidationError):
            SubscribeToProRequest()  # type: ignore


class TestCancelSubscriptionRequest:
    """Tests for CancelSubscriptionRequest schema."""

    def test_immediate_false_by_default(self):
        """Immediate should default to False."""
        request = CancelSubscriptionRequest()
        assert request.immediate is False

    def test_immediate_true(self):
        """Can set immediate to True."""
        request = CancelSubscriptionRequest(immediate=True)
        assert request.immediate is True


class TestUpdateServiceCountRequest:
    """Tests for UpdateServiceCountRequest schema."""

    def test_valid_service_count(self):
        """Valid service count should pass validation."""
        request = UpdateServiceCountRequest(service_count=5)
        assert request.service_count == 5

    def test_negative_service_count_rejected(self):
        """Negative service count should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            UpdateServiceCountRequest(service_count=-1)
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_zero_service_count_allowed(self):
        """Zero service count should be allowed."""
        request = UpdateServiceCountRequest(service_count=0)
        assert request.service_count == 0


class TestUsageResponse:
    """Tests for UsageResponse schema (weekly AIU limits)."""

    def test_valid_free_plan_usage(self):
        """Valid Free plan usage should pass validation."""
        usage = UsageResponse(
            plan_name="Free",
            plan_type="free",
            is_paid=False,
            is_byollm=False,
            service_count=1,
            service_limit=2,
            services_remaining=1,
            can_add_service=True,
            aiu_used_this_week=50_000,
            aiu_weekly_limit=100_000,
            aiu_remaining=50_000,
            can_use_aiu=True,
        )
        assert usage.plan_name == "Free"
        assert usage.aiu_used_this_week == 50_000
        assert usage.aiu_remaining == 50_000

    def test_valid_pro_plan_usage(self):
        """Valid Pro plan usage should pass validation."""
        usage = UsageResponse(
            plan_name="Pro",
            plan_type="pro",
            is_paid=True,
            is_byollm=False,
            service_count=5,
            service_limit=3,
            services_remaining=0,
            can_add_service=True,
            aiu_used_this_week=1_500_000,
            aiu_weekly_limit=4_000_000,
            aiu_remaining=2_500_000,
            can_use_aiu=True,
            subscription_status="ACTIVE",
            current_period_end=datetime.now(timezone.utc),
        )
        assert usage.plan_name == "Pro"
        assert usage.is_paid is True
        assert usage.aiu_weekly_limit == 4_000_000

    def test_byollm_unlimited_usage(self):
        """BYOLLM users should show -1 for unlimited."""
        usage = UsageResponse(
            plan_name="Pro",
            plan_type="pro",
            is_paid=True,
            is_byollm=True,
            service_count=10,
            service_limit=3,
            services_remaining=0,
            can_add_service=True,
            aiu_used_this_week=0,
            aiu_weekly_limit=-1,  # -1 = unlimited
            aiu_remaining=-1,      # -1 = unlimited
            can_use_aiu=True,
        )
        assert usage.is_byollm is True
        assert usage.aiu_weekly_limit == -1
        assert usage.aiu_remaining == -1

    def test_at_limit_usage(self):
        """Usage at limit should be valid."""
        usage = UsageResponse(
            plan_name="Free",
            plan_type="free",
            is_paid=False,
            is_byollm=False,
            service_count=2,
            service_limit=2,
            services_remaining=0,
            can_add_service=False,
            aiu_used_this_week=100_000,
            aiu_weekly_limit=100_000,
            aiu_remaining=0,
            can_use_aiu=False,
        )
        assert usage.can_add_service is False
        assert usage.can_use_aiu is False
        assert usage.aiu_remaining == 0

    # Validation tests for Field constraints

    def test_negative_service_count_rejected(self):
        """Negative service_count should be rejected (ge=0)."""
        with pytest.raises(ValidationError) as exc_info:
            UsageResponse(
                plan_name="Free",
                plan_type="free",
                is_paid=False,
                is_byollm=False,
                service_count=-1,  # ❌ Invalid
                service_limit=2,
                services_remaining=0,
                can_add_service=True,
                aiu_used_this_week=0,
                aiu_weekly_limit=100_000,
                aiu_remaining=100_000,
                can_use_aiu=True,
            )
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_negative_service_limit_rejected(self):
        """Negative service_limit should be rejected (ge=0)."""
        with pytest.raises(ValidationError) as exc_info:
            UsageResponse(
                plan_name="Free",
                plan_type="free",
                is_paid=False,
                is_byollm=False,
                service_count=1,
                service_limit=-2,  # ❌ Invalid
                services_remaining=0,
                can_add_service=True,
                aiu_used_this_week=0,
                aiu_weekly_limit=100_000,
                aiu_remaining=100_000,
                can_use_aiu=True,
            )
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_negative_services_remaining_rejected(self):
        """Negative services_remaining should be rejected (ge=0)."""
        with pytest.raises(ValidationError) as exc_info:
            UsageResponse(
                plan_name="Free",
                plan_type="free",
                is_paid=False,
                is_byollm=False,
                service_count=1,
                service_limit=2,
                services_remaining=-1,  # ❌ Invalid
                can_add_service=True,
                aiu_used_this_week=0,
                aiu_weekly_limit=100_000,
                aiu_remaining=100_000,
                can_use_aiu=True,
            )
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_negative_aiu_used_rejected(self):
        """Negative aiu_used_this_week should be rejected (ge=0)."""
        with pytest.raises(ValidationError) as exc_info:
            UsageResponse(
                plan_name="Free",
                plan_type="free",
                is_paid=False,
                is_byollm=False,
                service_count=1,
                service_limit=2,
                services_remaining=1,
                can_add_service=True,
                aiu_used_this_week=-5000,  # ❌ Invalid
                aiu_weekly_limit=100_000,
                aiu_remaining=100_000,
                can_use_aiu=True,
            )
        assert "greater than or equal to 0" in str(exc_info.value)

    def test_invalid_aiu_weekly_limit_rejected(self):
        """aiu_weekly_limit less than -1 should be rejected (ge=-1)."""
        with pytest.raises(ValidationError) as exc_info:
            UsageResponse(
                plan_name="Free",
                plan_type="free",
                is_paid=False,
                is_byollm=False,
                service_count=1,
                service_limit=2,
                services_remaining=1,
                can_add_service=True,
                aiu_used_this_week=0,
                aiu_weekly_limit=-5,  # ❌ Invalid (only -1 or positive allowed)
                aiu_remaining=0,
                can_use_aiu=True,
            )
        assert "greater than or equal to -1" in str(exc_info.value)

    def test_invalid_aiu_remaining_rejected(self):
        """aiu_remaining less than -1 should be rejected (ge=-1)."""
        with pytest.raises(ValidationError) as exc_info:
            UsageResponse(
                plan_name="Free",
                plan_type="free",
                is_paid=False,
                is_byollm=False,
                service_count=1,
                service_limit=2,
                services_remaining=1,
                can_add_service=True,
                aiu_used_this_week=0,
                aiu_weekly_limit=100_000,
                aiu_remaining=-999,  # ❌ Invalid (only -1 or positive allowed)
                can_use_aiu=True,
            )
        assert "greater than or equal to -1" in str(exc_info.value)

    def test_zero_values_allowed(self):
        """Zero values should be allowed for counts."""
        usage = UsageResponse(
            plan_name="Free",
            plan_type="free",
            is_paid=False,
            is_byollm=False,
            service_count=0,  # ✅ Valid
            service_limit=0,  # ✅ Valid (edge case)
            services_remaining=0,  # ✅ Valid
            can_add_service=False,
            aiu_used_this_week=0,  # ✅ Valid
            aiu_weekly_limit=0,    # ✅ Valid (edge case)
            aiu_remaining=0,       # ✅ Valid
            can_use_aiu=False,
        )
        assert usage.service_count == 0
        assert usage.aiu_used_this_week == 0

    def test_large_aiu_values(self):
        """Large AIU values should be valid."""
        usage = UsageResponse(
            plan_name="Pro",
            plan_type="pro",
            is_paid=True,
            is_byollm=False,
            service_count=100,
            service_limit=50,
            services_remaining=0,
            can_add_service=True,
            aiu_used_this_week=50_000_000,  # 50M
            aiu_weekly_limit=100_000_000,   # 100M
            aiu_remaining=50_000_000,       # 50M
            can_use_aiu=True,
        )
        assert usage.aiu_used_this_week == 50_000_000
        assert usage.aiu_weekly_limit == 100_000_000

    def test_optional_fields_can_be_none(self):
        """Optional subscription fields can be None."""
        usage = UsageResponse(
            plan_name="Free",
            plan_type="free",
            is_paid=False,
            is_byollm=False,
            service_count=1,
            service_limit=2,
            services_remaining=1,
            can_add_service=True,
            aiu_used_this_week=50_000,
            aiu_weekly_limit=100_000,
            aiu_remaining=50_000,
            can_use_aiu=True,
            subscription_status=None,  # ✅ Optional
            current_period_end=None,   # ✅ Optional
        )
        assert usage.subscription_status is None
        assert usage.current_period_end is None
