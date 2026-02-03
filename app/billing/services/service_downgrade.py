"""
Service Downgrade Implementation

Handles downgrading services without refund - changes take effect at next billing cycle.
"""
import logging
from typing import Optional

import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Subscription
from app.billing.services.stripe_service import stripe_service
from app.core.config import settings

logger = logging.getLogger(__name__)


async def downgrade_services(
    db: AsyncSession,
    workspace_id: str,
    new_service_count: int,
    subscription: Subscription,
) -> dict:
    """
    Downgrade services - takes effect at next billing cycle.
    No refund, no immediate charge.

    Uses Stripe SubscriptionSchedule to schedule the change.

    Args:
        db: Database session
        workspace_id: Workspace ID
        new_service_count: New total service count (including base 5)
        subscription: Current subscription

    Returns:
        dict with downgrade details
    """
    try:
        # Check if there's a Stripe subscription
        if not subscription.stripe_subscription_id:
            return {
                "success": False,
                "message": "No active Stripe subscription found. Upgrade to Pro first.",
            }

        # Calculate new billable service count (subtract base 5)
        new_billable_count = max(0, new_service_count - 5)

        # Get current subscription from Stripe
        stripe_sub = await stripe_service.get_subscription(
            subscription.stripe_subscription_id
        )
        if not stripe_sub:
            raise ValueError(f"Stripe subscription {subscription.stripe_subscription_id} not found")

        # Get the subscription items
        current_items = stripe_sub.get("items", {}).get("data", [])
        if not current_items:
            raise ValueError("No subscription items found")

        # Identify current items
        base_item = None
        current_billable_count = subscription.billable_service_count

        for item in current_items:
            # Safely get price ID from item (handle both dict and object formats)
            if isinstance(item, dict):
                price_id = item.get("price", {}).get("id")
            else:
                price_id = getattr(item.price, "id", None) if hasattr(item, "price") else None

            if price_id == settings.STRIPE_PRO_PLAN_PRICE_ID:
                base_item = item

        if not base_item:
            raise ValueError("Base Pro plan item not found in subscription")

        # Build Phase 1: Current state (until end of billing period)
        phase1_items = [{"price": settings.STRIPE_PRO_PLAN_PRICE_ID, "quantity": 1}]
        if current_billable_count > 0:
            phase1_items.append({
                "price": settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID,
                "quantity": current_billable_count,
            })

        # Build Phase 2: New state (starting next billing period)
        phase2_items = [{"price": settings.STRIPE_PRO_PLAN_PRICE_ID, "quantity": 1}]
        if new_billable_count > 0:
            phase2_items.append({
                "price": settings.STRIPE_ADDITIONAL_SERVICE_PRICE_ID,
                "quantity": new_billable_count,
            })

        # Get timestamp for when current billing period ends
        period_end_timestamp = int(subscription.current_period_end.timestamp())

        # Create subscription schedule with two phases
        # Phase 1: Keep current services until billing period ends
        # Phase 2: Apply new service count starting next billing period
        # NOTE: Using 'now' keyword for Phase 1 start (can't use timestamp for current phase)
        phases = [
            {
                "items": phase1_items,
                "start_date": "now",  # Anchor point for end_date
                "end_date": period_end_timestamp,
            },
            {
                "items": phase2_items,
                "start_date": period_end_timestamp,
                # No end_date - continues indefinitely
            },
        ]

        # ALWAYS check Stripe for the current active schedule (DB might be stale)
        existing_schedule_id = await stripe_service.get_subscription_schedule_for_subscription(
            subscription.stripe_subscription_id
        )

        if existing_schedule_id:
            logger.info(f"Found active schedule in Stripe: {existing_schedule_id}")
            # Update DB with current schedule ID
            if subscription.subscription_schedule_id != existing_schedule_id:
                logger.info(f"Updating DB schedule_id from {subscription.subscription_schedule_id} to {existing_schedule_id}")
                subscription.subscription_schedule_id = existing_schedule_id
                await db.commit()
        else:
            logger.info("No active schedule found in Stripe")

        # Update existing schedule or create new one
        if existing_schedule_id:
            try:
                # Update existing schedule with new phases
                schedule = await stripe_service.update_subscription_schedule(
                    existing_schedule_id,
                    phases=phases,
                )
                logger.info(f"Updated existing schedule {existing_schedule_id}")
            except Exception as e:
                logger.warning(f"Failed to update existing schedule: {e}. Releasing and creating new one...")
                # If update fails, release old schedule and create new one
                try:
                    await stripe_service.cancel_subscription_schedule(
                        existing_schedule_id
                    )
                    logger.info(f"Released old schedule {existing_schedule_id}")
                except Exception as release_error:
                    logger.warning(f"Failed to release schedule: {release_error}")
                # Create new schedule
                schedule = await stripe_service.create_subscription_schedule(
                    subscription.stripe_subscription_id,
                    phases=phases,
                )
        else:
            # No existing schedule, create new one
            logger.info("No existing schedule found, creating new one")
            schedule = await stripe_service.create_subscription_schedule(
                subscription.stripe_subscription_id,
                phases=phases,
            )

        # Store pending downgrade in database (don't update current count yet!)
        # Extract schedule ID - handle both dict and object formats
        schedule_id = schedule.get('id') if isinstance(schedule, dict) else schedule.id

        subscription.subscription_schedule_id = schedule_id
        subscription.pending_billable_service_count = new_billable_count
        subscription.pending_change_date = subscription.current_period_end
        await db.commit()
        await db.refresh(subscription)

        logger.info(
            f"Downgrade scheduled for subscription {subscription.id}: "
            f"current={subscription.billable_service_count + 5} → pending={new_service_count} services "
            f"(takes effect at {subscription.current_period_end}) "
            f"schedule_id={schedule_id}"
        )

        # Verify it was saved
        logger.info(f"Verified schedule_id in DB: {subscription.subscription_schedule_id}")

        # Calculate new price
        new_price = 30 + (new_billable_count * 5)  # $30 base + $5 per additional service

        return {
            "success": True,
            "type": "downgrade",
            "current_service_count": subscription.billable_service_count + 5,  # Keep current
            "new_service_count": new_service_count,  # What it will be
            "takes_effect": subscription.current_period_end.isoformat(),
            "next_billing_amount": new_price,
            "message": (
                f"Downgrade scheduled. Starting {subscription.current_period_end.strftime('%b %d, %Y')}, "
                f"you'll be charged ${new_price}/month for {new_service_count} services."
            ),
        }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error during downgrade: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to schedule downgrade. Please try again.",
        }
    except Exception as e:
        logger.error(f"Error during downgrade: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "An error occurred while scheduling the downgrade.",
        }


