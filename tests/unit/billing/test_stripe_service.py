"""
Unit tests for billing stripe_service.py.
Tests initialization, webhook validation, and error handling.
Note: These tests mock Stripe API calls - they don't hit real Stripe endpoints.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import stripe

from app.billing.services.stripe_service import StripeService


class TestStripeServiceInitialization:
    """Tests for StripeService initialization."""

    def test_init_logs_warning_when_key_not_configured(self):
        """Should log warning when STRIPE_SECRET_KEY is not configured."""
        with patch("app.billing.services.stripe_service.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = None

            with patch("app.billing.services.stripe_service.logger") as mock_logger:
                StripeService()
                mock_logger.warning.assert_called_once()
                assert "not configured" in str(mock_logger.warning.call_args)


class TestConstructWebhookEvent:
    """Tests for StripeService.construct_webhook_event method."""

    @pytest.fixture
    def stripe_service(self):
        """Create a StripeService with mocked settings."""
        with patch("app.billing.services.stripe_service.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = "sk_test_123"
            mock_settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
            return StripeService()

    def test_raises_error_when_webhook_secret_not_configured(self):
        """Should raise ValueError when STRIPE_WEBHOOK_SECRET is not configured."""
        with patch("app.billing.services.stripe_service.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = "sk_test_123"
            mock_settings.STRIPE_WEBHOOK_SECRET = None
            service = StripeService()

            with pytest.raises(ValueError) as exc_info:
                service.construct_webhook_event(b"payload", "sig_123")

            assert "STRIPE_WEBHOOK_SECRET not configured" in str(exc_info.value)

    def test_calls_stripe_webhook_construct_event(self, stripe_service):
        """Should call stripe.Webhook.construct_event with correct parameters."""
        with patch("app.billing.services.stripe_service.stripe") as mock_stripe:
            with patch("app.billing.services.stripe_service.settings") as mock_settings:
                mock_settings.STRIPE_WEBHOOK_SECRET = "whsec_test_secret"
                mock_event = MagicMock(spec=stripe.Event)
                mock_stripe.Webhook.construct_event.return_value = mock_event

                payload = b'{"type": "customer.subscription.created"}'
                signature = "t=123,v1=abc"

                result = stripe_service.construct_webhook_event(payload, signature)

                mock_stripe.Webhook.construct_event.assert_called_once_with(
                    payload, signature, "whsec_test_secret"
                )
                assert result == mock_event


class TestCreateCustomerMetadata:
    """Tests for customer metadata building logic."""

    @pytest.fixture
    def stripe_service(self):
        """Create a StripeService with mocked settings."""
        with patch("app.billing.services.stripe_service.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = "sk_test_123"
            return StripeService()

    @pytest.mark.asyncio
    async def test_customer_metadata_includes_workspace_id(self, stripe_service):
        """Customer creation should include workspace_id in metadata."""
        with patch("app.billing.services.stripe_service.stripe") as mock_stripe:
            mock_customer = MagicMock()
            mock_customer.id = "cus_123"
            mock_stripe.Customer.create.return_value = mock_customer

            await stripe_service.create_customer(
                workspace_id="ws-abc123",
                email="test@example.com",
                name="Test Customer",
            )

            # Verify workspace_id is in metadata
            call_kwargs = mock_stripe.Customer.create.call_args[1]
            assert call_kwargs["metadata"]["workspace_id"] == "ws-abc123"

    @pytest.mark.asyncio
    async def test_customer_metadata_merges_additional_metadata(self, stripe_service):
        """Additional metadata should be merged with workspace_id."""
        with patch("app.billing.services.stripe_service.stripe") as mock_stripe:
            mock_customer = MagicMock()
            mock_customer.id = "cus_123"
            mock_stripe.Customer.create.return_value = mock_customer

            await stripe_service.create_customer(
                workspace_id="ws-abc123",
                email="test@example.com",
                name="Test Customer",
                metadata={"custom_field": "custom_value", "tier": "enterprise"},
            )

            call_kwargs = mock_stripe.Customer.create.call_args[1]
            assert call_kwargs["metadata"]["workspace_id"] == "ws-abc123"
            assert call_kwargs["metadata"]["custom_field"] == "custom_value"
            assert call_kwargs["metadata"]["tier"] == "enterprise"


class TestGetOrCreateCustomer:
    """Tests for StripeService.get_or_create_customer method."""

    @pytest.fixture
    def stripe_service(self):
        """Create a StripeService with mocked settings."""
        with patch("app.billing.services.stripe_service.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = "sk_test_123"
            return StripeService()

    @pytest.mark.asyncio
    async def test_returns_existing_customer_id_if_found(self, stripe_service):
        """Should return existing customer ID when customer exists."""
        mock_customer = MagicMock()
        mock_customer.id = "cus_existing_123"

        stripe_service.get_customer = AsyncMock(return_value=mock_customer)

        result = await stripe_service.get_or_create_customer(
            workspace_id="ws-123",
            email="test@example.com",
            name="Test",
            existing_customer_id="cus_existing_123",
        )

        assert result == "cus_existing_123"

    @pytest.mark.asyncio
    async def test_creates_new_customer_if_none_exists(self, stripe_service):
        """Should create new customer when no existing customer ID provided."""
        mock_new_customer = MagicMock()
        mock_new_customer.id = "cus_new_456"

        stripe_service.create_customer = AsyncMock(return_value=mock_new_customer)

        result = await stripe_service.get_or_create_customer(
            workspace_id="ws-123",
            email="test@example.com",
            name="Test",
            existing_customer_id=None,
        )

        assert result == "cus_new_456"

    @pytest.mark.asyncio
    async def test_creates_new_customer_if_existing_not_found(self, stripe_service):
        """Should create new customer when existing ID returns None."""
        mock_new_customer = MagicMock()
        mock_new_customer.id = "cus_new_789"

        stripe_service.get_customer = AsyncMock(return_value=None)
        stripe_service.create_customer = AsyncMock(return_value=mock_new_customer)

        result = await stripe_service.get_or_create_customer(
            workspace_id="ws-123",
            email="test@example.com",
            name="Test",
            existing_customer_id="cus_deleted",
        )

        assert result == "cus_new_789"


class TestCancelSubscription:
    """Tests for StripeService.cancel_subscription method."""

    @pytest.fixture
    def stripe_service(self):
        """Create a StripeService with mocked settings."""
        with patch("app.billing.services.stripe_service.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = "sk_test_123"
            return StripeService()

    @pytest.mark.asyncio
    async def test_immediate_cancel_uses_prorate(self, stripe_service):
        """Immediate cancellation should use prorate=True."""
        with patch("app.billing.services.stripe_service.stripe") as mock_stripe:
            mock_subscription = MagicMock()
            mock_stripe.Subscription.cancel.return_value = mock_subscription

            await stripe_service.cancel_subscription("sub_123", immediate=True)

            mock_stripe.Subscription.cancel.assert_called_once_with(
                "sub_123", prorate=True
            )

    @pytest.mark.asyncio
    async def test_non_immediate_cancel_sets_cancel_at_period_end(self, stripe_service):
        """Non-immediate cancellation should set cancel_at_period_end=True."""
        with patch("app.billing.services.stripe_service.stripe") as mock_stripe:
            mock_subscription = MagicMock()
            mock_stripe.Subscription.modify.return_value = mock_subscription

            await stripe_service.cancel_subscription("sub_123", immediate=False)

            mock_stripe.Subscription.modify.assert_called_once_with(
                "sub_123", cancel_at_period_end=True
            )


class TestUpdateSubscription:
    """Tests for StripeService.update_subscription method."""

    @pytest.fixture
    def stripe_service(self):
        """Create a StripeService with mocked settings."""
        with patch("app.billing.services.stripe_service.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = "sk_test_123"
            return StripeService()

    @pytest.mark.asyncio
    async def test_update_uses_proration_behavior(self, stripe_service):
        """Updates should use create_prorations proration behavior."""
        with patch("app.billing.services.stripe_service.stripe") as mock_stripe:
            # Mock subscription with items
            mock_subscription = MagicMock()
            mock_item = MagicMock()
            mock_item.id = "si_123"
            mock_subscription.items.data = [mock_item]
            mock_stripe.Subscription.retrieve.return_value = mock_subscription
            mock_stripe.Subscription.modify.return_value = mock_subscription

            await stripe_service.update_subscription("sub_123", quantity=5)

            mock_stripe.Subscription.modify.assert_called_once()
            call_kwargs = mock_stripe.Subscription.modify.call_args[1]
            assert call_kwargs["proration_behavior"] == "create_prorations"

    @pytest.mark.asyncio
    async def test_update_with_no_changes_skips_modify(self, stripe_service):
        """Update with no changes should not call modify."""
        with patch("app.billing.services.stripe_service.stripe") as mock_stripe:
            mock_subscription = MagicMock()
            mock_subscription.items.data = []
            mock_stripe.Subscription.retrieve.return_value = mock_subscription

            await stripe_service.update_subscription("sub_123")

            mock_stripe.Subscription.modify.assert_not_called()


class TestReactivateSubscription:
    """Tests for StripeService.reactivate_subscription method."""

    @pytest.fixture
    def stripe_service(self):
        """Create a StripeService with mocked settings."""
        with patch("app.billing.services.stripe_service.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = "sk_test_123"
            return StripeService()

    @pytest.mark.asyncio
    async def test_reactivate_sets_cancel_at_period_end_false(self, stripe_service):
        """Reactivation should set cancel_at_period_end=False."""
        with patch("app.billing.services.stripe_service.stripe") as mock_stripe:
            mock_subscription = MagicMock()
            mock_stripe.Subscription.modify.return_value = mock_subscription

            await stripe_service.reactivate_subscription("sub_123")

            mock_stripe.Subscription.modify.assert_called_once_with(
                "sub_123", cancel_at_period_end=False
            )
