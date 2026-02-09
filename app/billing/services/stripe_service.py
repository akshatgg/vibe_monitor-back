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

    @stripe_api_metric("update_additional_services")
    async def update_additional_services(
        self,
        subscription_id: str,
        additional_service_price_id: str,
        quantity: int,
    ) -> StripeSubscription:
        """
        Update the additional services subscription item.

        This handles adding, updating, or removing the additional services item
        from a subscription.

        Args:
            subscription_id: Stripe subscription ID
            additional_service_price_id: Price ID for additional services
            quantity: Number of additional services (0 to remove)

        Returns:
            Updated stripe.Subscription object
        """
        try:
            # Retrieve subscription with items expanded
            subscription = stripe.Subscription.retrieve(
                subscription_id,
                expand=["items.data.price"]
            )

            # Find the additional services item if it exists
            additional_services_item = None
            for item in subscription["items"]["data"]:
                if item["price"]["id"] == additional_service_price_id:
                    additional_services_item = item
                    break

            if quantity > 0:
                if additional_services_item:
                    # Update existing item
                    subscription = stripe.Subscription.modify(
                        subscription_id,
                        items=[{
                            "id": additional_services_item["id"],
                            "quantity": quantity,
                        }],
                        proration_behavior="create_prorations",
                    )
                    logger.info(
                        f"Updated additional services quantity to {quantity} "
                        f"for subscription {subscription_id}"
                    )
                else:
                    # Add new item for additional services
                    subscription = stripe.Subscription.modify(
                        subscription_id,
                        items=[{
                            "price": additional_service_price_id,
                            "quantity": quantity,
                        }],
                        proration_behavior="create_prorations",
                    )
                    logger.info(
                        f"Added additional services item with quantity {quantity} "
                        f"to subscription {subscription_id}"
                    )
            elif additional_services_item:
                # Remove the additional services item if quantity is 0
                subscription = stripe.Subscription.modify(
                    subscription_id,
                    items=[{
                        "id": additional_services_item["id"],
                        "deleted": True,
                    }],
                    proration_behavior="create_prorations",
                )
                logger.info(
                    f"Removed additional services item from subscription {subscription_id}"
                )

            return subscription
        except stripe.error.StripeError as e:
            logger.error(f"Failed to update additional services: {e}")
            raise

    @stripe_api_metric("reset_subscription_billing_cycle")
    async def reset_subscription_with_new_billing_cycle(
        self,
        subscription_id: str,
        base_price_id: str,
        additional_service_price_id: str,
        additional_service_quantity: int,
        old_monthly_amount_cents: int,
    ) -> StripeSubscription:
        """
        Cancel current subscription and create new one with reset billing cycle.

        This implements the "billing cycle reset" approach where:
        1. Calculate credit for unused days on current subscription
        2. Cancel current subscription immediately
        3. Create new subscription starting today (new billing cycle anchor)
        4. Apply credit to reduce immediate charge

        Args:
            subscription_id: Current Stripe subscription ID to cancel
            base_price_id: Base plan price ID (e.g., Pro plan)
            additional_service_price_id: Additional service price ID
            additional_service_quantity: Number of additional services
            old_monthly_amount_cents: Total monthly cost of old subscription in cents

        Returns:
            New stripe.Subscription object with reset billing cycle
        """
        try:
            from datetime import datetime, timezone

            # Get current subscription to calculate credit
            old_sub = stripe.Subscription.retrieve(subscription_id)
            customer_id = old_sub.customer

            # Calculate unused days credit
            now = datetime.now(timezone.utc)
            period_end = datetime.fromtimestamp(old_sub.current_period_end, tz=timezone.utc)
            period_start = datetime.fromtimestamp(old_sub.current_period_start, tz=timezone.utc)

            days_total = (period_end - period_start).days
            days_remaining = max(0, (period_end - now).days)

            # Credit = (days_remaining / days_total) * old_monthly_cost
            # Multiply first to avoid precision loss with small fractions
            credit_amount_cents = int((days_remaining * old_monthly_amount_cents) / days_total)

            logger.info(
                f"Resetting subscription {subscription_id}: "
                f"{days_remaining}/{days_total} days unused, "
                f"credit: ${credit_amount_cents/100:.2f}"
            )

            # Cancel old subscription immediately (no proration since we're doing manual credit)
            stripe.Subscription.delete(subscription_id)
            logger.info(f"Canceled old subscription {subscription_id}")

            # Build new subscription items
            new_items = [{"price": base_price_id, "quantity": 1}]
            if additional_service_quantity > 0:
                new_items.append({
                    "price": additional_service_price_id,
                    "quantity": additional_service_quantity
                })

            # Create new subscription starting immediately (Stripe handles billing anchor)
            # Don't set billing_cycle_anchor explicitly - it causes "timestamp in the past" errors
            # due to processing delays. Stripe will anchor to subscription creation time.
            new_sub = stripe.Subscription.create(
                customer=customer_id,
                items=new_items,
                proration_behavior="none",  # No proration, we handle credit manually
                metadata=old_sub.metadata,
            )

            logger.info(
                f"Created new subscription {new_sub.id} with billing anchor at {now.isoformat()}"
            )

            # Apply credit as invoice item (negative amount = credit)
            if credit_amount_cents > 0:
                stripe.InvoiceItem.create(
                    customer=customer_id,
                    amount=-credit_amount_cents,  # Negative for credit
                    currency="usd",
                    description=f"Credit for {days_remaining} unused days from previous billing cycle",
                    subscription=new_sub.id,
                )
                logger.info(f"Applied credit of ${credit_amount_cents/100:.2f} to customer")

            return new_sub

        except stripe.error.StripeError as e:
            logger.error(f"Failed to reset subscription billing cycle: {e}")
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
                # Pass metadata to the subscription that will be created
                subscription_data={
                    "metadata": metadata or {},
                },
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

    @stripe_api_metric("create_subscription_schedule")
    async def create_subscription_schedule(
        self,
        subscription_id: str,
        phases: list[dict],
    ) -> stripe.SubscriptionSchedule:
        """
        Create a subscription schedule for future changes.

        Args:
            subscription_id: Stripe subscription ID
            phases: List of phase dicts with items, end_date, start_date etc.
                   NOTE: For phase 1, start_date will be replaced with the actual schedule start

        Returns:
            stripe.SubscriptionSchedule object
        """
        try:
            # Step 1: Create schedule from subscription (without phases parameter)
            schedule = stripe.SubscriptionSchedule.create(
                from_subscription=subscription_id,
            )
            logger.info(f"Created subscription schedule {schedule.id} from subscription {subscription_id}")

            # Step 2: Get the current phase's actual start_date
            current_phase = schedule.phases[0] if schedule.phases else None
            if not current_phase:
                raise ValueError("Created schedule has no phases")

            actual_start_date = current_phase.start_date
            logger.info(f"Schedule phase 1 starts at: {actual_start_date}")

            # Step 3: Update phases to use the actual start_date for phase 1
            updated_phases = phases.copy()
            if len(updated_phases) > 0:
                # Replace phase 1 start_date with actual start from created schedule
                updated_phases[0] = {**updated_phases[0], "start_date": actual_start_date}

            # Step 4: Modify schedule with corrected phases
            schedule = stripe.SubscriptionSchedule.modify(
                schedule.id,
                phases=updated_phases,
            )
            logger.info(f"Updated schedule {schedule.id} with custom phases")
            return schedule
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create subscription schedule: {e}")
            raise

    async def cancel_subscription_schedule(self, schedule_id: str) -> stripe.SubscriptionSchedule:
        """
        Cancel a subscription schedule and release the subscription.

        Args:
            schedule_id: Stripe subscription schedule ID

        Returns:
            stripe.SubscriptionSchedule object
        """
        try:
            # Release the subscription by canceling the schedule
            schedule = stripe.SubscriptionSchedule.release(schedule_id)
            logger.info(f"Released subscription schedule {schedule_id}")
            return schedule
        except stripe.error.StripeError as e:
            logger.error(f"Failed to release subscription schedule: {e}")
            raise

    async def update_subscription_schedule(
        self,
        schedule_id: str,
        phases: list[dict],
    ) -> stripe.SubscriptionSchedule:
        """
        Update an existing subscription schedule with new phases.

        Args:
            schedule_id: Stripe subscription schedule ID
            phases: List of phase dicts with items, end_date, etc.

        Returns:
            stripe.SubscriptionSchedule object
        """
        try:
            schedule = stripe.SubscriptionSchedule.modify(
                schedule_id,
                phases=phases,
            )
            logger.info(f"Updated subscription schedule {schedule_id} with new phases")
            return schedule
        except stripe.error.StripeError as e:
            logger.error(f"Failed to update subscription schedule: {e}")
            raise

    async def get_subscription_schedule_for_subscription(
        self,
        subscription_id: str,
    ) -> Optional[str]:
        """
        Get the schedule ID for a subscription if one exists.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            Schedule ID or None
        """
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            schedule_id = subscription.get('schedule')
            if schedule_id:
                logger.info(f"Found schedule {schedule_id} for subscription {subscription_id}")
                return schedule_id
            return None
        except stripe.error.StripeError as e:
            logger.error(f"Failed to get schedule for subscription: {e}")
            return None

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
