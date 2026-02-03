"""
Billing domain schemas for Subscription APIs.

Includes schemas for plans, subscriptions, invoices, and usage tracking.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, computed_field

from app.models import PlanType, SubscriptionStatus


# ============================================================================
# Plan Schemas (VIB-290)
# ============================================================================


class PlanResponse(BaseModel):
    """Response schema for a billing plan."""

    id: str
    name: str
    plan_type: PlanType
    stripe_price_id: Optional[str] = None
    base_service_count: int
    base_price_cents: int
    additional_service_price_cents: int
    rca_session_limit_daily: int
    is_active: bool
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @property
    def base_price_dollars(self) -> float:
        """Base price in dollars."""
        return self.base_price_cents / 100

    @property
    def additional_service_price_dollars(self) -> float:
        """Additional service price in dollars."""
        return self.additional_service_price_cents / 100


class PlansListResponse(BaseModel):
    """Response schema for listing all plans."""

    plans: list[PlanResponse]


# ============================================================================
# Subscription Schemas (VIB-290)
# ============================================================================


class SubscriptionResponse(BaseModel):
    """Response schema for a subscription."""

    id: str
    workspace_id: str
    plan_id: str
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    status: SubscriptionStatus
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    billable_service_count: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Include plan details
    plan: Optional[PlanResponse] = None

    @computed_field
    @property
    def plan_name(self) -> Optional[str]:
        """Plan type for frontend compatibility (free/pro)."""
        return self.plan.plan_type.value if self.plan else None

    @computed_field
    @property
    def cancel_at_period_end(self) -> bool:
        """Whether subscription cancels at period end."""
        return self.canceled_at is not None and self.status == SubscriptionStatus.ACTIVE

    model_config = {"from_attributes": True}


class SubscriptionWithPlanResponse(BaseModel):
    """Subscription response with embedded plan details."""

    subscription: SubscriptionResponse
    plan: PlanResponse


# ============================================================================
# Billing Request Schemas (VIB-290)
# ============================================================================


class SubscribeToProRequest(BaseModel):
    """Request to subscribe a workspace to the Pro plan."""

    success_url: str = Field(
        ...,
        description="URL to redirect to after successful payment",
        examples=["https://app.vibemonitor.ai/settings/billing?success=true"],
    )
    cancel_url: str = Field(
        ...,
        description="URL to redirect to if user cancels checkout",
        examples=["https://app.vibemonitor.ai/settings/billing?canceled=true"],
    )


class CheckoutSessionResponse(BaseModel):
    """Response containing a Stripe Checkout session URL."""

    checkout_url: str = Field(
        ...,
        description="Stripe Checkout session URL to redirect the user to",
    )


class BillingPortalRequest(BaseModel):
    """Request to create a Stripe Customer Portal session."""

    return_url: str = Field(
        ...,
        description="URL to return to after the portal session",
        examples=["https://app.vibemonitor.ai/settings/billing"],
    )


class BillingPortalResponse(BaseModel):
    """Response containing a Stripe Customer Portal URL."""

    portal_url: str = Field(
        ...,
        description="Stripe Customer Portal URL to redirect the user to",
    )


class CancelSubscriptionRequest(BaseModel):
    """Request to cancel a subscription."""

    immediate: bool = Field(
        default=False,
        description="If true, cancel immediately. Otherwise, cancel at end of billing period.",
    )


class UpdateServiceCountRequest(BaseModel):
    """Request to update the service count for billing."""

    service_count: int = Field(
        ...,
        ge=0,
        description="Total number of services in the workspace",
    )


# ============================================================================
# Invoice Schemas (VIB-290)
# ============================================================================


class InvoiceResponse(BaseModel):
    """Response schema for a Stripe invoice."""

    id: str
    amount_due: int
    amount_paid: int
    currency: str
    status: str
    created: datetime
    hosted_invoice_url: Optional[str] = None
    invoice_pdf: Optional[str] = None


class InvoicesListResponse(BaseModel):
    """Response schema for listing invoices."""

    invoices: list[InvoiceResponse]


# ============================================================================
# Usage/Limit Schemas (VIB-290)
# ============================================================================


class UsageLimitsResponse(BaseModel):
    """Response schema for current usage limits."""

    plan_name: str
    plan_type: PlanType

    # Service limits
    base_service_count: int
    current_service_count: int
    billable_service_count: int

    # RCA limits
    daily_rca_limit: int
    daily_rca_used: int
    daily_rca_remaining: int

    # Billing info
    is_paid: bool
    next_billing_date: Optional[datetime] = None
    estimated_monthly_cost_cents: int

    @property
    def estimated_monthly_cost_dollars(self) -> float:
        """Estimated monthly cost in dollars."""
        return self.estimated_monthly_cost_cents / 100


class UsageResponse(BaseModel):
    """Current usage stats for a workspace."""

    plan_name: str
    plan_type: str  # "free" or "pro"
    is_paid: bool

    # Service usage (both Free and Pro have base limits: 5 services)
    service_count: int
    service_limit: int  # Free: hard limit, Pro: base count (can exceed with $5/each additional)
    services_remaining: int
    can_add_service: bool

    # RCA session usage
    rca_sessions_today: int
    rca_session_limit_daily: int
    rca_sessions_remaining: int
    can_start_rca: bool

    # Subscription info
    subscription_status: Optional[str] = None
    current_period_end: Optional[datetime] = None
