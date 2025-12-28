"""
Limit enforcement service for billing.

Enforces plan-based limits for services and RCA sessions.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Plan,
    PlanType,
    Service,
    Subscription,
    Job,
    JobStatus,
)


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

        Counts jobs created today for this workspace.
        """
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        result = await db.execute(
            select(func.count())
            .select_from(Job)
            .where(
                Job.vm_workspace_id == workspace_id,
                Job.created_at >= today_start,
                Job.status != JobStatus.FAILED,  # Don't count failed jobs
            )
        )
        return result.scalar() or 0

    async def check_can_add_service(
        self, db: AsyncSession, workspace_id: str
    ) -> tuple[bool, dict]:
        """
        Check if workspace can add another service.

        Free plan: Hard limit of 5 services
        Pro plan: No limit (tracks for billing)

        Returns:
            Tuple of (can_add, details_dict)
        """
        subscription, plan = await self.get_workspace_plan(db, workspace_id)
        current_count = await self.get_service_count(db, workspace_id)

        # Determine limit based on plan
        if plan and plan.plan_type == PlanType.PRO:
            # Pro plan: unlimited services
            return True, {
                "current_count": current_count,
                "limit": None,  # Unlimited
                "plan_name": plan.name,
                "is_paid": True,
            }

        # Free plan or no subscription: enforce limit
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
        rca_sessions_today = await self.get_rca_sessions_today(db, workspace_id)

        # Plan details
        if plan:
            plan_name = plan.name
            plan_type = plan.plan_type
            is_paid = plan.plan_type == PlanType.PRO
            service_limit = (
                None if plan.plan_type == PlanType.PRO else plan.base_service_count
            )
            rca_daily_limit = plan.rca_session_limit_daily
        else:
            plan_name = "Free"
            plan_type = PlanType.FREE
            is_paid = False
            service_limit = DEFAULT_FREE_SERVICE_LIMIT
            rca_daily_limit = DEFAULT_FREE_RCA_DAILY_LIMIT

        # Calculate remaining
        services_remaining = (
            None if service_limit is None else max(0, service_limit - service_count)
        )
        rca_remaining = max(0, rca_daily_limit - rca_sessions_today)

        return {
            "plan_name": plan_name,
            "plan_type": plan_type.value,
            "is_paid": is_paid,
            # Service usage
            "service_count": service_count,
            "service_limit": service_limit,
            "services_remaining": services_remaining,
            "can_add_service": (
                True if service_limit is None else service_count < service_limit
            ),
            # RCA usage
            "rca_sessions_today": rca_sessions_today,
            "rca_session_limit_daily": rca_daily_limit,
            "rca_sessions_remaining": rca_remaining,
            "can_start_rca": rca_sessions_today < rca_daily_limit,
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
