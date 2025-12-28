"""
Billing domain router for subscription management APIs.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.services.google_auth_service import AuthService
from app.core.database import get_db
from app.models import (
    Membership,
    PlanType,
    Role,
    User,
    Workspace,
)
from app.billing.schemas import (
    BillingPortalRequest,
    BillingPortalResponse,
    CancelSubscriptionRequest,
    CheckoutSessionResponse,
    InvoiceResponse,
    InvoicesListResponse,
    PlanResponse,
    PlansListResponse,
    SubscribeToProRequest,
    SubscriptionResponse,
    UpdateServiceCountRequest,
)
from app.billing.services.subscription_service import subscription_service
from app.billing.services.stripe_service import stripe_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

auth_service = AuthService()


async def get_workspace_with_owner_check(
    workspace_id: str,
    current_user: User,
    db: AsyncSession,
    require_owner: bool = True,
) -> Workspace:
    """
    Get workspace and verify user has access (optionally require owner role).
    """
    # Get workspace
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()

    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check membership
    result = await db.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == current_user.id,
        )
    )
    membership = result.scalar_one_or_none()

    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    if require_owner and membership.role != Role.OWNER:
        raise HTTPException(
            status_code=403, detail="Only workspace owners can manage billing"
        )

    return workspace


# Plan endpoints


@router.get("/plans", response_model=PlansListResponse)
async def list_plans(
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(default=True, description="Only show active plans"),
):
    """
    List all available billing plans.

    Returns the Free and Pro plans with their pricing and limits.
    """
    plans = await subscription_service.get_all_plans(db, active_only=active_only)
    return PlansListResponse(
        plans=[PlanResponse.model_validate(plan) for plan in plans]
    )


@router.get("/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get details of a specific plan."""
    plan = await subscription_service.get_plan_by_id(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return PlanResponse.model_validate(plan)


# Subscription endpoints


@router.get(
    "/workspaces/{workspace_id}/subscription", response_model=SubscriptionResponse
)
async def get_workspace_subscription(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current subscription for a workspace.

    Any workspace member can view the subscription status.
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=False
    )

    subscription = await subscription_service.get_workspace_subscription(
        db, workspace_id
    )
    if not subscription:
        raise HTTPException(
            status_code=404, detail="Subscription not found for this workspace"
        )

    return SubscriptionResponse.model_validate(subscription)


@router.post(
    "/workspaces/{workspace_id}/subscribe/pro",
    response_model=CheckoutSessionResponse,
)
async def subscribe_to_pro(
    workspace_id: str,
    request: SubscribeToProRequest,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate subscription to the Pro plan.

    Creates a Stripe Checkout session and returns the URL.
    Only workspace owners can subscribe.

    The user should be redirected to the checkout_url to complete payment.
    After payment, they will be redirected to success_url or cancel_url.
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=True
    )

    # Check if already on Pro
    subscription = await subscription_service.get_workspace_subscription(
        db, workspace_id
    )
    if subscription and subscription.plan:
        plan = await subscription_service.get_plan_by_id(db, subscription.plan_id)
        if plan and plan.plan_type == PlanType.PRO:
            raise HTTPException(
                status_code=400, detail="Workspace is already on the Pro plan"
            )

    try:
        checkout_url = await subscription_service.subscribe_to_pro(
            db=db,
            workspace_id=workspace_id,
            owner_email=current_user.email,
            owner_name=current_user.name,
            success_url=request.success_url,
            cancel_url=request.cancel_url,
        )
        return CheckoutSessionResponse(checkout_url=checkout_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/workspaces/{workspace_id}/subscription/cancel",
    response_model=SubscriptionResponse,
)
async def cancel_subscription(
    workspace_id: str,
    request: CancelSubscriptionRequest,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel the workspace subscription.

    By default, cancels at the end of the billing period.
    Set immediate=true to cancel immediately with proration.

    Only workspace owners can cancel subscriptions.
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=True
    )

    try:
        subscription = await subscription_service.cancel_subscription(
            db=db,
            workspace_id=workspace_id,
            immediate=request.immediate,
        )
        return SubscriptionResponse.model_validate(subscription)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/workspaces/{workspace_id}/billing-portal",
    response_model=BillingPortalResponse,
)
async def create_billing_portal_session(
    workspace_id: str,
    request: BillingPortalRequest,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a Stripe Customer Portal session for self-service billing.

    The portal allows users to:
    - Update payment methods
    - View invoice history
    - Cancel subscription

    Only workspace owners can access the billing portal.
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=True
    )

    try:
        portal_url = await subscription_service.get_billing_portal_url(
            db=db,
            workspace_id=workspace_id,
            return_url=request.return_url,
        )
        return BillingPortalResponse(portal_url=portal_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put(
    "/workspaces/{workspace_id}/subscription/services",
    response_model=SubscriptionResponse,
)
async def update_service_count(
    workspace_id: str,
    request: UpdateServiceCountRequest,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update the service count for billing purposes.

    This endpoint is typically called automatically when services
    are added or removed from a workspace. It updates the billable
    service count and triggers prorated billing in Stripe.

    Only workspace owners can update service counts.
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=True
    )

    try:
        subscription = await subscription_service.update_service_count(
            db=db,
            workspace_id=workspace_id,
            new_service_count=request.service_count,
        )
        return SubscriptionResponse.model_validate(subscription)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workspaces/{workspace_id}/invoices", response_model=InvoicesListResponse)
async def list_invoices(
    workspace_id: str,
    limit: int = Query(default=10, ge=1, le=100),
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List invoices for a workspace.

    Returns the most recent invoices from Stripe.
    Only workspace owners can view invoices.
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=True
    )

    subscription = await subscription_service.get_workspace_subscription(
        db, workspace_id
    )
    if not subscription or not subscription.stripe_customer_id:
        return InvoicesListResponse(invoices=[])

    try:
        stripe_invoices = await stripe_service.list_invoices(
            customer_id=subscription.stripe_customer_id,
            limit=limit,
        )

        invoices = [
            InvoiceResponse(
                id=inv.id,
                amount_due=inv.amount_due,
                amount_paid=inv.amount_paid,
                currency=inv.currency,
                status=inv.status,
                created=datetime.fromtimestamp(inv.created, tz=timezone.utc),
                hosted_invoice_url=inv.hosted_invoice_url,
                invoice_pdf=inv.invoice_pdf,
            )
            for inv in stripe_invoices
        ]

        return InvoicesListResponse(invoices=invoices)
    except Exception as e:
        logger.error(f"Failed to fetch invoices: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch invoices")


@router.post("/workspaces/{workspace_id}/subscription/sync")
async def sync_subscription(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Sync subscription state from Stripe.

    Forces a refresh of the subscription data from Stripe.
    Useful if webhook events were missed.

    Only workspace owners can trigger a sync.
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=True
    )

    subscription = await subscription_service.get_workspace_subscription(
        db, workspace_id
    )
    if not subscription or not subscription.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No Stripe subscription to sync")

    updated = await subscription_service.sync_subscription_from_stripe(
        db, subscription.stripe_subscription_id
    )

    if not updated:
        raise HTTPException(
            status_code=500, detail="Failed to sync subscription from Stripe"
        )

    return SubscriptionResponse.model_validate(updated)
