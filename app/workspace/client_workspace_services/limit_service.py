"""
Limit enforcement service for billing.

Enforces plan-based limits for services and RCA sessions.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Plan, PlanType, Service, Subscription
from app.utils.rate_limiter import is_byollm_workspace

logger = logging.getLogger(__name__)

# Default limits for Free plan (fallback if no subscription exists)
DEFAULT_FREE_SERVICE_LIMIT = 5
DEFAULT_FREE_RCA_DAILY_LIMIT = 10


class LimitService:
    """
    Enforces plan-based limits for workspaces.

    Handles:
    - Service count limits (Free: 5, Pro: unlimited)
    - RCA session daily limits (Free: 10, Pro: 100)
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

    async def get_rca_sessions_today(self, db: AsyncSession, workspace_id: str) -> int:
        """
        Get count of RCA sessions started today for a workspace.

        For VibeMonitor users: Uses RateLimitTracking table (only counts rate-limited requests)
        This ensures we don't count requests made with custom LLM providers.
        """
        from app.models import RateLimitTracking
        from app.utils.rate_limiter import ResourceType

        today = datetime.now(timezone.utc).date().isoformat()

        result = await db.execute(
            select(RateLimitTracking.count)
            .where(
                RateLimitTracking.workspace_id == workspace_id,
                RateLimitTracking.resource_type == ResourceType.RCA_REQUEST.value,
                RateLimitTracking.window_key == today,
            )
        )
        return result.scalar() or 0

    async def check_can_add_service(
        self, db: AsyncSession, workspace_id: str
    ) -> tuple[bool, dict]:
        """
        Check if workspace can add another service.

        Free plan: Hard limit of 5 services (cannot exceed)
        Pro plan: 5 base services + unlimited additional at $5/each

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
        Check if workspace can start another RCA session today.

        Free plan: 10 sessions/day
        Pro plan: 100 sessions/day

        Returns:
            Tuple of (can_start, details_dict)
        """
        subscription, plan = await self.get_workspace_plan(db, workspace_id)
        sessions_today = await self.get_rca_sessions_today(db, workspace_id)

        # Determine daily limit based on plan
        if plan:
            daily_limit = plan.rca_session_limit_daily
            is_paid = plan.plan_type == PlanType.PRO
            plan_name = plan.name
        else:
            daily_limit = DEFAULT_FREE_RCA_DAILY_LIMIT
            is_paid = False
            plan_name = "Free"

        can_start = sessions_today < daily_limit
        remaining = max(0, daily_limit - sessions_today)

        return can_start, {
            "sessions_today": sessions_today,
            "daily_limit": daily_limit,
            "remaining": remaining,
            "plan_name": plan_name,
            "is_paid": is_paid,
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
        Enforce RCA session limit - raises HTTPException 402 if exceeded.

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
                    "error": "Daily RCA session limit exceeded",
                    "limit_type": "rca_session",
                    "current": details["sessions_today"],
                    "limit": details["daily_limit"],
                    "upgrade_available": not details["is_paid"],
                    "message": (
                        f"You've used all {details['daily_limit']} RCA sessions for today. "
                        + (
                            "Upgrade to Pro for more daily sessions."
                            if not details["is_paid"]
                            else "Your daily limit resets at midnight UTC."
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

        # For BYOLLM users, RCA limits don't apply - don't count sessions
        if is_byollm:
            # Don't count jobs for BYOLLM users - they're unlimited
            rca_sessions_today = 0  # Not tracked for BYOLLM
            rca_daily_limit = -1  # -1 indicates unlimited
            rca_remaining = -1  # Unlimited remaining
            logger.info(
                f"BYOLLM workspace {workspace_id} - not counting RCA sessions "
                f"(unlimited with custom LLM)"
            )
        else:
            # Count actual Job records for rate-limited workspaces
            rca_sessions_today = await self.get_rca_sessions_today(db, workspace_id)
            # Plan details
            if plan:
                rca_daily_limit = plan.rca_session_limit_daily
            else:
                rca_daily_limit = DEFAULT_FREE_RCA_DAILY_LIMIT
            rca_remaining = max(0, rca_daily_limit - rca_sessions_today)
            logger.debug(
                f"VibeMonitor workspace {workspace_id} - RCA sessions: "
                f"{rca_sessions_today}/{rca_daily_limit}"
            )

        # Plan details
        if plan:
            plan_name = plan.name
            plan_type = plan.plan_type
            is_paid = plan.plan_type == PlanType.PRO
            # Both Free and Pro have base service limits (Free: 5, Pro: 5 base + $5/each additional)
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
            "can_add_service": service_count < service_limit,
            # RCA usage (unlimited if BYOLLM)
            "rca_sessions_today": rca_sessions_today,
            "rca_session_limit_daily": rca_daily_limit,  # -1 for BYOLLM (unlimited)
            "rca_sessions_remaining": rca_remaining,  # -1 for BYOLLM
            "can_start_rca": is_byollm or rca_sessions_today < rca_daily_limit,
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
