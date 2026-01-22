"""
Stripe webhook handler for processing billing events.
"""

import logging

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.services.stripe_service import stripe_service
from app.billing.services.subscription_service import subscription_service
from app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Stripe webhook events.

    Events handled:
    - customer.subscription.created
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.payment_succeeded
    - invoice.payment_failed
    - checkout.session.completed

    Stripe sends webhook events for subscription lifecycle changes.
    This endpoint verifies the webhook signature and routes events
    to the appropriate handler.

    For local testing, use:
    stripe listen --forward-to localhost:8000/api/v1/billing/webhooks/stripe
    """
    payload = await request.body()

    if not stripe_signature:
        logger.warning("Stripe webhook received without signature")
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    try:
        event = stripe_service.construct_webhook_event(payload, stripe_signature)
    except stripe.error.SignatureVerificationError as e:
        logger.warning(f"Invalid Stripe webhook signature: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except ValueError as e:
        logger.error(f"Webhook configuration error: {e}")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    event_type = event.type
    data = event.data.object

    logger.info(f"Received Stripe webhook: {event_type}")

    try:
        if event_type == "customer.subscription.created":
            await subscription_service.handle_subscription_created(db, data)

        elif event_type == "customer.subscription.updated":
            await subscription_service.handle_subscription_updated(db, data)

        elif event_type == "customer.subscription.deleted":
            await subscription_service.handle_subscription_deleted(db, data.id)

        elif event_type == "invoice.payment_succeeded":
            await subscription_service.handle_payment_succeeded(db, data)

        elif event_type == "invoice.payment_failed":
            await subscription_service.handle_payment_failed(db, data)

        elif event_type == "checkout.session.completed":
            # Checkout session completed - subscription created via checkout
            # The subscription.created event will also fire, so we just log here
            logger.info(
                f"Checkout session completed: {data.id}, customer: {data.customer}"
            )

        elif event_type == "customer.updated":
            # Customer updated (e.g., email changed)
            logger.info(f"Customer updated: {data.id}")

        else:
            # Log unhandled events but don't fail
            logger.debug(f"Unhandled Stripe event type: {event_type}")

    except Exception as e:
        logger.exception(f"Error handling Stripe webhook {event_type}: {e}")
        # Return 200 to acknowledge receipt, but log the error
        # Stripe will retry failed webhooks, so we want to avoid
        # infinite retry loops for bugs in our handler
        # In production, you might want to queue these for retry
        return {"status": "error", "message": str(e)}

    return {"status": "success", "event_type": event_type}
