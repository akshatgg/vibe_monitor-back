"""
Comprehensive tests for service downgrade functionality using Stripe Subscription Schedules.

Tests cover:
- Downgrade scheduling
- Cancel pending downgrades
- Get pending changes
- Stripe schedule creation/update/cancel
- Webhook handling for schedule execution
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, Mock, patch
import stripe

from app.billing.services.service_downgrade import (
    downgrade_services,
    cancel_pending_downgrade,
    get_pending_changes,
)
from app.billing.services.subscription_service import subscription_service
from app.billing.services.stripe_service import stripe_service
from app.models import Subscription, SubscriptionStatus, Plan, PlanType


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def mock_pro_plan():
    """Mock Pro plan with pricing information."""
    return Plan(
        id="pro-plan-id",
        name="Pro",
        plan_type=PlanType.PRO,
        base_service_count=5,
        base_price_cents=3000,  # $30.00
        additional_service_price_cents=500,  # $5.00
        is_active=True,
    )


@pytest.fixture
def base_subscription():
    """Create a base subscription for testing."""
    now = datetime.now(timezone.utc)
    period_end = now + timedelta(days=27)  # 27 days remaining in billing period

    subscription = Subscription(
        id="sub-123",
        workspace_id="workspace-456",
        stripe_subscription_id="sub_stripe123",
        stripe_customer_id="cus_stripe456",
        status=SubscriptionStatus.ACTIVE,
        plan_id="pro",
        billable_service_count=40,  # 40 additional services (45 total with base 5)
        current_period_start=now,
        current_period_end=period_end,
        subscription_schedule_id=None,
        pending_billable_service_count=None,
        pending_change_date=None,
    )
    return subscription


@pytest.fixture
def subscription_with_pending_downgrade(base_subscription): 
    """Subscription with a pending downgrade."""
    base_subscription.subscription_schedule_id = "sub_sched_abc123"
    base_subscription.pending_billable_service_count = 10  # Will have 15 total (10 + 5 base)
    base_subscription.pending_change_date = base_subscription.current_period_end
    return base_subscription


@pytest.fixture
def mock_stripe_subscription():
    """Mock Stripe subscription object."""
    return {
        "id": "sub_stripe123",
        "customer": "cus_stripe456",
        "status": "active",
        "current_period_start": int(datetime.now(timezone.utc).timestamp()),
        "current_period_end": int((datetime.now(timezone.utc) + timedelta(days=27)).timestamp()),
        "schedule": None,  # No schedule attached
        "items": {
            "data": [
                {
                    "id": "si_base",
                    "price": {"id": "price_pro_plan"},
                    "quantity": 1,
                },
                {
                    "id": "si_additional",
                    "price": {"id": "price_additional_services"},
                    "quantity": 40,
                },
            ]
        },
    }


@pytest.fixture
def mock_stripe_schedule():
    """Mock Stripe subscription schedule object."""
    now = datetime.now(timezone.utc)
    period_end = now + timedelta(days=27)

    return Mock(
        id="sub_sched_new123",
        status="active",
        subscription="sub_stripe123",
        phases=[
            Mock(
                start_date=int(now.timestamp()),
                end_date=int(period_end.timestamp()),
                items=[
                    {"price": "price_pro_plan", "quantity": 1},
                    {"price": "price_additional_services", "quantity": 40},
                ],
            ),
            Mock(
                start_date=int(period_end.timestamp()),
                end_date=None,
                items=[
                    {"price": "price_pro_plan", "quantity": 1},
                    {"price": "price_additional_services", "quantity": 10},
                ],
            ),
        ],
    )


@pytest.fixture
def mock_stripe_settings():
    """Mock Stripe settings with test price IDs."""
    with patch("app.billing.services.service_downgrade.settings") as mock_settings:
        mock_settings.STRIPE_PRO_PLAN_PRICE_ID = "price_pro_plan"
        mock_settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID = "price_additional_services"
        yield mock_settings


# ============================================================================
# TEST DOWNGRADE_SERVICES
# ============================================================================

@pytest.mark.asyncio
class TestDowngradeServices:
    """Test suite for downgrade_services function."""

    async def test_downgrade_success_no_existing_schedule(
        self, mock_db_session, base_subscription, mock_pro_plan, mock_stripe_subscription, mock_stripe_schedule,
        mock_stripe_settings
    ):
        """Test successful downgrade when no schedule exists."""
        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            # Setup mocks
            mock_stripe.get_subscription = AsyncMock(return_value=mock_stripe_subscription)
            mock_stripe.get_subscription_schedule_for_subscription = AsyncMock(return_value=None)
            mock_stripe.create_subscription_schedule = AsyncMock(return_value=mock_stripe_schedule)

            # Execute downgrade from 45 to 15 services
            result = await downgrade_services(
                db=mock_db_session,
                workspace_id="workspace-456",
                new_service_count=15,  # 10 billable + 5 base
                subscription=base_subscription,
                plan=mock_pro_plan,
            )

            # Assertions
            assert result["success"] is True
            assert result["type"] == "downgrade"
            assert result["current_service_count"] == 45
            assert result["new_service_count"] == 15
            assert result["next_billing_amount"] == 80  # $30 + (10 * $5)

            # Verify schedule was created with correct phases
            mock_stripe.create_subscription_schedule.assert_called_once()
            call_args = mock_stripe.create_subscription_schedule.call_args
            phases = call_args[1]["phases"]

            # Phase 1: Current services until period end
            assert phases[0]["items"][0]["price"] == "price_pro_plan"
            assert phases[0]["items"][1]["quantity"] == 40  # Current billable count

            # Phase 2: New services starting next period
            assert phases[1]["items"][1]["quantity"] == 10  # New billable count

            # Verify database was updated
            assert base_subscription.subscription_schedule_id == "sub_sched_new123"
            assert base_subscription.pending_billable_service_count == 10
            assert base_subscription.pending_change_date == base_subscription.current_period_end
            mock_db_session.commit.assert_called()

    async def test_downgrade_success_with_existing_schedule(
        self, mock_db_session, subscription_with_pending_downgrade, mock_pro_plan,
        mock_stripe_subscription, mock_stripe_schedule, mock_stripe_settings
    ):
        """Test downgrade when a schedule already exists (updates it)."""
        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            # Setup mocks
            mock_stripe.get_subscription = AsyncMock(return_value=mock_stripe_subscription)
            mock_stripe.get_subscription_schedule_for_subscription = AsyncMock(
                return_value="sub_sched_abc123"
            )
            mock_stripe.update_subscription_schedule = AsyncMock(return_value=mock_stripe_schedule)

            # Execute downgrade (changing mind from 15 to 20 services)
            result = await downgrade_services(
                db=mock_db_session,
                workspace_id="workspace-456",
                new_service_count=20,  # 15 billable + 5 base
                subscription=subscription_with_pending_downgrade,
                plan=mock_pro_plan,
            )

            # Assertions
            assert result["success"] is True
            assert result["new_service_count"] == 20
            assert result["next_billing_amount"] == 105  # $30 + (15 * $5)

            # Verify existing schedule was updated
            mock_stripe.update_subscription_schedule.assert_called_once()
            mock_stripe.create_subscription_schedule.assert_not_called()

    async def test_downgrade_to_base_plan(
        self, mock_db_session, base_subscription, mock_pro_plan, mock_stripe_subscription, mock_stripe_schedule,
        mock_stripe_settings
    ):
        """Test downgrade to base plan (5 services only, 0 billable)."""
        mock_stripe_schedule.phases[1].items = [
            {"price": "price_pro_plan", "quantity": 1},
            # No additional services
        ]

        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            mock_stripe.get_subscription = AsyncMock(return_value=mock_stripe_subscription)
            mock_stripe.get_subscription_schedule_for_subscription = AsyncMock(return_value=None)
            mock_stripe.create_subscription_schedule = AsyncMock(return_value=mock_stripe_schedule)

            result = await downgrade_services(
                db=mock_db_session,
                workspace_id="workspace-456",
                new_service_count=5,  # Base plan only
                subscription=base_subscription,
                plan=mock_pro_plan,
            )

            assert result["success"] is True
            assert result["new_service_count"] == 5
            assert result["next_billing_amount"] == 30  # Base plan only

            # Verify Phase 2 has only base plan
            call_args = mock_stripe.create_subscription_schedule.call_args
            phase2_items = call_args[1]["phases"][1]["items"]
            assert len(phase2_items) == 1  # Only base plan item
            assert phase2_items[0]["price"] == "price_pro_plan"

    async def test_downgrade_no_stripe_subscription(self, mock_db_session, base_subscription, mock_pro_plan):
        """Test downgrade fails when no Stripe subscription exists."""
        base_subscription.stripe_subscription_id = None

        result = await downgrade_services(
            db=mock_db_session,
            workspace_id="workspace-456",
            new_service_count=15,
            subscription=base_subscription,
            plan=mock_pro_plan,
        )

        assert result["success"] is False
        assert "No active Stripe subscription" in result["message"]

    async def test_downgrade_stripe_subscription_not_found(
        self, mock_db_session, base_subscription, mock_pro_plan
    ):
        """Test downgrade fails when Stripe subscription doesn't exist in Stripe."""
        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            mock_stripe.get_subscription = AsyncMock(return_value=None)

            result = await downgrade_services(
                db=mock_db_session,
                workspace_id="workspace-456",
                new_service_count=15,
                subscription=base_subscription,
                plan=mock_pro_plan,
            )

            assert result["success"] is False
            assert "error" in result

    async def test_downgrade_stripe_error(
        self, mock_db_session, base_subscription, mock_pro_plan, mock_stripe_subscription,
        mock_stripe_settings
    ):
        """Test downgrade handles Stripe API errors gracefully."""
        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            mock_stripe.get_subscription = AsyncMock(return_value=mock_stripe_subscription)
            mock_stripe.get_subscription_schedule_for_subscription = AsyncMock(return_value=None)
            mock_stripe.create_subscription_schedule = AsyncMock(
                side_effect=stripe.error.StripeError("API Error")
            )

            result = await downgrade_services(
                db=mock_db_session,
                workspace_id="workspace-456",
                new_service_count=15,
                subscription=base_subscription,
                plan=mock_pro_plan,
            )

            assert result["success"] is False
            assert "Failed to schedule downgrade" in result["message"]

    async def test_downgrade_update_fails_fallback_to_create(
        self, mock_db_session, subscription_with_pending_downgrade, mock_pro_plan,
        mock_stripe_subscription, mock_stripe_schedule, mock_stripe_settings
    ):
        """Test that if updating existing schedule fails, it cancels and creates new one."""
        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            mock_stripe.get_subscription = AsyncMock(return_value=mock_stripe_subscription)
            mock_stripe.get_subscription_schedule_for_subscription = AsyncMock(
                return_value="sub_sched_abc123"
            )
            # Update fails
            mock_stripe.update_subscription_schedule = AsyncMock(
                side_effect=stripe.error.StripeError("Cannot update")
            )
            # Cancel succeeds
            mock_stripe.cancel_subscription_schedule = AsyncMock(return_value=Mock())
            # Create succeeds
            mock_stripe.create_subscription_schedule = AsyncMock(return_value=mock_stripe_schedule)

            result = await downgrade_services(
                db=mock_db_session,
                workspace_id="workspace-456",
                new_service_count=20,
                subscription=subscription_with_pending_downgrade,
                plan=mock_pro_plan,
            )

            assert result["success"] is True
            mock_stripe.cancel_subscription_schedule.assert_called_once()
            mock_stripe.create_subscription_schedule.assert_called_once()

    async def test_downgrade_stale_schedule_id_in_db(
        self, mock_db_session, subscription_with_pending_downgrade, mock_pro_plan,
        mock_stripe_subscription, mock_stripe_schedule, mock_stripe_settings
    ):
        """Test that if DB has stale schedule ID, it gets updated from Stripe."""
        subscription_with_pending_downgrade.subscription_schedule_id = "sub_sched_old999"

        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            mock_stripe.get_subscription = AsyncMock(return_value=mock_stripe_subscription)
            # Stripe says the actual schedule is different
            mock_stripe.get_subscription_schedule_for_subscription = AsyncMock(
                return_value="sub_sched_actual_from_stripe"
            )
            mock_stripe.update_subscription_schedule = AsyncMock(return_value=mock_stripe_schedule)

            await downgrade_services(
                db=mock_db_session,
                workspace_id="workspace-456",
                new_service_count=20,
                subscription=subscription_with_pending_downgrade,
                plan=mock_pro_plan,
            )

            # Verify DB was updated with correct schedule ID
            assert subscription_with_pending_downgrade.subscription_schedule_id == "sub_sched_new123"
            mock_db_session.commit.assert_called()

    async def test_downgrade_multiple_changes_same_period(
        self, mock_db_session, subscription_with_pending_downgrade, mock_pro_plan,
        mock_stripe_subscription, mock_stripe_schedule, mock_stripe_settings
    ):
        """Test multiple downgrades in same billing period - last one wins."""
        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            mock_stripe.get_subscription = AsyncMock(return_value=mock_stripe_subscription)
            mock_stripe.get_subscription_schedule_for_subscription = AsyncMock(
                return_value="sub_sched_abc123"
            )
            mock_stripe.update_subscription_schedule = AsyncMock(return_value=mock_stripe_schedule)

            # First downgrade to 20
            result1 = await downgrade_services(
                db=mock_db_session,
                workspace_id="workspace-456",
                new_service_count=20,
                subscription=subscription_with_pending_downgrade,
                plan=mock_pro_plan,
            )
            assert result1["success"] is True
            assert result1["new_service_count"] == 20

            # Change mind, downgrade to 10 instead
            result2 = await downgrade_services(
                db=mock_db_session,
                workspace_id="workspace-456",
                new_service_count=10,
                subscription=subscription_with_pending_downgrade,
                plan=mock_pro_plan,
            )
            assert result2["success"] is True
            assert result2["new_service_count"] == 10

            # Schedule was updated, not created again
            assert mock_stripe.update_subscription_schedule.call_count == 2


