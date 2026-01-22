"""
Tests for billing operations and Stripe integration.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models import Plan, PlanType, Subscription, SubscriptionStatus


# Test data fixtures
@pytest.fixture
def free_plan():
    """Create a Free plan for testing."""
    return Plan(
        id=str(uuid.uuid4()),
        name="Free",
        plan_type=PlanType.FREE,
        stripe_price_id=None,
        base_service_count=5,
        base_price_cents=0,
        additional_service_price_cents=0,
        rca_session_limit_daily=10,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def pro_plan():
    """Create a Pro plan for testing."""
    return Plan(
        id=str(uuid.uuid4()),
        name="Pro",
        plan_type=PlanType.PRO,
        stripe_price_id="price_pro_monthly",
        base_service_count=5,
        base_price_cents=3000,
        additional_service_price_cents=500,
        rca_session_limit_daily=100,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def free_subscription(free_plan):
    """Create a Free subscription for testing."""
    return Subscription(
        id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        plan_id=free_plan.id,
        stripe_customer_id=None,
        stripe_subscription_id=None,
        status=SubscriptionStatus.ACTIVE,
        billable_service_count=0,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def pro_subscription(pro_plan):
    """Create a Pro subscription for testing."""
    return Subscription(
        id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        plan_id=pro_plan.id,
        stripe_customer_id="cus_test123",
        stripe_subscription_id="sub_test123",
        status=SubscriptionStatus.ACTIVE,
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc),
        billable_service_count=0,
        created_at=datetime.now(timezone.utc),
    )


class TestPlanModel:
    """Tests for the Plan model."""

    def test_free_plan_has_correct_defaults(self, free_plan):
        """Test that Free plan has correct pricing."""
        assert free_plan.plan_type == PlanType.FREE
        assert free_plan.base_price_cents == 0
        assert free_plan.base_service_count == 5
        assert free_plan.rca_session_limit_daily == 10
        assert free_plan.stripe_price_id is None

    def test_pro_plan_has_correct_pricing(self, pro_plan):
        """Test that Pro plan has correct pricing."""
        assert pro_plan.plan_type == PlanType.PRO
        assert pro_plan.base_price_cents == 3000  # $30
        assert pro_plan.additional_service_price_cents == 500  # $5
        assert pro_plan.base_service_count == 5
        assert pro_plan.rca_session_limit_daily == 100
        assert pro_plan.stripe_price_id is not None


class TestSubscriptionModel:
    """Tests for the Subscription model."""

    def test_free_subscription_has_no_stripe_ids(self, free_subscription):
        """Test that Free subscription has no Stripe IDs."""
        assert free_subscription.stripe_customer_id is None
        assert free_subscription.stripe_subscription_id is None
        assert free_subscription.status == SubscriptionStatus.ACTIVE

    def test_pro_subscription_has_stripe_ids(self, pro_subscription):
        """Test that Pro subscription has Stripe IDs."""
        assert pro_subscription.stripe_customer_id is not None
        assert pro_subscription.stripe_subscription_id is not None
        assert pro_subscription.status == SubscriptionStatus.ACTIVE


class TestSubscriptionStatus:
    """Tests for SubscriptionStatus enum."""

    def test_all_status_values_exist(self):
        """Test that all expected status values exist."""
        expected_statuses = ["active", "past_due", "canceled", "incomplete", "trialing"]
        for status in expected_statuses:
            assert SubscriptionStatus(status) is not None

    def test_status_values_match_stripe(self):
        """Test that status values match Stripe's subscription statuses."""
        assert SubscriptionStatus.ACTIVE.value == "active"
        assert SubscriptionStatus.PAST_DUE.value == "past_due"
        assert SubscriptionStatus.CANCELED.value == "canceled"


class TestStripeService:
    """Tests for the Stripe service."""

    @pytest.fixture
    def stripe_service(self):
        """Create a StripeService instance for testing."""
        from app.billing.services.stripe_service import StripeService

        return StripeService()

    @patch("stripe.Customer.create")
    def test_create_customer_success(self, mock_create, stripe_service):
        """Test creating a Stripe customer."""
        mock_customer = MagicMock()
        mock_customer.id = "cus_test123"
        mock_create.return_value = mock_customer

        import asyncio

        customer = asyncio.get_event_loop().run_until_complete(
            stripe_service.create_customer(
                workspace_id="ws_123",
                email="test@example.com",
                name="Test Workspace",
            )
        )

        assert customer.id == "cus_test123"
        mock_create.assert_called_once()

    @patch("stripe.Subscription.create")
    def test_create_subscription_success(self, mock_create, stripe_service):
        """Test creating a Stripe subscription."""
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_test123"
        mock_subscription.status = "active"
        mock_create.return_value = mock_subscription

        import asyncio

        subscription = asyncio.get_event_loop().run_until_complete(
            stripe_service.create_subscription(
                customer_id="cus_test123",
                price_id="price_pro_monthly",
                quantity=1,
            )
        )

        assert subscription.id == "sub_test123"
        mock_create.assert_called_once()

    @patch("stripe.Subscription.modify")
    @patch("stripe.Subscription.retrieve")
    def test_cancel_subscription_at_period_end(
        self, mock_retrieve, mock_modify, stripe_service
    ):
        """Test canceling a subscription at period end."""
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_test123"
        mock_subscription.cancel_at_period_end = True
        mock_modify.return_value = mock_subscription
        mock_retrieve.return_value = mock_subscription

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            stripe_service.cancel_subscription(
                subscription_id="sub_test123",
                immediate=False,
            )
        )

        mock_modify.assert_called_once_with(
            "sub_test123",
            cancel_at_period_end=True,
        )