async def cancel_pending_downgrade(
    db: AsyncSession,
    subscription: Subscription,
) -> dict:
    """
    Cancel a pending downgrade by canceling the Stripe Subscription Schedule.

    Args:
        db: Database session
        subscription: Current subscription

    Returns:
        dict with cancellation details
    """
    try:
        # Check if there's a pending downgrade
        if subscription.pending_billable_service_count is None:
            return {
                "success": False,
                "message": "No pending downgrade found.",
            }

        if not subscription.subscription_schedule_id:
            return {
                "success": False,
                "message": "No subscription schedule found to cancel.",
            }

        # Cancel the subscription schedule in Stripe
        # This releases the subscription back to normal (no schedule)
        await stripe_service.cancel_subscription_schedule(
            subscription.subscription_schedule_id
        )

        current_service_count = subscription.billable_service_count + 5

        # Clear pending downgrade and schedule ID
        subscription.subscription_schedule_id = None
        subscription.pending_billable_service_count = None
        subscription.pending_change_date = None
        await db.commit()

        logger.info(
            f"Canceled pending downgrade for subscription {subscription.id}. "
            f"Keeping {current_service_count} services."
        )

        return {
            "success": True,
            "message": f"Downgrade canceled. You'll continue with {current_service_count} services.",
            "service_count": current_service_count,
        }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error canceling downgrade: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to cancel downgrade. Please try again.",
        }
    except Exception as e:
        logger.error(f"Error canceling downgrade: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "An error occurred while canceling the downgrade.",
        }


async def get_pending_changes(subscription: Subscription) -> Optional[dict]:
    """
    Check if there's a pending downgrade stored in the database.

    Args:
        subscription: Current subscription

    Returns:
        dict with pending change details or None
    """
    try:
        # Check if there's a pending downgrade
        if subscription.pending_billable_service_count is None:
            return None

        new_service_count = subscription.pending_billable_service_count + 5

        return {
            "type": "downgrade",
            "current_service_count": subscription.billable_service_count + 5,
            "new_service_count": new_service_count,
            "takes_effect": subscription.pending_change_date,
        }

    except Exception as e:
        logger.error(f"Error checking pending changes: {e}")
        return None