# ============================================================================
# TEST CANCEL_PENDING_DOWNGRADE
# ============================================================================

@pytest.mark.asyncio
class TestCancelPendingDowngrade:
    """Test suite for cancel_pending_downgrade function."""

    async def test_cancel_success(
        self, mock_db_session, subscription_with_pending_downgrade, mock_pro_plan
    ):
        """Test successfully canceling a pending downgrade."""
        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            mock_stripe.cancel_subscription_schedule = AsyncMock(return_value=Mock())

            result = await cancel_pending_downgrade(
                db=mock_db_session,
                subscription=subscription_with_pending_downgrade,
                plan=mock_pro_plan,
            )

            assert result["success"] is True
            assert result["service_count"] == 45
            assert "canceled" in result["message"].lower()

            # Verify schedule was canceled in Stripe
            mock_stripe.cancel_subscription_schedule.assert_called_once_with("sub_sched_abc123")

            # Verify database was cleared
            assert subscription_with_pending_downgrade.subscription_schedule_id is None
            assert subscription_with_pending_downgrade.pending_billable_service_count is None
            assert subscription_with_pending_downgrade.pending_change_date is None
            mock_db_session.commit.assert_called()

    async def test_cancel_no_pending_downgrade(self, mock_db_session, base_subscription, mock_pro_plan):
        """Test cancel when there's no pending downgrade."""
        result = await cancel_pending_downgrade(
            db=mock_db_session,
            subscription=base_subscription,
            plan=mock_pro_plan,
        )

        assert result["success"] is False
        assert "No pending downgrade" in result["message"]

    async def test_cancel_no_schedule_id(
        self, mock_db_session, subscription_with_pending_downgrade, mock_pro_plan
    ):
        """Test cancel when pending count exists but no schedule ID."""
        subscription_with_pending_downgrade.subscription_schedule_id = None

        result = await cancel_pending_downgrade(
            db=mock_db_session,
            subscription=subscription_with_pending_downgrade,
            plan=mock_pro_plan,
        )

        assert result["success"] is False
        assert "No subscription schedule found" in result["message"]

    async def test_cancel_stripe_error(
        self, mock_db_session, subscription_with_pending_downgrade, mock_pro_plan
    ):
        """Test cancel handles Stripe API errors gracefully."""
        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            mock_stripe.cancel_subscription_schedule = AsyncMock(
                side_effect=stripe.error.StripeError("API Error")
            )

            result = await cancel_pending_downgrade(
                db=mock_db_session,
                subscription=subscription_with_pending_downgrade,
                plan=mock_pro_plan,
            )

            assert result["success"] is False
            assert "Failed to cancel downgrade" in result["message"]


