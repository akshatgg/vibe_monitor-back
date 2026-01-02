"""
Unit tests for billing subscription_service.py.
Tests billable count calculation, timestamp handling, and status transitions.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


from app.billing.services.subscription_service import SubscriptionService
from app.models import Plan, PlanType, Subscription, SubscriptionStatus


class TestBillableServiceCountCalculation:
    """Tests for billable service count calculation logic."""

    @pytest.fixture
    def subscription_service(self):
        """Create a SubscriptionService instance."""
        return SubscriptionService()

    @pytest.fixture
    def mock_plan(self):
        """Create a mock Plan with base_service_count=10."""
        plan = MagicMock(spec=Plan)
        plan.base_service_count = 10
        return plan

    @pytest.fixture
    def mock_subscription(self):
        """Create a mock Subscription."""
        subscription = MagicMock(spec=Subscription)
        subscription.stripe_subscription_id = None  # No Stripe subscription
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.plan_id = "plan-123"
        subscription.billable_service_count = 0
        return subscription

    def test_billable_count_zero_when_under_base(self):
        """Billable count should be 0 when services <= base count."""
        base_count = 10
        # Formula: max(0, new_service_count - plan.base_service_count)
        assert max(0, 5 - base_count) == 0
        assert max(0, 10 - base_count) == 0

    def test_billable_count_positive_when_over_base(self):
        """Billable count should be positive when services > base count."""
        base_count = 10
        assert max(0, 15 - base_count) == 5
        assert max(0, 20 - base_count) == 10

    def test_billable_count_never_negative(self):
        """Billable count should never be negative."""
        base_count = 10
        assert max(0, 0 - base_count) == 0
        assert max(0, -5 - base_count) == 0

    @pytest.mark.asyncio
    async def test_update_service_count_calculates_billable_correctly(
        self, subscription_service, mock_db, mock_plan, mock_subscription
    ):
        """update_service_count should calculate billable count correctly."""
        mock_plan.base_service_count = 10

        subscription_service.get_workspace_subscription = AsyncMock(
            return_value=mock_subscription
        )
        subscription_service.get_plan_by_id = AsyncMock(return_value=mock_plan)

        # Update to 15 services (5 billable)
        await subscription_service.update_service_count(mock_db, "ws-123", 15)

        # billable_service_count = max(0, 15 - 10) = 5
        assert mock_subscription.billable_service_count == 5

    @pytest.mark.asyncio
    async def test_update_service_count_under_base_zero_billable(
        self, subscription_service, mock_db, mock_plan, mock_subscription
    ):
        """update_service_count under base should have 0 billable."""
        mock_plan.base_service_count = 10

        subscription_service.get_workspace_subscription = AsyncMock(
            return_value=mock_subscription
        )
        subscription_service.get_plan_by_id = AsyncMock(return_value=mock_plan)

        # Update to 7 services (0 billable)
        await subscription_service.update_service_count(mock_db, "ws-123", 7)

        assert mock_subscription.billable_service_count == 0


class TestWebhookTimestampConversion:
    """Tests for timestamp conversion in webhook handlers."""

    def test_unix_timestamp_to_datetime(self):
        """Unix timestamps should convert to timezone-aware datetimes."""
        # Example: 1704067200 = 2024-01-01 00:00:00 UTC
        unix_ts = 1704067200
        expected = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        assert result == expected

    def test_conversion_preserves_timezone(self):
        """Converted datetimes should be in UTC timezone."""
        unix_ts = 1704067200
        result = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        assert result.tzinfo == timezone.utc


class TestSubscriptionStatusMapping:
    """Tests for subscription status mapping from Stripe."""

    def test_active_status_mapping(self):
        """Stripe 'active' should map to SubscriptionStatus.ACTIVE."""
        status = SubscriptionStatus("active")
        assert status == SubscriptionStatus.ACTIVE

    def test_past_due_status_mapping(self):
        """Stripe 'past_due' should map to SubscriptionStatus.PAST_DUE."""
        status = SubscriptionStatus("past_due")
        assert status == SubscriptionStatus.PAST_DUE

    def test_canceled_status_mapping(self):
        """Stripe 'canceled' should map to SubscriptionStatus.CANCELED."""
        status = SubscriptionStatus("canceled")
        assert status == SubscriptionStatus.CANCELED

    def test_incomplete_status_mapping(self):
        """Stripe 'incomplete' should map to SubscriptionStatus.INCOMPLETE."""
        status = SubscriptionStatus("incomplete")
        assert status == SubscriptionStatus.INCOMPLETE

    def test_trialing_status_mapping(self):
        """Stripe 'trialing' should map to SubscriptionStatus.TRIALING."""
        status = SubscriptionStatus("trialing")
        assert status == SubscriptionStatus.TRIALING


class TestHandleSubscriptionCreated:
    """Tests for handle_subscription_created webhook handler."""

    @pytest.fixture
    def subscription_service(self):
        return SubscriptionService()

    @pytest.fixture
    def mock_stripe_subscription(self):
        """Create a mock Stripe subscription object."""
        sub = MagicMock()
        sub.id = "sub_stripe_123"
        sub.status = "active"
        sub.current_period_start = 1704067200  # 2024-01-01 00:00:00 UTC
        sub.current_period_end = 1706745600  # 2024-02-01 00:00:00 UTC
        sub.metadata = {"workspace_id": "ws-123", "plan_id": "plan-456"}
        return sub

    @pytest.mark.asyncio
    async def test_updates_subscription_with_stripe_details(
        self, subscription_service, mock_db, mock_stripe_subscription
    ):
        """Handler should update local subscription with Stripe details."""
        mock_local_sub = MagicMock(spec=Subscription)
        subscription_service.get_workspace_subscription = AsyncMock(
            return_value=mock_local_sub
        )

        await subscription_service.handle_subscription_created(
            mock_db, mock_stripe_subscription
        )

        assert mock_local_sub.stripe_subscription_id == "sub_stripe_123"
        assert mock_local_sub.status == SubscriptionStatus.ACTIVE
        assert mock_local_sub.plan_id == "plan-456"

    @pytest.mark.asyncio
    async def test_converts_timestamps_correctly(
        self, subscription_service, mock_db, mock_stripe_subscription
    ):
        """Handler should convert Unix timestamps to datetimes."""
        mock_local_sub = MagicMock(spec=Subscription)
        subscription_service.get_workspace_subscription = AsyncMock(
            return_value=mock_local_sub
        )

        await subscription_service.handle_subscription_created(
            mock_db, mock_stripe_subscription
        )

        expected_start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        expected_end = datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert mock_local_sub.current_period_start == expected_start
        assert mock_local_sub.current_period_end == expected_end

    @pytest.mark.asyncio
    async def test_skips_if_no_workspace_id(
        self, subscription_service, mock_db, mock_stripe_subscription
    ):
        """Handler should skip if workspace_id not in metadata."""
        mock_stripe_subscription.metadata = {}

        # Should not raise, just log warning
        await subscription_service.handle_subscription_created(
            mock_db, mock_stripe_subscription
        )

    @pytest.mark.asyncio
    async def test_skips_if_local_subscription_not_found(
        self, subscription_service, mock_db, mock_stripe_subscription
    ):
        """Handler should skip if local subscription not found."""
        subscription_service.get_workspace_subscription = AsyncMock(return_value=None)

        # Should not raise, just log warning
        await subscription_service.handle_subscription_created(
            mock_db, mock_stripe_subscription
        )


class TestHandleSubscriptionDeleted:
    """Tests for handle_subscription_deleted webhook handler."""

    @pytest.fixture
    def subscription_service(self):
        return SubscriptionService()

    @pytest.fixture
    def mock_free_plan(self):
        plan = MagicMock(spec=Plan)
        plan.id = "plan-free"
        plan.plan_type = PlanType.FREE
        return plan

    @pytest.mark.asyncio
    async def test_downgrades_to_free_plan(
        self, subscription_service, mock_db, mock_free_plan
    ):
        """Handler should downgrade subscription to Free plan."""
        mock_result = MagicMock()
        mock_local_sub = MagicMock(spec=Subscription)
        mock_result.scalar_one_or_none.return_value = mock_local_sub
        mock_db.execute.return_value = mock_result

        subscription_service.get_plan_by_type = AsyncMock(return_value=mock_free_plan)

        await subscription_service.handle_subscription_deleted(
            mock_db, "sub_stripe_123"
        )

        assert mock_local_sub.plan_id == "plan-free"
        assert mock_local_sub.status == SubscriptionStatus.ACTIVE
        assert mock_local_sub.stripe_subscription_id is None
        assert mock_local_sub.billable_service_count == 0
        assert mock_local_sub.current_period_start is None
        assert mock_local_sub.current_period_end is None


class TestHandlePaymentSucceeded:
    """Tests for handle_payment_succeeded webhook handler."""

    @pytest.fixture
    def subscription_service(self):
        return SubscriptionService()

    @pytest.mark.asyncio
    async def test_reactivates_past_due_subscription(
        self, subscription_service, mock_db
    ):
        """Handler should reactivate past_due subscription on payment success."""
        mock_invoice = MagicMock()
        mock_invoice.subscription = "sub_123"

        mock_result = MagicMock()
        mock_local_sub = MagicMock(spec=Subscription)
        mock_local_sub.status = SubscriptionStatus.PAST_DUE
        mock_result.scalar_one_or_none.return_value = mock_local_sub
        mock_db.execute.return_value = mock_result

        await subscription_service.handle_payment_succeeded(mock_db, mock_invoice)

        assert mock_local_sub.status == SubscriptionStatus.ACTIVE
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_non_subscription_invoices(self, subscription_service, mock_db):
        """Handler should skip invoices not tied to subscriptions."""
        mock_invoice = MagicMock()
        mock_invoice.subscription = None

        await subscription_service.handle_payment_succeeded(mock_db, mock_invoice)

        mock_db.execute.assert_not_called()


class TestHandlePaymentFailed:
    """Tests for handle_payment_failed webhook handler."""

    @pytest.fixture
    def subscription_service(self):
        return SubscriptionService()

    @pytest.mark.asyncio
    async def test_marks_subscription_past_due(self, subscription_service, mock_db):
        """Handler should mark subscription as past_due on payment failure."""
        mock_invoice = MagicMock()
        mock_invoice.subscription = "sub_123"

        mock_result = MagicMock()
        mock_local_sub = MagicMock(spec=Subscription)
        mock_local_sub.status = SubscriptionStatus.ACTIVE
        mock_local_sub.id = "sub-local-123"
        mock_local_sub.workspace_id = "ws-123"
        mock_result.scalar_one_or_none.return_value = mock_local_sub
        mock_db.execute.return_value = mock_result

        await subscription_service.handle_payment_failed(mock_db, mock_invoice)

        assert mock_local_sub.status == SubscriptionStatus.PAST_DUE
        mock_db.commit.assert_called_once()


class TestCancelSubscription:
    """Tests for cancel_subscription method."""

    @pytest.fixture
    def subscription_service(self):
        return SubscriptionService()

    @pytest.fixture
    def mock_subscription(self):
        sub = MagicMock(spec=Subscription)
        sub.stripe_subscription_id = "sub_stripe_123"
        sub.status = SubscriptionStatus.ACTIVE
        return sub

    @pytest.fixture
    def mock_free_plan(self):
        plan = MagicMock(spec=Plan)
        plan.id = "plan-free"
        plan.plan_type = PlanType.FREE
        return plan

    @pytest.mark.asyncio
    async def test_immediate_cancel_downgrades_to_free(
        self, subscription_service, mock_db, mock_subscription, mock_free_plan
    ):
        """Immediate cancellation should downgrade to Free plan."""
        subscription_service.get_workspace_subscription = AsyncMock(
            return_value=mock_subscription
        )
        subscription_service.get_plan_by_type = AsyncMock(return_value=mock_free_plan)

        with patch(
            "app.billing.services.subscription_service.stripe_service"
        ) as mock_stripe:
            mock_stripe.cancel_subscription = AsyncMock()

            await subscription_service.cancel_subscription(
                mock_db, "ws-123", immediate=True
            )

        assert mock_subscription.plan_id == "plan-free"
        assert mock_subscription.status == SubscriptionStatus.ACTIVE
        assert mock_subscription.stripe_subscription_id is None

    @pytest.mark.asyncio
    async def test_non_immediate_cancel_keeps_subscription(
        self, subscription_service, mock_db, mock_subscription
    ):
        """Non-immediate cancellation should not change plan immediately."""
        subscription_service.get_workspace_subscription = AsyncMock(
            return_value=mock_subscription
        )

        with patch(
            "app.billing.services.subscription_service.stripe_service"
        ) as mock_stripe:
            mock_stripe.cancel_subscription = AsyncMock()

            await subscription_service.cancel_subscription(
                mock_db, "ws-123", immediate=False
            )

        # Status should not be CANCELED immediately
        assert mock_subscription.status == SubscriptionStatus.ACTIVE
        # stripe_subscription_id should still be set
        assert mock_subscription.stripe_subscription_id == "sub_stripe_123"


class TestSubscribeToProValidation:
    """Tests for subscribe_to_pro validation logic."""

    @pytest.fixture
    def subscription_service(self):
        return SubscriptionService()

    @pytest.mark.asyncio
    async def test_raises_if_no_subscription_exists(
        self, subscription_service, mock_db
    ):
        """Should raise ValueError if workspace has no subscription."""
        subscription_service.get_workspace_subscription = AsyncMock(return_value=None)

        with pytest.raises(ValueError) as exc_info:
            await subscription_service.subscribe_to_pro(
                mock_db,
                "ws-123",
                "test@example.com",
                "Test User",
                "https://success.url",
                "https://cancel.url",
            )

        assert "No subscription found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_if_pro_plan_not_found(self, subscription_service, mock_db):
        """Should raise ValueError if Pro plan doesn't exist."""
        mock_sub = MagicMock(spec=Subscription)
        subscription_service.get_workspace_subscription = AsyncMock(
            return_value=mock_sub
        )
        subscription_service.get_plan_by_type = AsyncMock(return_value=None)

        with pytest.raises(ValueError) as exc_info:
            await subscription_service.subscribe_to_pro(
                mock_db,
                "ws-123",
                "test@example.com",
                "Test User",
                "https://success.url",
                "https://cancel.url",
            )

        assert "Pro plan not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_if_stripe_price_id_not_configured(
        self, subscription_service, mock_db
    ):
        """Should raise ValueError if STRIPE_PRO_PLAN_PRICE_ID not configured."""
        mock_sub = MagicMock(spec=Subscription)
        mock_pro_plan = MagicMock(spec=Plan)

        subscription_service.get_workspace_subscription = AsyncMock(
            return_value=mock_sub
        )
        subscription_service.get_plan_by_type = AsyncMock(return_value=mock_pro_plan)

        with patch(
            "app.billing.services.subscription_service.settings"
        ) as mock_settings:
            mock_settings.STRIPE_PRO_PLAN_PRICE_ID = None

            with pytest.raises(ValueError) as exc_info:
                await subscription_service.subscribe_to_pro(
                    mock_db,
                    "ws-123",
                    "test@example.com",
                    "Test User",
                    "https://success.url",
                    "https://cancel.url",
                )

            assert "STRIPE_PRO_PLAN_PRICE_ID not configured" in str(exc_info.value)
