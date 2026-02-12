"""
Limit enforcement service for billing.

Enforces plan-based limits for services and AIU (AI Unit) usage.
"""

import logging
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Plan, PlanType, Service, Subscription
from app.utils.rate_limiter import is_byollm_workspace, get_weekly_window_key

logger = logging.getLogger(__name__)

# Default limits for Free plan (fallback if no subscription exists)
DEFAULT_FREE_SERVICE_LIMIT = 2
DEFAULT_FREE_AIU_WEEKLY = 100_000  # 100K AIU per week


class LimitService:
    """
    Enforces plan-based limits for workspaces.

    Handles:
    - Service count limits (Free: 2, Pro: 3 base + $5/each additional)
    - Weekly AIU (AI Unit) limits (Free: 100K, Pro: 3M base + 500K per extra service)
    """

    async def get_workspace_plan(
        self, db: AsyncSession, workspace_id: str
    ) -> tuple[Optional[Subscription], Optional[Plan]]:
        """
        Get the subscription and plan for a workspace.

        Returns:
            Tuple of (Subscription, Plan) or (None, None) if no subscription
        """
        result = await db.execute(
            select(Subscription)
            .where(Subscription.workspace_id == workspace_id)
            .options()
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            return None, None

        # Get the plan
        plan_result = await db.execute(
            select(Plan).where(Plan.id == subscription.plan_id)
        )
        plan = plan_result.scalar_one_or_none()

        return subscription, plan

    async def get_service_count(self, db: AsyncSession, workspace_id: str) -> int:
        """Get current service count for a workspace."""
        result = await db.execute(
            select(func.count())
            .select_from(Service)
            .where(Service.workspace_id == workspace_id)
        )
        return result.scalar() or 0


    async def get_aiu_usage_this_week(self, db: AsyncSession, workspace_id: str) -> int:
        """
        Get AIU (AI Units) consumed this week for a workspace.

        Uses RateLimitTracking table with weekly window_key (e.g., '2026-W06').
        For VibeMonitor users only - BYOLLM users are unlimited.

        Returns:
            int: Total AIU consumed this week (0 if no usage or BYOLLM)
        """
        from app.models import RateLimitTracking
        from app.utils.rate_limiter import ResourceType

        week_key = get_weekly_window_key()

        result = await db.execute(
            select(RateLimitTracking.count)
            .where(
                RateLimitTracking.workspace_id == workspace_id,
                RateLimitTracking.resource_type == ResourceType.AIU_USAGE.value,
                RateLimitTracking.window_key == week_key,
            )
        )
        return result.scalar() or 0

    async def check_can_add_service(
        self, db: AsyncSession, workspace_id: str
    ) -> tuple[bool, dict]:
        """
        Check if workspace can add another service.

        Free plan: Hard limit of 2 services (cannot exceed)
        Pro plan: 3 base services + unlimited additional at $5/each

        Returns:
            Tuple of (can_add, details_dict)
        """
        subscription, plan = await self.get_workspace_plan(db, workspace_id)
        current_count = await self.get_service_count(db, workspace_id)

        # Determine limit based on plan
        if plan and plan.plan_type == PlanType.PRO:
            # Pro plan: can always add services (5 base + $5 per additional)
            return True, {
                "current_count": current_count,
                "limit": plan.base_service_count,  # Show base limit
                "plan_name": plan.name,
                "is_paid": True,
            }

        # Free plan or no subscription: enforce hard limit
        limit = plan.base_service_count if plan else DEFAULT_FREE_SERVICE_LIMIT
        can_add = current_count < limit

        return can_add, {
            "current_count": current_count,
            "limit": limit,
            "plan_name": plan.name if plan else "Free",
            "is_paid": False,
        }


    async def check_can_start_rca(
        self, db: AsyncSession, workspace_id: str
    ) -> tuple[bool, dict]:
        """
        Check if workspace can start an RCA (within weekly AIU limit).

        For BYOLLM workspaces: Always returns True (unlimited)
        For VibeMonitor workspaces: Checks weekly AIU usage vs limit

        Returns:
            Tuple of (can_start, details_dict)
        """
        subscription, plan = await self.get_workspace_plan(db, workspace_id)

        # Check if BYOLLM (unlimited AIU usage)
        try:
            is_byollm = await is_byollm_workspace(workspace_id, db)
        except Exception as e:
            logger.error(
                f"Error checking BYOLLM status for workspace {workspace_id}: {e}",
                exc_info=True
            )
            is_byollm = False

        # BYOLLM workspaces have unlimited AIU
        if is_byollm:
            return True, {
                "aiu_used_this_week": 0,
                "aiu_weekly_limit": -1,  # -1 indicates unlimited
                "aiu_remaining": -1,  # -1 indicates unlimited
                "plan_name": plan.name if plan else "Free",
                "is_paid": plan.plan_type == PlanType.PRO if plan else False,
                "is_byollm": True,
            }

        # Get current AIU usage this week
        aiu_used_this_week = await self.get_aiu_usage_this_week(db, workspace_id)

        # Calculate weekly AIU limit
        if plan:
            aiu_weekly_limit = plan.aiu_limit_weekly_base
            # Add per-service AIU for Pro plan
            if plan.plan_type == PlanType.PRO and subscription:
                billable_services = subscription.billable_service_count or 0
                aiu_weekly_limit += billable_services * plan.aiu_limit_weekly_per_service
        else:
            aiu_weekly_limit = DEFAULT_FREE_AIU_WEEKLY

        # Check if under limit
        can_start = aiu_used_this_week < aiu_weekly_limit

        # Calculate remaining AIU (never negative)
        aiu_remaining = max(0, aiu_weekly_limit - aiu_used_this_week)

        return can_start, {
            "aiu_used_this_week": aiu_used_this_week,
            "aiu_weekly_limit": aiu_weekly_limit,
            "aiu_remaining": aiu_remaining,
            "plan_name": plan.name if plan else "Free",
            "is_paid": plan.plan_type == PlanType.PRO if plan else False,
            "is_byollm": False,
        }

    async def enforce_service_limit(self, db: AsyncSession, workspace_id: str) -> None:
        """
        Enforce service limit - raises HTTPException 402 if exceeded.

        Args:
            db: Database session
            workspace_id: Workspace ID

        Raises:
            HTTPException: 402 if limit exceeded
        """
        can_add, details = await self.check_can_add_service(db, workspace_id)

        if not can_add:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "Service limit exceeded",
                    "limit_type": "service",
                    "current": details["current_count"],
                    "limit": details["limit"],
                    "upgrade_available": True,
                    "message": (
                        f"Your {details['plan_name']} plan allows {details['limit']} services. "
                        "Upgrade to Pro for unlimited services."
                    ),
                },
            )

    async def enforce_rca_limit(self, db: AsyncSession, workspace_id: str) -> None:
        """
        Enforce weekly AIU limit - raises HTTPException 402 if exceeded.

        Args:
            db: Database session
            workspace_id: Workspace ID

        Raises:
            HTTPException: 402 if limit exceeded
        """
        can_start, details = await self.check_can_start_rca(db, workspace_id)

        if not can_start:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "Weekly AIU limit exceeded",
                    "limit_type": "aiu_weekly",
                    "current": details["aiu_used_this_week"],
                    "limit": details["aiu_weekly_limit"],
                    "upgrade_available": not details["is_paid"],
                    "message": (
                        f"You've used all {details['aiu_weekly_limit']:,} AIU for this week. "
                        + (
                            "Upgrade to Pro for more AIU (3M base + 500K per extra service)."
                            if not details["is_paid"]
                            else "Your weekly limit resets every Monday."
                        )
                    ),
                },
            )

    async def get_usage_stats(self, db: AsyncSession, workspace_id: str) -> dict:
        """
        Get current usage stats for a workspace.

        Returns:
            Dict with service and RCA usage information
        """
        subscription, plan = await self.get_workspace_plan(db, workspace_id)
        service_count = await self.get_service_count(db, workspace_id)

        # Check if workspace uses BYOLLM (Bring Your Own LLM)
        try:
            is_byollm = await is_byollm_workspace(workspace_id, db)
        except Exception as e:
            # If BYOLLM check fails, default to not BYOLLM (apply rate limits)
            logger.error(
                f"Error checking BYOLLM status for workspace {workspace_id}: {e}",
                exc_info=True
            )
            is_byollm = False

        # For BYOLLM users, AIU limits don't apply - unlimited usage
        if is_byollm:
            # Don't count AIU for BYOLLM users - they're unlimited
            aiu_used_this_week = 0  # Not tracked for BYOLLM
            aiu_weekly_limit = -1  # -1 indicates unlimited
            aiu_remaining = -1  # Unlimited remaining
            logger.info(
                f"BYOLLM workspace {workspace_id} - not counting AIU usage "
                f"(unlimited with custom LLM)"
            )
        else:
            # Get AIU usage for rate-limited workspaces
            aiu_used_this_week = await self.get_aiu_usage_this_week(db, workspace_id)

            # Calculate weekly AIU limit
            if plan:
                aiu_weekly_limit = plan.aiu_limit_weekly_base
                # Add per-service AIU for Pro plan
                if plan.plan_type == PlanType.PRO and subscription:
                    billable_services = subscription.billable_service_count or 0
                    aiu_weekly_limit += billable_services * plan.aiu_limit_weekly_per_service
            else:
                aiu_weekly_limit = DEFAULT_FREE_AIU_WEEKLY

            aiu_remaining = max(0, aiu_weekly_limit - aiu_used_this_week)
            logger.debug(
                f"VibeMonitor workspace {workspace_id} - AIU usage: "
                f"{aiu_used_this_week:,}/{aiu_weekly_limit:,}"
            )

        # Plan details
        if plan:
            plan_name = plan.name
            plan_type = plan.plan_type
            is_paid = plan.plan_type == PlanType.PRO
            # For Pro users, effective limit = base + billable (paid additional services)
            # For Free users, limit = base only
            if is_paid and subscription:
                service_limit = plan.base_service_count + (subscription.billable_service_count or 0)
            else:
                service_limit = plan.base_service_count
        else:
            plan_name = "Free"
            plan_type = PlanType.FREE
            is_paid = False
            service_limit = DEFAULT_FREE_SERVICE_LIMIT

        # Calculate remaining
        services_remaining = max(0, service_limit - service_count)

        return {
            "plan_name": plan_name,
            "plan_type": plan_type.value,
            "is_paid": is_paid,
            "is_byollm": is_byollm,  # Add BYOLLM status
            # Service usage
            "service_count": service_count,
            "service_limit": service_limit,
            "services_remaining": services_remaining,
            "can_add_service": is_paid or service_count < service_limit,
            # AIU usage (unlimited if BYOLLM)
            "aiu_used_this_week": aiu_used_this_week,
            "aiu_weekly_limit": aiu_weekly_limit,  # -1 for BYOLLM (unlimited)
            "aiu_remaining": aiu_remaining,  # -1 for BYOLLM
            "can_use_aiu": is_byollm or aiu_used_this_week < aiu_weekly_limit,
            # Subscription info
            "subscription_status": (
                subscription.status.value if subscription else None
            ),
            "current_period_end": (
                subscription.current_period_end if subscription else None
            ),
        }


# Singleton instance
limit_service = LimitService()