# ============================================================================
# TEST GET_PENDING_CHANGES
# ============================================================================

@pytest.mark.asyncio
class TestGetPendingChanges:
    """Test suite for get_pending_changes function."""

    async def test_get_pending_changes_exists(self, subscription_with_pending_downgrade, mock_pro_plan):
        """Test getting pending changes when they exist."""
        result = await get_pending_changes(subscription_with_pending_downgrade, mock_pro_plan)

        assert result is not None
        assert result["type"] == "downgrade"
        assert result["current_service_count"] == 45
        assert result["new_service_count"] == 15  # 10 billable + 5 base
        assert result["takes_effect"] == subscription_with_pending_downgrade.current_period_end

    async def test_get_pending_changes_none(self, base_subscription, mock_pro_plan):
        """Test getting pending changes when none exist."""
        result = await get_pending_changes(base_subscription, mock_pro_plan)

        assert result is None

    async def test_get_pending_changes_error_handling(self, mock_pro_plan):
        """Test error handling in get_pending_changes."""
        # Create a subscription mock that raises an error
        bad_subscription = Mock()
        bad_subscription.pending_billable_service_count = None
        bad_subscription.billable_service_count = Mock(side_effect=Exception("DB Error"))

        result = await get_pending_changes(bad_subscription, mock_pro_plan)

        # Should handle error gracefully
        assert result is None


