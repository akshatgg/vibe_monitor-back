"""
Subscription service for business logic around billing and subscriptions.
Orchestrates between the database models and Stripe API.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.billing.services.stripe_service import stripe_service
from app.core.config import settings
from app.models import Plan, PlanType, Subscription, SubscriptionStatus

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Business logic for subscription management."""

    async def get_plan_by_type(
        self,
        db: AsyncSession,
        plan_type: PlanType,
    ) -> Optional[Plan]:
        """
        Get a plan by its type.

        Args:
            db: Database session
            plan_type: PlanType enum value (FREE or PRO)

        Returns:
            Plan object or None
        """
        result = await db.execute(
            select(Plan).where(Plan.plan_type == plan_type, Plan.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_plan_by_id(
        self,
        db: AsyncSession,
        plan_id: str,
    ) -> Optional[Plan]:
        """Get a plan by its ID."""
        result = await db.execute(select(Plan).where(Plan.id == plan_id))
        return result.scalar_one_or_none()

    async def get_all_plans(
        self,
        db: AsyncSession,
        active_only: bool = True,
    ) -> list[Plan]:
        """Get all plans."""
        query = select(Plan)
        if active_only:
            query = query.where(Plan.is_active.is_(True))
        result = await db.execute(query.order_by(Plan.base_price_cents))
        return list(result.scalars().all())

    async def get_workspace_subscription(
        self,
        db: AsyncSession,
        workspace_id: str,
    ) -> Optional[Subscription]:
        """
        Get the current subscription for a workspace.

        Args:
            db: Database session
            workspace_id: Workspace ID

        Returns:
            Subscription object or None
        """
        result = await db.execute(
            select(Subscription)
            .options(selectinload(Subscription.plan))
            .where(Subscription.workspace_id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def create_subscription(
        self,
        db: AsyncSession,
        workspace_id: str,
        plan_id: str,
    ) -> Subscription:
        """
        Create a subscription for a workspace (typically Free plan on signup).

        Args:
            db: Database session
            workspace_id: Workspace ID
            plan_id: Plan ID to subscribe to

        Returns:
            Created Subscription object
        """
        subscription = Subscription(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            plan_id=plan_id,
            status=SubscriptionStatus.ACTIVE,
            billable_service_count=0,
        )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)
        logger.info(
            f"Created subscription {subscription.id} for workspace {workspace_id}"
        )
        return subscription

    async def subscribe_to_pro(
        self,
        db: AsyncSession,
        workspace_id: str,
        owner_email: str,
        owner_name: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """
        Initiate subscription to Pro plan via Stripe Checkout.

        Args:
            db: Database session
            workspace_id: Workspace ID
            owner_email: Email of the workspace owner
            owner_name: Name of the workspace owner
            success_url: URL to redirect to on successful payment
            cancel_url: URL to redirect to if user cancels

        Returns:
            Stripe Checkout session URL
        """
        # Get current subscription
        subscription = await self.get_workspace_subscription(db, workspace_id)
        if not subscription:
            raise ValueError(f"No subscription found for workspace {workspace_id}")

        # Get Pro plan
        pro_plan = await self.get_plan_by_type(db, PlanType.PRO)
        if not pro_plan:
            raise ValueError("Pro plan not found")

        if not settings.STRIPE_PRO_PLAN_PRICE_ID:
            raise ValueError("STRIPE_PRO_PLAN_PRICE_ID not configured")

        # Get or create Stripe customer
        customer_id = await stripe_service.get_or_create_customer(
            workspace_id=workspace_id,
            email=owner_email,
            name=owner_name,
            existing_customer_id=subscription.stripe_customer_id,
        )

        # Update subscription with customer ID
        subscription.stripe_customer_id = customer_id
        await db.commit()

        # Create Checkout session
        checkout_session = await stripe_service.create_checkout_session(
            customer_id=customer_id,
            price_id=settings.STRIPE_PRO_PLAN_PRICE_ID,
            success_url=success_url,
            cancel_url=cancel_url,
            quantity=1,
            metadata={"workspace_id": workspace_id, "plan_id": pro_plan.id},
        )

        return checkout_session.url

    async def create_service_update_checkout(
        self,
        db: AsyncSession,
        workspace_id: str,
        new_service_count: int,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """
        Create Stripe Checkout session for updating service count.

        This shows the user:
        - New monthly cost
        - Credit for unused days
        - Final amount to pay today

        Args:
            db: Database session
            workspace_id: Workspace ID
            new_service_count: New total number of services
            success_url: URL to redirect on success
            cancel_url: URL to redirect on cancel

        Returns:
            Checkout session URL
        """
        subscription = await self.get_workspace_subscription(db, workspace_id)
        if not subscription:
            raise ValueError(f"No subscription found for workspace {workspace_id}")

        plan = await self.get_plan_by_id(db, subscription.plan_id)
        if not plan:
            raise ValueError(f"Plan {subscription.plan_id} not found")

        if not subscription.stripe_subscription_id:
            raise ValueError("No Stripe subscription found")

        if not settings.STRIPE_PRO_PLAN_PRICE_ID or not settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID:
            raise ValueError("Stripe price IDs not configured")

        # Calculate new billable count
        new_billable_count = max(0, new_service_count - plan.base_service_count)

        # Calculate old and new monthly costs
        old_billable_count = subscription.billable_service_count
        old_monthly_cost_cents = (
            plan.base_price_cents +
            (old_billable_count * plan.additional_service_price_cents)
        )
        new_monthly_cost_cents = (
            plan.base_price_cents +
            (new_billable_count * plan.additional_service_price_cents)
        )

        # Calculate credit for unused days
        old_stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
        now = datetime.now(timezone.utc)
        period_end = datetime.fromtimestamp(old_stripe_sub.current_period_end, tz=timezone.utc)
        period_start = datetime.fromtimestamp(old_stripe_sub.current_period_start, tz=timezone.utc)

        days_total = max(1, (period_end - period_start).days)
        days_remaining = max(0, (period_end - now).days)
        credit_cents = int((days_remaining / days_total) * old_monthly_cost_cents)

        logger.info(
            f"Service update checkout for workspace {workspace_id}: "
            f"Old: ${old_monthly_cost_cents/100:.2f}/mo, "
            f"New: ${new_monthly_cost_cents/100:.2f}/mo, "
            f"Credit: ${credit_cents/100:.2f} ({days_remaining}/{days_total} days)"
        )

        # Create coupon for the credit amount (one-time discount)
        coupon_id = f"credit_{workspace_id}_{uuid.uuid4().hex[:8]}"
        stripe.Coupon.create(
            id=coupon_id,
            amount_off=credit_cents,
            currency="usd",
            duration="once",
            name=f"Credit for {days_remaining} unused days",
        )

        # Create checkout session for new subscription
        customer_id = subscription.stripe_customer_id
        if not customer_id:
            raise ValueError("No Stripe customer ID found")

        # Build line items
        line_items = [{"price": settings.STRIPE_PRO_PLAN_PRICE_ID, "quantity": 1}]
        if new_billable_count > 0:
            line_items.append({
                "price": settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID,
                "quantity": new_billable_count
            })

        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=line_items,
            success_url=success_url,
            cancel_url=cancel_url,
            discounts=[{"coupon": coupon_id}],
            metadata={
                "workspace_id": workspace_id,
                "plan_id": plan.id,
                "old_subscription_id": subscription.stripe_subscription_id,
                "service_count_update": "true",
                "new_service_count": str(new_service_count),
            },
            subscription_data={
                "metadata": {
                    "workspace_id": workspace_id,
                    "plan_id": plan.id,
                    "service_count_update": "true",
                    "new_service_count": str(new_service_count),
                },
            },
        )

        logger.info(f"Created service update checkout session {checkout_session.id}")
        return checkout_session.url

    async def update_service_count(
        self,
        db: AsyncSession,
        workspace_id: str,
        new_service_count: int,
    ) -> Subscription:
        """
        Update the billable service count (resets billing cycle with credit).

        This implements billing cycle reset approach:
        - Cancels current subscription
        - Calculates credit for unused days
        - Creates new subscription starting today
        - New billing cycle anchor = today's date

        Args:
            db: Database session
            workspace_id: Workspace ID
            new_service_count: New total number of services

        Returns:
            Updated Subscription object
        """
        subscription = await self.get_workspace_subscription(db, workspace_id)
        if not subscription:
            raise ValueError(f"No subscription found for workspace {workspace_id}")

        plan = await self.get_plan_by_id(db, subscription.plan_id)
        if not plan:
            raise ValueError(f"Plan {subscription.plan_id} not found")

        # Calculate new billable services (above base count)
        new_billable_count = max(0, new_service_count - plan.base_service_count)

        # Update Stripe if there's an active subscription
        if (
            subscription.stripe_subscription_id
            and subscription.status == SubscriptionStatus.ACTIVE
            and settings.STRIPE_PRO_PLAN_PRICE_ID
            and settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID
        ):
            # Calculate old monthly cost for credit calculation
            old_billable_count = subscription.billable_service_count
            old_monthly_cost_cents = (
                plan.base_price_cents +
                (old_billable_count * plan.additional_service_price_cents)
            )

            # Reset subscription with new billing cycle
            new_stripe_sub = await stripe_service.reset_subscription_with_new_billing_cycle(
                subscription_id=subscription.stripe_subscription_id,
                base_price_id=settings.STRIPE_PRO_PLAN_PRICE_ID,
                additional_service_price_id=settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID,
                additional_service_quantity=new_billable_count,
                old_monthly_amount_cents=old_monthly_cost_cents,
            )

            # Update subscription with new Stripe subscription ID
            subscription.stripe_subscription_id = new_stripe_sub.id
            subscription.current_period_start = datetime.fromtimestamp(
                new_stripe_sub.current_period_start, tz=timezone.utc
            )
            subscription.current_period_end = datetime.fromtimestamp(
                new_stripe_sub.current_period_end, tz=timezone.utc
            )

        # Update local record
        subscription.billable_service_count = new_billable_count

        # Clear any pending downgrade since we're creating a new subscription
        # (old subscription with schedule is being deleted)
        subscription.pending_billable_service_count = None
        subscription.pending_change_date = None
        subscription.subscription_schedule_id = None

        await db.commit()
        await db.refresh(subscription)

        logger.info(
            f"Reset subscription for workspace {workspace_id}: "
            f"{new_service_count} total services, {new_billable_count} billable. "
            f"New billing cycle starts today. Cleared any pending downgrades."
        )
        return subscription

    async def cancel_subscription(
        self,
        db: AsyncSession,
        workspace_id: str,
        immediate: bool = False,
    ) -> Subscription:
        """
        Cancel a subscription.

        Args:
            db: Database session
            workspace_id: Workspace ID
            immediate: If True, cancel immediately. Otherwise, at period end.

        Returns:
            Updated Subscription object
        """
        subscription = await self.get_workspace_subscription(db, workspace_id)
        if not subscription:
            raise ValueError(f"No subscription found for workspace {workspace_id}")

        # Cancel in Stripe if there's an active subscription
        if subscription.stripe_subscription_id:
            # If there's a subscription schedule (pending downgrade), release it first.
            # Stripe won't allow canceling a subscription managed by a schedule directly.
            if subscription.subscription_schedule_id:
                try:
                    await stripe_service.cancel_subscription_schedule(
                        subscription.subscription_schedule_id
                    )
                    logger.info(
                        f"Released subscription schedule {subscription.subscription_schedule_id} "
                        f"before canceling subscription for workspace {workspace_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to release schedule {subscription.subscription_schedule_id}: {e}. "
                        f"Continuing with cancellation."
                    )
                # Clear pending downgrade fields
                subscription.pending_billable_service_count = None
                subscription.pending_change_date = None
                subscription.subscription_schedule_id = None

            await stripe_service.cancel_subscription(
                subscription_id=subscription.stripe_subscription_id,
                immediate=immediate,
            )

            if immediate:
                # Immediate cancellation - downgrade to FREE now
                subscription.status = SubscriptionStatus.CANCELED
                subscription.canceled_at = datetime.now(timezone.utc)

                # Downgrade to Free plan
                free_plan = await self.get_plan_by_type(db, PlanType.FREE)
                if free_plan:
                    subscription.plan_id = free_plan.id
                    subscription.stripe_subscription_id = None
                    subscription.status = SubscriptionStatus.ACTIVE
            else:
                # Cancel at period end - keep PRO until period ends
                subscription.canceled_at = datetime.now(timezone.utc)
                # Status stays ACTIVE until period ends
        else:
            # No Stripe subscription - just cancel locally
            if immediate:
                subscription.status = SubscriptionStatus.CANCELED
                subscription.canceled_at = datetime.now(timezone.utc)

                free_plan = await self.get_plan_by_type(db, PlanType.FREE)
                if free_plan:
                    subscription.plan_id = free_plan.id
                    subscription.status = SubscriptionStatus.ACTIVE

        await db.commit()
        await db.refresh(subscription)

        logger.info(
            f"Canceled subscription for workspace {workspace_id} "
            f"(immediate={immediate})"
        )
        return subscription

    async def get_billing_portal_url(
        self,
        db: AsyncSession,
        workspace_id: str,
        return_url: str,
    ) -> str:
        """
        Get Stripe Customer Portal URL for self-service billing.

        Args:
            db: Database session
            workspace_id: Workspace ID
            return_url: URL to return to after portal session

        Returns:
            Stripe Customer Portal URL
        """
        subscription = await self.get_workspace_subscription(db, workspace_id)
        if not subscription or not subscription.stripe_customer_id:
            raise ValueError("No Stripe customer found for this workspace")

        session = await stripe_service.create_billing_portal_session(
            customer_id=subscription.stripe_customer_id,
            return_url=return_url,
        )
        return session.url

    # Webhook handlers

    async def handle_subscription_created(
        self,
        db: AsyncSession,
        stripe_subscription: stripe.Subscription,
    ) -> None:
        """Handle customer.subscription.created webhook event."""
        logger.info(f"Processing subscription.created webhook for {stripe_subscription.id}")
        logger.info(f"Subscription metadata: {stripe_subscription.metadata}")

        workspace_id = stripe_subscription.metadata.get("workspace_id")
        if not workspace_id:
            logger.warning(f"Subscription {stripe_subscription.id} created without workspace_id in metadata")
            return

        subscription = await self.get_workspace_subscription(db, workspace_id)
        if not subscription:
            logger.warning(f"No local subscription found for workspace {workspace_id}")
            return

        # Update with Stripe subscription details
        # Stripe sends lowercase status ("active"), convert to UPPERCASE for our enum
        subscription.stripe_subscription_id = stripe_subscription.id

        # Don't downgrade from ACTIVE to INCOMPLETE (race condition with checkout.completed)
        new_status = SubscriptionStatus(stripe_subscription.status.upper())
        if subscription.status == SubscriptionStatus.ACTIVE and new_status == SubscriptionStatus.INCOMPLETE:
            logger.info(f"Keeping subscription {subscription.id} as ACTIVE (not downgrading to INCOMPLETE in subscription.created)")
        else:
            subscription.status = new_status

        # Handle current_period_start and current_period_end (may be None)
        if hasattr(stripe_subscription, 'current_period_start') and stripe_subscription.current_period_start:
            subscription.current_period_start = datetime.fromtimestamp(
                stripe_subscription.current_period_start, tz=timezone.utc
            )
        if hasattr(stripe_subscription, 'current_period_end') and stripe_subscription.current_period_end:
            subscription.current_period_end = datetime.fromtimestamp(
                stripe_subscription.current_period_end, tz=timezone.utc
            )

        # Update plan if specified in metadata
        plan_id = stripe_subscription.metadata.get("plan_id")
        if plan_id:
            logger.info(f"Updating workspace {workspace_id} to plan {plan_id}")
            subscription.plan_id = plan_id
        else:
            logger.warning(f"No plan_id in subscription metadata for workspace {workspace_id}")

        await db.commit()
        logger.info(f"Successfully updated subscription for workspace {workspace_id}: plan={subscription.plan_id}, stripe_sub={subscription.stripe_subscription_id}")

    async def handle_subscription_updated(
        self,
        db: AsyncSession,
        stripe_subscription: stripe.Subscription,
    ) -> None:
        """Handle customer.subscription.updated webhook event."""
        # Find subscription by Stripe subscription ID
        result = await db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_subscription.id
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            logger.warning(
                f"No local subscription found for Stripe subscription {stripe_subscription.id}"
            )
            return

        # Update status and period
        # Don't downgrade from ACTIVE to INCOMPLETE (race condition with checkout.completed)
        new_status = SubscriptionStatus(stripe_subscription.status.upper())
        if subscription.status == SubscriptionStatus.ACTIVE and new_status == SubscriptionStatus.INCOMPLETE:
            logger.info(f"Keeping subscription {subscription.id} as ACTIVE (not downgrading to INCOMPLETE)")
        else:
            logger.debug(f"Updating subscription status from {subscription.status} to {new_status}")
            subscription.status = new_status

        # Handle current_period_start and current_period_end (may be None)
        if hasattr(stripe_subscription, 'current_period_start') and stripe_subscription.current_period_start:
            subscription.current_period_start = datetime.fromtimestamp(
                stripe_subscription.current_period_start, tz=timezone.utc
            )
        if hasattr(stripe_subscription, 'current_period_end') and stripe_subscription.current_period_end:
            subscription.current_period_end = datetime.fromtimestamp(
                stripe_subscription.current_period_end, tz=timezone.utc
            )

        if stripe_subscription.canceled_at:
            subscription.canceled_at = datetime.fromtimestamp(
                stripe_subscription.canceled_at, tz=timezone.utc
            )

        # Sync billable service count from Stripe subscription items
        # This is CRITICAL for applying pending downgrades when schedule executes
        items = stripe_subscription.get('items', {}).get('data', [])
        if items:
            additional_service_count = 0
            for item in items:
                # Check if this item is for additional services
                if (settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID and
                    item.get('price', {}).get('id') == settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID):
                    additional_service_count = item.get('quantity', 0)
                    break

            # Update billable service count if it changed
            if subscription.billable_service_count != additional_service_count:
                logger.info(
                    f"Syncing billable_service_count from Stripe: "
                    f"{subscription.billable_service_count} -> {additional_service_count}"
                )
                subscription.billable_service_count = additional_service_count

                # If there was a pending downgrade and it matches the new count, clear pending fields
                if (subscription.pending_billable_service_count is not None and
                    subscription.pending_billable_service_count == additional_service_count):
                    logger.info(
                        f"Pending downgrade applied! Clearing pending fields for subscription {subscription.id}"
                    )
                    subscription.pending_billable_service_count = None
                    subscription.pending_change_date = None
                    subscription.subscription_schedule_id = None

        await db.commit()
        logger.info(f"Handled subscription updated for subscription {subscription.id}")

    async def handle_subscription_deleted(
        self,
        db: AsyncSession,
        stripe_subscription_id: str,
    ) -> None:
        """Handle customer.subscription.deleted webhook event."""
        result = await db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_subscription_id
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            logger.info(
                f"No local subscription found for Stripe subscription {stripe_subscription_id} "
                f"(may have already been replaced by a new subscription)"
            )
            return

        # Safety check: verify this is still the active stripe subscription
        # This prevents race conditions where a new subscription was created
        # but the DB hasn't been updated yet
        try:
            stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
            if stripe_sub.status != "canceled":
                logger.warning(
                    f"Stripe subscription {stripe_subscription_id} is not actually canceled "
                    f"(status: {stripe_sub.status}), skipping downgrade"
                )
                return
        except stripe.error.InvalidRequestError:
            # Subscription doesn't exist in Stripe anymore, proceed with downgrade
            pass
        except Exception as e:
            logger.warning(f"Could not verify subscription status: {e}, proceeding with downgrade")

        # Downgrade to Free plan
        free_plan = await self.get_plan_by_type(db, PlanType.FREE)
        if free_plan:
            subscription.plan_id = free_plan.id

        subscription.status = SubscriptionStatus.ACTIVE  # Active on Free plan
        subscription.stripe_subscription_id = None
        subscription.canceled_at = datetime.now(timezone.utc)
        subscription.current_period_start = None
        subscription.current_period_end = None
        subscription.billable_service_count = 0

        await db.commit()
        logger.info(
            f"Handled subscription deleted, downgraded to Free for {subscription.id}"
        )

    async def handle_payment_succeeded(
        self,
        db: AsyncSession,
        invoice: stripe.Invoice,
    ) -> None:
        """Handle invoice.payment_succeeded webhook event."""
        # Check if invoice has subscription attribute (not all invoices do)
        if not hasattr(invoice, 'subscription') or not invoice.subscription:
            return  # Not a subscription invoice

        result = await db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == invoice.subscription
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            return

        # Ensure status is active after successful payment
        if subscription.status == SubscriptionStatus.PAST_DUE:
            subscription.status = SubscriptionStatus.ACTIVE
            await db.commit()
            logger.info(f"Payment succeeded, subscription {subscription.id} now active")

    async def handle_payment_failed(
        self,
        db: AsyncSession,
        invoice: stripe.Invoice,
    ) -> None:
        """Handle invoice.payment_failed webhook event."""

        from app.core.config import settings
        from app.core.otel_metrics import STRIPE_METRICS

        if settings.OTEL_ENABLED and STRIPE_METRICS:
            STRIPE_METRICS["stripe_payment_failures_total"].add(1)

        if not invoice.subscription:
            return  # Not a subscription invoice

        result = await db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == invoice.subscription
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            return

        # Mark as past due
        subscription.status = SubscriptionStatus.PAST_DUE
        await db.commit()

        logger.warning(
            f"Payment failed for subscription {subscription.id}, "
            f"workspace {subscription.workspace_id}"
        )
        # TODO: Send notification to workspace owner

    async def handle_checkout_completed(
        self,
        db: AsyncSession,
        checkout_session: stripe.checkout.Session,
    ) -> None:
        """
        Handle checkout.session.completed webhook event.
        This fires when a user successfully completes payment through Checkout.
        """
        logger.info(f"Processing checkout.session.completed for {checkout_session.id}")
        logger.info(f"Checkout session metadata: {checkout_session.metadata}")

        # Get workspace_id from metadata
        workspace_id = checkout_session.metadata.get("workspace_id")
        if not workspace_id:
            logger.warning(f"Checkout session {checkout_session.id} without workspace_id in metadata")
            return

        # Get plan_id from metadata
        plan_id = checkout_session.metadata.get("plan_id")
        if not plan_id:
            logger.warning(f"Checkout session {checkout_session.id} without plan_id in metadata")
            return

        # Get the subscription that was created
        stripe_subscription_id = checkout_session.subscription
        if not stripe_subscription_id:
            logger.warning(f"Checkout session {checkout_session.id} without subscription")
            return

        # Get local subscription
        subscription = await self.get_workspace_subscription(db, workspace_id)
        if not subscription:
            logger.warning(f"No local subscription found for workspace {workspace_id}")
            return

        # Fetch full subscription details from Stripe
        from app.billing.services.stripe_service import stripe_service
        stripe_subscription = await stripe_service.get_subscription(stripe_subscription_id)
        if not stripe_subscription:
            logger.error(f"Failed to fetch Stripe subscription {stripe_subscription_id}")
            return

        # Update local subscription with Stripe details
        # Stripe sends lowercase status ("active"), convert to UPPERCASE for our enum
        subscription.stripe_subscription_id = stripe_subscription.id
        subscription.stripe_customer_id = stripe_subscription.customer

        # If checkout was paid, set subscription to ACTIVE immediately
        # (don't wait for delayed customer.subscription.updated webhook)
        logger.info(f"Checkout payment_status: {checkout_session.payment_status}, status: {checkout_session.status}")
        if checkout_session.payment_status == "paid":
            subscription.status = SubscriptionStatus.ACTIVE
            logger.info("Checkout paid - setting subscription to ACTIVE immediately")
        else:
            subscription.status = SubscriptionStatus(stripe_subscription.status.upper())
            logger.info(f"Checkout not paid yet - subscription status: {subscription.status}")

        # Handle current_period_start and current_period_end (may be None)
        if hasattr(stripe_subscription, 'current_period_start') and stripe_subscription.current_period_start:
            subscription.current_period_start = datetime.fromtimestamp(
                stripe_subscription.current_period_start, tz=timezone.utc
            )
        if hasattr(stripe_subscription, 'current_period_end') and stripe_subscription.current_period_end:
            subscription.current_period_end = datetime.fromtimestamp(
                stripe_subscription.current_period_end, tz=timezone.utc
            )

        subscription.plan_id = plan_id

        # Check if this is a service count update (not initial Pro subscription)
        is_service_update = checkout_session.metadata.get("service_count_update") == "true"
        old_subscription_id = checkout_session.metadata.get("old_subscription_id")

        logger.info(
            f"Checkout metadata check - is_service_update: {is_service_update}, "
            f"old_subscription_id: {old_subscription_id}, "
            f"metadata: {checkout_session.metadata}"
        )

        if is_service_update and old_subscription_id:
            # Calculate billable service count from new service count
            new_service_count = int(checkout_session.metadata.get("new_service_count", "0"))
            plan = await self.get_plan_by_id(db, plan_id)
            if plan:
                subscription.billable_service_count = max(0, new_service_count - plan.base_service_count)
                logger.info(
                    f"Updated billable service count to {subscription.billable_service_count} "
                    f"(total: {new_service_count}, base: {plan.base_service_count})"
                )

            # Clear any pending downgrade since we're creating a new subscription
            # (old subscription with schedule will be deleted below)
            if subscription.pending_billable_service_count is not None:
                logger.info(
                    f"Clearing pending downgrade (was scheduled for "
                    f"{subscription.pending_billable_service_count + (plan.base_service_count if plan else 5)} services)"
                )
                subscription.pending_billable_service_count = None
                subscription.pending_change_date = None
                subscription.subscription_schedule_id = None

            # IMPORTANT: Commit BEFORE deleting old subscription to avoid race condition.
            # The delete triggers a customer.subscription.deleted webhook. If the DB still
            # has the old stripe_subscription_id, that webhook handler would match and
            # incorrectly downgrade to Free.
            await db.commit()
            logger.info(
                f"Committed new subscription {subscription.stripe_subscription_id} "
                f"before canceling old subscription {old_subscription_id}"
            )

            # Now safe to cancel the old subscription
            logger.info(f"Service count update detected - canceling old subscription {old_subscription_id}")
            try:
                stripe.Subscription.delete(old_subscription_id)
                logger.info(f"Successfully canceled old subscription {old_subscription_id}")
            except stripe.error.StripeError as e:
                logger.error(f"Failed to cancel old subscription {old_subscription_id}: {e}")
                # Continue anyway - new subscription is already created
        else:
            await db.commit()
        logger.info(
            f"Successfully updated subscription for workspace {workspace_id}: "
            f"plan={subscription.plan_id}, stripe_sub={subscription.stripe_subscription_id}"
        )

    async def sync_subscription_from_stripe(
        self,
        db: AsyncSession,
        stripe_subscription_id: str,
    ) -> Optional[Subscription]:
        """
        Sync local subscription state from Stripe.

        Args:
            db: Database session
            stripe_subscription_id: Stripe subscription ID

        Returns:
            Updated Subscription or None
        """
        from app.core.config import settings

        stripe_sub = await stripe_service.get_subscription(stripe_subscription_id)
        if not stripe_sub:
            return None

        result = await db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_subscription_id
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            return None

        subscription.status = SubscriptionStatus(stripe_sub.status.upper())

        # Handle current_period_start and current_period_end (may be None)
        if hasattr(stripe_sub, 'current_period_start') and stripe_sub.current_period_start:
            subscription.current_period_start = datetime.fromtimestamp(
                stripe_sub.current_period_start, tz=timezone.utc
            )
        if hasattr(stripe_sub, 'current_period_end') and stripe_sub.current_period_end:
            subscription.current_period_end = datetime.fromtimestamp(
                stripe_sub.current_period_end, tz=timezone.utc
            )

        if stripe_sub.canceled_at:
            subscription.canceled_at = datetime.fromtimestamp(
                stripe_sub.canceled_at, tz=timezone.utc
            )

        # Sync billable service count from Stripe subscription items
        if hasattr(stripe_sub, 'items') and stripe_sub.items:
            additional_service_count = 0
            for item in stripe_sub.items.data:
                # Check if this item is for additional services
                if (settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID and
                    item.price.id == settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID):
                    additional_service_count = item.quantity
                    break

            # Update billable service count if it changed
            if subscription.billable_service_count != additional_service_count:
                logger.info(
                    f"Syncing billable_service_count from Stripe: "
                    f"{subscription.billable_service_count} -> {additional_service_count}"
                )
                subscription.billable_service_count = additional_service_count

        await db.commit()
        await db.refresh(subscription)

        logger.info(f"Synced subscription {subscription.id} from Stripe")
        return subscription

    async def count_active_subscriptions(self, db: AsyncSession) -> int:
        """
        Count active Stripe subscriptions for metrics.
        """
        from sqlalchemy import func

        result = await db.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.status == SubscriptionStatus.ACTIVE)
            .where(Subscription.stripe_subscription_id.isnot(None))
        )
        return result.scalar() or 0


# Singleton instance
subscription_service = SubscriptionService()
