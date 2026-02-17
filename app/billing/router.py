"""
Billing domain API routers for Subscription APIs.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google.service import AuthService
from app.billing.schemas import (  # Billing schemas
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
    UsageResponse,
)
from app.billing.services.stripe_service import stripe_service
from app.billing.services.subscription_service import subscription_service
from app.billing.services.service_downgrade import (
    downgrade_services,
    cancel_pending_downgrade,
    get_pending_changes,
)
from app.core.database import get_db
from app.models import Membership, PlanType, Role, User, Workspace
from app.workspace.client_workspace_services.limit_service import limit_service

logger = logging.getLogger(__name__)

auth_service = AuthService()


# ============================================================================
# Helper Functions
# ============================================================================


async def get_workspace_with_owner_check(
    workspace_id: str,
    current_user: User,
    db: AsyncSession,
    require_owner: bool = True,
) -> Workspace:
    """
    Get workspace and verify user has access (optionally require owner role).
    """
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()

    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

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


# ============================================================================
# Billing Router - Global Endpoints (Plans)
# ============================================================================

billing_router = APIRouter(prefix="/billing", tags=["billing"])


@billing_router.get("/plans", response_model=PlansListResponse)
async def list_plans(
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(default=True, description="Only show active plans"),
):
    """List all available billing plans."""
    plans = await subscription_service.get_all_plans(db, active_only=active_only)
    return PlansListResponse(
        plans=[PlanResponse.model_validate(plan) for plan in plans]
    )


@billing_router.get("/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get details of a specific plan."""
    plan = await subscription_service.get_plan_by_id(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return PlanResponse.model_validate(plan)


# ============================================================================
# Workspace Billing Router - Workspace-scoped Endpoints
# ============================================================================

workspace_billing_router = APIRouter(
    prefix="/workspaces/{workspace_id}/billing", tags=["billing"]
)


@workspace_billing_router.get("/subscription", response_model=SubscriptionResponse)
async def get_workspace_subscription(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current subscription for a workspace."""
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


@workspace_billing_router.post(
    "/subscribe/pro",
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
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=True
    )

    subscription = await subscription_service.get_workspace_subscription(
        db, workspace_id
    )
    if subscription and subscription.plan:
        # Use already-loaded plan from subscription (no extra query needed)
        plan = subscription.plan
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


@workspace_billing_router.post(
    "/subscription/cancel",
    response_model=SubscriptionResponse,
)
async def cancel_subscription(
    workspace_id: str,
    request: CancelSubscriptionRequest,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel the workspace subscription."""
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


@workspace_billing_router.post(
    "/portal",
    response_model=BillingPortalResponse,
)
async def create_billing_portal_session(
    workspace_id: str,
    request: BillingPortalRequest,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Customer Portal session for self-service billing."""
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


@workspace_billing_router.post(
    "/subscription/services/checkout",
    response_model=CheckoutSessionResponse,
)
async def create_service_update_checkout(
    workspace_id: str,
    request: UpdateServiceCountRequest,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create Stripe Checkout session for updating service count.

    This will:
    1. Calculate credit for unused days on current subscription
    2. Create checkout session with discounted price
    3. On success, old subscription is canceled and new one created
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=True
    )

    try:
        # Get success/cancel URLs using web app URL from settings
        from app.core.config import settings as app_settings
        current_url = app_settings.WEB_APP_URL
        success_url = f"{current_url}/settings/billing?success=true&service_update=true"
        cancel_url = f"{current_url}/settings/billing?canceled=true"

        checkout_url = await subscription_service.create_service_update_checkout(
            db=db,
            workspace_id=workspace_id,
            new_service_count=request.service_count,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return CheckoutSessionResponse(checkout_url=checkout_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@workspace_billing_router.get("/invoices", response_model=InvoicesListResponse)
async def list_invoices(
    workspace_id: str,
    limit: int = Query(default=10, ge=1, le=100),
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List invoices for a workspace."""
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


@workspace_billing_router.get("/usage", response_model=UsageResponse)
async def get_workspace_usage(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current usage stats for a workspace."""
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=False
    )

    try:
        usage_stats = await limit_service.get_usage_stats(db, workspace_id)
        return UsageResponse(**usage_stats)
    except Exception as e:
        logger.error(f"Failed to get usage stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get usage stats")


@workspace_billing_router.post("/subscription/sync")
async def sync_subscription(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync subscription state from Stripe."""
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


# ============================================================================
# Service Downgrade Endpoints
# ============================================================================


@workspace_billing_router.post("/services/downgrade")
async def schedule_service_downgrade(
    workspace_id: str,
    request: UpdateServiceCountRequest,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Schedule service downgrade - takes effect at next billing cycle.
    No immediate charge, no refund.
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=True
    )

    subscription = await subscription_service.get_workspace_subscription(
        db, workspace_id
    )
    if not subscription:
        raise HTTPException(
            status_code=404, detail="No subscription found for this workspace"
        )

    # Get plan for pricing and service count information
    plan = await subscription_service.get_plan_by_id(db, subscription.plan_id)
    if not plan:
        raise HTTPException(
            status_code=404, detail="Plan not found for this subscription"
        )

    # Check if it's actually a downgrade
    current_service_count = subscription.billable_service_count + plan.base_service_count
    if request.service_count >= current_service_count:
        raise HTTPException(
            status_code=400,
            detail=f"New service count must be less than current ({current_service_count}). Use service update endpoint for increases."
        )

    # Perform downgrade
    result = await downgrade_services(db, workspace_id, request.service_count, subscription, plan)

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("message", "Failed to schedule downgrade")
        )

    return result


@workspace_billing_router.delete("/services/downgrade")
async def cancel_service_downgrade(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel a scheduled service downgrade.
    Reverts to the current service count.
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=True
    )

    subscription = await subscription_service.get_workspace_subscription(
        db, workspace_id
    )
    if not subscription:
        raise HTTPException(
            status_code=404, detail="No subscription found for this workspace"
        )

    # Get plan for service count information
    plan = await subscription_service.get_plan_by_id(db, subscription.plan_id)
    if not plan:
        raise HTTPException(
            status_code=404, detail="Plan not found for this subscription"
        )

    # Cancel downgrade
    result = await cancel_pending_downgrade(db, subscription, plan)

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("message", "Failed to cancel downgrade")
        )

    return result


@workspace_billing_router.get("/services/pending")
async def get_pending_service_changes(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get any pending service count changes.
    """
    await get_workspace_with_owner_check(
        workspace_id, current_user, db, require_owner=False
    )

    subscription = await subscription_service.get_workspace_subscription(
        db, workspace_id
    )
    if not subscription:
        raise HTTPException(
            status_code=404, detail="No subscription found for this workspace"
        )

    # Get plan for service count information
    plan = await subscription_service.get_plan_by_id(db, subscription.plan_id)
    if not plan:
        raise HTTPException(
            status_code=404, detail="Plan not found for this subscription"
        )

    # Get pending changes
    pending = await get_pending_changes(subscription, plan)

    if not pending:
        return {
            "has_pending_changes": False,
            "current_service_count": subscription.billable_service_count + plan.base_service_count,
        }

    return {
        "has_pending_changes": True,
        "current_service_count": pending["current_service_count"],
        "new_service_count": pending["new_service_count"],
        "takes_effect": pending["takes_effect"].isoformat(),
        "type": pending["type"],
    }