# ============================================================================
# TEST STRIPE SERVICE METHODS
# ============================================================================

@pytest.mark.asyncio
class TestStripeServiceScheduleMethods:
    """Test Stripe service schedule management methods."""

    async def test_create_subscription_schedule_success(self, mock_stripe_schedule):
        """Test creating a subscription schedule."""
        with patch("stripe.SubscriptionSchedule.create") as mock_create, \
             patch("stripe.SubscriptionSchedule.modify") as mock_modify:

            # Setup mocks
            mock_create.return_value = mock_stripe_schedule
            mock_modify.return_value = mock_stripe_schedule

            phases = [
                {
                    "items": [{"price": "price_pro_plan", "quantity": 1}],
                    "start_date": "now",
                    "end_date": 123456789,
                },
                {
                    "items": [{"price": "price_pro_plan", "quantity": 1}],
                    "start_date": 123456789,
                },
            ]

            result = await stripe_service.create_subscription_schedule(
                subscription_id="sub_123",
                phases=phases,
            )

            # Verify create was called without phases
            mock_create.assert_called_once_with(from_subscription="sub_123")

            # Verify modify was called with corrected phases
            mock_modify.assert_called_once()
            assert result.id == "sub_sched_new123"

    async def test_update_subscription_schedule_success(self):
        """Test updating a subscription schedule."""
        with patch("stripe.SubscriptionSchedule.modify") as mock_modify:
            mock_schedule = Mock(id="sub_sched_123")
            mock_modify.return_value = mock_schedule

            phases = [
                {"items": [{"price": "price_pro_plan", "quantity": 1}], "end_date": 123456789},
                {"items": [{"price": "price_pro_plan", "quantity": 1}]},
            ]

            result = await stripe_service.update_subscription_schedule(
                schedule_id="sub_sched_123",
                phases=phases,
            )

            mock_modify.assert_called_once_with("sub_sched_123", phases=phases)
            assert result.id == "sub_sched_123"

    async def test_cancel_subscription_schedule_success(self):
        """Test canceling/releasing a subscription schedule."""
        with patch("stripe.SubscriptionSchedule.release") as mock_release:
            mock_schedule = Mock(id="sub_sched_123", status="released")
            mock_release.return_value = mock_schedule

            result = await stripe_service.cancel_subscription_schedule("sub_sched_123")

            mock_release.assert_called_once_with("sub_sched_123")
            assert result.status == "released"

    async def test_get_subscription_schedule_for_subscription(self):
        """Test getting schedule ID for a subscription."""
        with patch("stripe.Subscription.retrieve") as mock_retrieve:
            # Case 1: Subscription has a schedule
            mock_sub = {"id": "sub_123", "schedule": "sub_sched_abc"}
            mock_retrieve.return_value = mock_sub

            result = await stripe_service.get_subscription_schedule_for_subscription("sub_123")
            assert result == "sub_sched_abc"

            # Case 2: Subscription has no schedule
            mock_sub = {"id": "sub_123", "schedule": None}
            mock_retrieve.return_value = mock_sub

            result = await stripe_service.get_subscription_schedule_for_subscription("sub_123")
            assert result is None

            # Case 3: Stripe error
            mock_retrieve.side_effect = stripe.error.StripeError("Not found")
            result = await stripe_service.get_subscription_schedule_for_subscription("sub_123")
            assert result is None


