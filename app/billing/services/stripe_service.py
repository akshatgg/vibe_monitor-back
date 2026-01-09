"""
Stripe API service for handling all Stripe interactions.
Wraps the Stripe SDK for subscription management, customer creation,
and webhook handling.
"""

import logging
from typing import Optional

import stripe
from stripe import Customer
from stripe import Subscription as StripeSubscription
from stripe.billing_portal import Session as BillingPortalSession

from app.billing.stripe_instrumentation import stripe_api_metric
from app.core.config import settings

logger = logging.getLogger(__name__)


class StripeService:
    """Handles all Stripe API interactions."""

    def __init__(self):
        """Initialize Stripe with the secret key from settings."""
        if settings.STRIPE_SECRET_KEY:
            stripe.api_key = settings.STRIPE_SECRET_KEY
        else:
            logger.warning(
                "STRIPE_SECRET_KEY not configured - Stripe operations will fail"
            )

    @stripe_api_metric("create_customer")
    async def create_customer(
        self,
        workspace_id: str,
        email: str,
        name: str,
        metadata: Optional[dict] = None,
    ) -> Customer:
        """
        Create a Stripe customer for a workspace.

        Args:
            workspace_id: The internal workspace ID
            email: Customer email address
            name: Customer/workspace name
            metadata: Additional metadata to store with the customer

        Returns:
            stripe.Customer object
        """
        customer_metadata = {"workspace_id": workspace_id}
        if metadata:
            customer_metadata.update(metadata)

        try:
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata=customer_metadata,
            )
            logger.info(
                f"Created Stripe customer {customer.id} for workspace {workspace_id}"
            )
            return customer
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create Stripe customer: {e}")
            raise

    async def get_customer(self, customer_id: str) -> Optional[Customer]:
        """
        Retrieve a Stripe customer by ID.

        Args:
            customer_id: Stripe customer ID (cus_...)

        Returns:
            stripe.Customer object or None if not found
        """
        try:
            return stripe.Customer.retrieve(customer_id)
        except stripe.error.InvalidRequestError:
            logger.warning(f"Stripe customer {customer_id} not found")
            return None
        except stripe.error.StripeError as e:
            logger.error(f"Failed to retrieve Stripe customer: {e}")
            raise

    async def get_or_create_customer(
        self,
        workspace_id: str,
        email: str,
        name: str,
        existing_customer_id: Optional[str] = None,
    ) -> str:
        """
        Get existing customer or create a new one.

        Args:
            workspace_id: The internal workspace ID
            email: Customer email address
            name: Customer/workspace name
            existing_customer_id: Existing Stripe customer ID if known

        Returns:
            Stripe customer ID
        """
        # Try to retrieve existing customer
        if existing_customer_id:
            customer = await self.get_customer(existing_customer_id)
            if customer:
                return customer.id

        # Create new customer
        customer = await self.create_customer(workspace_id, email, name)
        return customer.id

    @stripe_api_metric("create_subscription")
    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        quantity: int = 1,
        metadata: Optional[dict] = None,
    ) -> StripeSubscription:
        """
        Create a new subscription for a customer.

        Args:
            customer_id: Stripe customer ID
            price_id: Stripe price ID for the subscription
            quantity: Number of units (e.g., number of additional services)
            metadata: Additional metadata to store with the subscription

        Returns:
            stripe.Subscription object
        """
        try:
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id, "quantity": quantity}],
                metadata=metadata or {},
                payment_behavior="default_incomplete",
                expand=["latest_invoice.payment_intent"],
            )
            logger.info(
                f"Created Stripe subscription {subscription.id} for customer {customer_id}"
            )
            return subscription
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create Stripe subscription: {e}")
            raise

    async def get_subscription(
        self, subscription_id: str
    ) -> Optional[StripeSubscription]:
        """
        Retrieve a Stripe subscription by ID.

        Args:
            subscription_id: Stripe subscription ID (sub_...)

        Returns:
            stripe.Subscription object or None if not found
        """
        try:
            return stripe.Subscription.retrieve(subscription_id)
        except stripe.error.InvalidRequestError:
            logger.warning(f"Stripe subscription {subscription_id} not found")
            return None
        except stripe.error.StripeError as e:
            logger.error(f"Failed to retrieve Stripe subscription: {e}")
            raise

    @stripe_api_metric("update_subscription")
    async def update_subscription(
        self,
        subscription_id: str,
        quantity: Optional[int] = None,
        price_id: Optional[str] = None,
    ) -> StripeSubscription:
        """
        Update a subscription (e.g., change service count or plan).

        Stripe automatically handles prorated billing when updating.

        Args:
            subscription_id: Stripe subscription ID
            quantity: New quantity (if changing)
            price_id: New price ID (if changing plans)

        Returns:
            Updated stripe.Subscription object
        """
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)

            update_params = {}

            # Get the first subscription item (assuming single-item subscriptions)
            if subscription.items.data:
                item_id = subscription.items.data[0].id

                if quantity is not None or price_id is not None:
                    item_update = {"id": item_id}
                    if quantity is not None:
                        item_update["quantity"] = quantity
                    if price_id is not None:
                        item_update["price"] = price_id
                    update_params["items"] = [item_update]

            if update_params:
                subscription = stripe.Subscription.modify(
                    subscription_id,
                    proration_behavior="create_prorations",
                    **update_params,
                )
                logger.info(f"Updated Stripe subscription {subscription_id}")

            return subscription
        except stripe.error.StripeError as e:
            logger.error(f"Failed to update Stripe subscription: {e}")
            raise

    @stripe_api_metric("cancel_subscription")
    async def cancel_subscription(
        self,
        subscription_id: str,
        immediate: bool = False,
    ) -> StripeSubscription:
        """
        Cancel a subscription.

        Args:
            subscription_id: Stripe subscription ID
            immediate: If True, cancel immediately with proration.
                      If False (default), cancel at end of billing period.

        Returns:
            Updated stripe.Subscription object
        """
        try:
            if immediate:
                # Cancel immediately with proration
                subscription = stripe.Subscription.cancel(
                    subscription_id,
                    prorate=True,
                )
            else:
                # Cancel at end of billing period
                subscription = stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True,
                )
            logger.info(
                f"Canceled Stripe subscription {subscription_id} "
                f"(immediate={immediate})"
            )
            return subscription
        except stripe.error.StripeError as e:
            logger.error(f"Failed to cancel Stripe subscription: {e}")
            raise

    async def reactivate_subscription(
        self,
        subscription_id: str,
    ) -> StripeSubscription:
        """
        Reactivate a subscription that was scheduled to cancel at period end.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            Updated stripe.Subscription object
        """
        try:
            subscription = stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=False,
            )
            logger.info(f"Reactivated Stripe subscription {subscription_id}")
            return subscription
        except stripe.error.StripeError as e:
            logger.error(f"Failed to reactivate Stripe subscription: {e}")
            raise

    @stripe_api_metric("create_billing_portal_session")
    async def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ) -> BillingPortalSession:
        """
        Create a Stripe Customer Portal session for self-service billing.

        Args:
            customer_id: Stripe customer ID
            return_url: URL to return to after portal session

        Returns:
            stripe.billing_portal.Session object with URL
        """
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            logger.info(f"Created billing portal session for customer {customer_id}")
            return session
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create billing portal session: {e}")
            raise

    @stripe_api_metric("create_checkout_session")
    async def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        quantity: int = 1,
        metadata: Optional[dict] = None,
    ) -> stripe.checkout.Session:
        """
        Create a Stripe Checkout session for subscription signup.

        Args:
            customer_id: Stripe customer ID
            price_id: Stripe price ID
            success_url: URL to redirect to on successful payment
            cancel_url: URL to redirect to if user cancels
            quantity: Number of units
            metadata: Additional metadata

        Returns:
            stripe.checkout.Session object with URL
        """
        try:
            session = stripe.checkout.Session.create(
                customer=customer_id,
                mode="subscription",
                line_items=[{"price": price_id, "quantity": quantity}],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata or {},
            )
            logger.info(
                f"Created checkout session {session.id} for customer {customer_id}"
            )
            return session
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create checkout session: {e}")
            raise

    async def list_invoices(
        self,
        customer_id: str,
        limit: int = 10,
    ) -> list[stripe.Invoice]:
        """
        List invoices for a customer.

        Args:
            customer_id: Stripe customer ID
            limit: Maximum number of invoices to return

        Returns:
            List of stripe.Invoice objects
        """
        try:
            invoices = stripe.Invoice.list(
                customer=customer_id,
                limit=limit,
            )
            return invoices.data
        except stripe.error.StripeError as e:
            logger.error(f"Failed to list invoices: {e}")
            raise

    def construct_webhook_event(
        self,
        payload: bytes,
        signature: str,
    ) -> stripe.Event:
        """
        Verify and construct a webhook event from Stripe.

        Args:
            payload: Raw request body bytes
            signature: Stripe-Signature header value

        Returns:
            stripe.Event object

        Raises:
            stripe.error.SignatureVerificationError: If signature is invalid
        """
        if not settings.STRIPE_WEBHOOK_SECRET:
            raise ValueError("STRIPE_WEBHOOK_SECRET not configured")

        return stripe.Webhook.construct_event(
            payload,
            signature,
            settings.STRIPE_WEBHOOK_SECRET,
        )


# Singleton instance
stripe_service = StripeService()