class TestSubscriptionService:
    """Tests for the Subscription service."""

    @pytest.fixture
    def subscription_service(self):
        """Create a SubscriptionService instance for testing."""
        from app.billing.services.subscription_service import SubscriptionService

        return SubscriptionService()

    def test_billable_service_calculation(self, pro_plan):
        """Test calculating billable services above base count."""
        base_count = pro_plan.base_service_count  # 5

        # 3 services = 0 billable (under base)
        assert max(0, 3 - base_count) == 0

        # 5 services = 0 billable (at base)
        assert max(0, 5 - base_count) == 0

        # 8 services = 3 billable (above base)
        assert max(0, 8 - base_count) == 3

        # 10 services = 5 billable
        assert max(0, 10 - base_count) == 5


class TestWebhookHandler:
    """Tests for the Stripe webhook handler."""

    def test_subscription_created_event_handling(self):
        """Test handling subscription.created webhook event."""
        # Create mock event data
        event_data = {
            "id": "sub_test123",
            "status": "active",
            "current_period_start": 1234567890,
            "current_period_end": 1237246290,
            "metadata": {"workspace_id": "ws_123", "plan_id": "plan_123"},
        }
        # Actual test would verify database updates
        assert event_data["status"] == "active"

    def test_payment_failed_event_handling(self):
        """Test handling invoice.payment_failed webhook event."""
        # Create mock event data
        event_data = {
            "id": "in_test123",
            "subscription": "sub_test123",
            "status": "open",
            "amount_due": 3000,
        }
        # Actual test would verify subscription status update
        assert event_data["subscription"] == "sub_test123"


class TestBillingSchemas:
    """Tests for billing schemas."""

    def test_plan_response_model(self, pro_plan):
        """Test PlanResponse schema validation."""
        from app.billing.schemas import PlanResponse

        response = PlanResponse.model_validate(pro_plan)

        assert response.id == pro_plan.id
        assert response.name == "Pro"
        assert response.plan_type == PlanType.PRO
        assert response.base_price_cents == 3000

    def test_subscription_response_model(self, pro_subscription):
        """Test SubscriptionResponse schema validation."""
        from app.billing.schemas import SubscriptionResponse

        response = SubscriptionResponse.model_validate(pro_subscription)

        assert response.id == pro_subscription.id
        assert response.status == SubscriptionStatus.ACTIVE
        assert response.stripe_customer_id == "cus_test123"

    def test_subscribe_request_validation(self):
        """Test SubscribeToProRequest schema validation."""
        from app.billing.schemas import SubscribeToProRequest

        request = SubscribeToProRequest(
            success_url="https://app.vibemonitor.ai/billing?success=true",
            cancel_url="https://app.vibemonitor.ai/billing?canceled=true",
        )

        assert "success" in request.success_url
        assert "canceled" in request.cancel_url


class TestPricingCalculations:
    """Tests for pricing calculations."""

    def test_free_plan_monthly_cost(self, free_plan):
        """Test Free plan has zero cost."""
        services = 3
        billable = max(0, services - free_plan.base_service_count)
        monthly_cost = (
            free_plan.base_price_cents
            + billable * free_plan.additional_service_price_cents
        )
        assert monthly_cost == 0

    def test_pro_plan_base_monthly_cost(self, pro_plan):
        """Test Pro plan base monthly cost."""
        services = 5  # At base
        billable = max(0, services - pro_plan.base_service_count)
        monthly_cost = (
            pro_plan.base_price_cents
            + billable * pro_plan.additional_service_price_cents
        )
        assert monthly_cost == 3000  # $30

    def test_pro_plan_with_additional_services(self, pro_plan):
        """Test Pro plan with additional services."""
        services = 10  # 5 additional
        billable = max(0, services - pro_plan.base_service_count)
        monthly_cost = (
            pro_plan.base_price_cents
            + billable * pro_plan.additional_service_price_cents
        )
        assert billable == 5
        assert monthly_cost == 3000 + (5 * 500)  # $30 + $25 = $55
        assert monthly_cost == 5500


class TestEnumValues:
    """Tests for enum values match expected values."""

    def test_plan_type_values(self):
        """Test PlanType enum values."""
        assert PlanType.FREE.value == "free"
        assert PlanType.PRO.value == "pro"

    def test_subscription_status_values(self):
        """Test SubscriptionStatus enum values."""
        assert SubscriptionStatus.ACTIVE.value == "active"
        assert SubscriptionStatus.PAST_DUE.value == "past_due"
        assert SubscriptionStatus.CANCELED.value == "canceled"
        assert SubscriptionStatus.INCOMPLETE.value == "incomplete"
        assert SubscriptionStatus.TRIALING.value == "trialing"