# ============================================================================
# TEST WEBHOOK HANDLING
# ============================================================================

@pytest.mark.asyncio
class TestWebhookHandling:
    """Test webhook handling for scheduled downgrades."""

    async def test_webhook_applies_pending_downgrade(
        self, mock_db_session, subscription_with_pending_downgrade
    ):
        """Test that webhook correctly applies pending downgrade when schedule executes."""
        now = datetime.now(timezone.utc)
        period_end = now + timedelta(days=27)

        # Mock Stripe subscription after schedule applied (new service count)
        items_data = [
            {"price": {"id": "price_pro_plan"}, "quantity": 1},
            {"price": {"id": "price_additional_services"}, "quantity": 10},  # New count!
        ]
        stripe_subscription = Mock(
            id="sub_stripe123",
            status="active",
            current_period_start=int(now.timestamp()),
            current_period_end=int(period_end.timestamp()),
            canceled_at=None,
            items=Mock(data=items_data),
        )
        stripe_subscription.get = Mock(side_effect=lambda key, default=None:
            {'items': {'data': items_data}}.get(key, default)
        )

        with patch("app.billing.services.subscription_service.settings") as mock_settings:
            mock_settings.STRIPE_PRO_PLAN_PRICE_ID = "price_pro_plan"
            mock_settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID = "price_additional_services"

            # Mock database query to return the subscription
            mock_result = Mock()
            mock_result.scalar_one_or_none = Mock(return_value=subscription_with_pending_downgrade)
            mock_db_session.execute = AsyncMock(return_value=mock_result)

            # Execute webhook handler
            await subscription_service.handle_subscription_updated(
                db=mock_db_session,
                stripe_subscription=stripe_subscription,
            )

            # Verify billable count was updated
            assert subscription_with_pending_downgrade.billable_service_count == 10

            # Verify pending fields were cleared
            assert subscription_with_pending_downgrade.pending_billable_service_count is None
            assert subscription_with_pending_downgrade.pending_change_date is None
            assert subscription_with_pending_downgrade.subscription_schedule_id is None

    async def test_webhook_syncs_service_count_from_stripe(
        self, mock_db_session, base_subscription
    ):
        """Test webhook syncs service count from Stripe when it changes."""
        now = datetime.now(timezone.utc)
        period_end = now + timedelta(days=27)

        # Stripe has different count than DB
        items_data = [
            {"price": {"id": "price_pro_plan"}, "quantity": 1},
            {"price": {"id": "price_additional_services"}, "quantity": 25},  # Different!
        ]
        stripe_subscription = Mock(
            id="sub_stripe123",
            status="active",
            current_period_start=int(now.timestamp()),
            current_period_end=int(period_end.timestamp()),
            canceled_at=None,
            items=Mock(data=items_data),
        )
        stripe_subscription.get = Mock(side_effect=lambda key, default=None:
            {'items': {'data': items_data}}.get(key, default)
        )

        # DB has 40, Stripe has 25
        assert base_subscription.billable_service_count == 40

        with patch("app.billing.services.subscription_service.settings") as mock_settings:
            mock_settings.STRIPE_PRO_PLAN_PRICE_ID = "price_pro_plan"
            mock_settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID = "price_additional_services"

            # Mock database query to return the subscription
            mock_result = Mock()
            mock_result.scalar_one_or_none = Mock(return_value=base_subscription)
            mock_db_session.execute = AsyncMock(return_value=mock_result)

            await subscription_service.handle_subscription_updated(
                db=mock_db_session,
                stripe_subscription=stripe_subscription,
            )

            # Verify count was synced from Stripe
            assert base_subscription.billable_service_count == 25


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

@pytest.mark.asyncio
class TestDowngradeIntegration:
    """Integration tests for complete downgrade flow."""

    async def test_complete_downgrade_flow(
        self, mock_db_session, base_subscription, mock_pro_plan,
        mock_stripe_subscription, mock_stripe_schedule, mock_stripe_settings
    ):
        """Test complete flow: schedule downgrade -> verify pending -> cancel -> verify cleared."""
        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            # Setup
            mock_stripe.get_subscription = AsyncMock(return_value=mock_stripe_subscription)
            mock_stripe.get_subscription_schedule_for_subscription = AsyncMock(return_value=None)
            mock_stripe.create_subscription_schedule = AsyncMock(return_value=mock_stripe_schedule)
            mock_stripe.cancel_subscription_schedule = AsyncMock(return_value=Mock())

            # Step 1: Schedule downgrade
            result = await downgrade_services(
                db=mock_db_session,
                workspace_id="workspace-456",
                new_service_count=15,
                subscription=base_subscription,
                plan=mock_pro_plan,
            )
            assert result["success"] is True

            # Step 2: Verify pending changes
            pending = await get_pending_changes(base_subscription, mock_pro_plan)
            assert pending is not None
            assert pending["new_service_count"] == 15

            # Step 3: Cancel the downgrade
            cancel_result = await cancel_pending_downgrade(
                db=mock_db_session,
                subscription=base_subscription,
                plan=mock_pro_plan,
            )
            assert cancel_result["success"] is True

            # Step 4: Verify no pending changes
            pending_after = await get_pending_changes(base_subscription, mock_pro_plan)
            assert pending_after is None

    async def test_multiple_downgrades_then_cancel(
        self, mock_db_session, subscription_with_pending_downgrade, mock_pro_plan,
        mock_stripe_subscription, mock_stripe_schedule, mock_stripe_settings
    ):
        """Test changing mind multiple times, then canceling."""
        with patch("app.billing.services.service_downgrade.stripe_service") as mock_stripe:
            mock_stripe.get_subscription = AsyncMock(return_value=mock_stripe_subscription)
            mock_stripe.get_subscription_schedule_for_subscription = AsyncMock(
                return_value="sub_sched_abc123"
            )
            mock_stripe.update_subscription_schedule = AsyncMock(return_value=mock_stripe_schedule)
            mock_stripe.cancel_subscription_schedule = AsyncMock(return_value=Mock())

            # Downgrade to 20
            await downgrade_services(mock_db_session, "workspace-456", 20, subscription_with_pending_downgrade, mock_pro_plan)

            # Change to 25
            await downgrade_services(mock_db_session, "workspace-456", 25, subscription_with_pending_downgrade, mock_pro_plan)

            # Change to 30
            await downgrade_services(mock_db_session, "workspace-456", 30, subscription_with_pending_downgrade, mock_pro_plan)

            # Cancel
            result = await cancel_pending_downgrade(mock_db_session, subscription_with_pending_downgrade, mock_pro_plan)
            assert result["success"] is True

            # Verify schedule was updated 3 times and canceled once
            assert mock_stripe.update_subscription_schedule.call_count == 3
            mock_stripe.cancel_subscription_schedule.assert_called_once()
