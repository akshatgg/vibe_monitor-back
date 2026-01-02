"""
Unit tests for billing limit_service.py.
Tests limit enforcement logic, error messages, and usage calculations.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app.billing.services.limit_service import (
    DEFAULT_FREE_RCA_DAILY_LIMIT,
    DEFAULT_FREE_SERVICE_LIMIT,
    LimitService,
)
from app.models import Plan, PlanType, Subscription, SubscriptionStatus


class TestConstants:
    """Tests for default limit constants."""

    def test_default_free_service_limit(self):
        """Default free service limit should be 5."""
        assert DEFAULT_FREE_SERVICE_LIMIT == 5

    def test_default_free_rca_daily_limit(self):
        """Default free RCA daily limit should be 10."""
        assert DEFAULT_FREE_RCA_DAILY_LIMIT == 10


class TestLimitServiceCheckCanAddService:
    """Tests for LimitService.check_can_add_service method."""

    @pytest.fixture
    def limit_service(self):
        """Create a LimitService instance."""
        return LimitService()

    @pytest.fixture
    def mock_pro_plan(self):
        """Create a mock Pro plan."""
        plan = MagicMock(spec=Plan)
        plan.name = "Pro"
        plan.plan_type = PlanType.PRO
        plan.base_service_count = 10
        plan.rca_session_limit_daily = 100
        return plan

    @pytest.fixture
    def mock_free_plan(self):
        """Create a mock Free plan."""
        plan = MagicMock(spec=Plan)
        plan.name = "Free"
        plan.plan_type = PlanType.FREE
        plan.base_service_count = 5
        plan.rca_session_limit_daily = 10
        return plan

    @pytest.fixture
    def mock_subscription(self, mock_free_plan):
        """Create a mock subscription."""
        subscription = MagicMock(spec=Subscription)
        subscription.workspace_id = "ws-123"
        subscription.plan_id = "plan-123"
        subscription.status = SubscriptionStatus.ACTIVE
        return subscription

    @pytest.mark.asyncio
    async def test_pro_plan_unlimited_services(
        self, limit_service, mock_db, mock_pro_plan, mock_subscription
    ):
        """Pro plan should allow unlimited services."""
        # Mock get_workspace_plan to return Pro subscription
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_pro_plan)
        )
        limit_service.get_service_count = AsyncMock(return_value=50)

        can_add, details = await limit_service.check_can_add_service(mock_db, "ws-123")

        assert can_add is True
        assert details["limit"] is None  # Unlimited
        assert details["current_count"] == 50
        assert details["plan_name"] == "Pro"
        assert details["is_paid"] is True

    @pytest.mark.asyncio
    async def test_free_plan_under_limit(
        self, limit_service, mock_db, mock_free_plan, mock_subscription
    ):
        """Free plan should allow adding services when under limit."""
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_free_plan)
        )
        limit_service.get_service_count = AsyncMock(return_value=3)

        can_add, details = await limit_service.check_can_add_service(mock_db, "ws-123")

        assert can_add is True
        assert details["limit"] == 5
        assert details["current_count"] == 3
        assert details["plan_name"] == "Free"
        assert details["is_paid"] is False

    @pytest.mark.asyncio
    async def test_free_plan_at_limit(
        self, limit_service, mock_db, mock_free_plan, mock_subscription
    ):
        """Free plan should NOT allow adding services when at limit."""
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_free_plan)
        )
        limit_service.get_service_count = AsyncMock(return_value=5)

        can_add, details = await limit_service.check_can_add_service(mock_db, "ws-123")

        assert can_add is False
        assert details["limit"] == 5
        assert details["current_count"] == 5

    @pytest.mark.asyncio
    async def test_no_subscription_uses_defaults(self, limit_service, mock_db):
        """No subscription should use default free limits."""
        limit_service.get_workspace_plan = AsyncMock(return_value=(None, None))
        limit_service.get_service_count = AsyncMock(return_value=4)

        can_add, details = await limit_service.check_can_add_service(mock_db, "ws-123")

        assert can_add is True
        assert details["limit"] == DEFAULT_FREE_SERVICE_LIMIT
        assert details["plan_name"] == "Free"
        assert details["is_paid"] is False

    @pytest.mark.asyncio
    async def test_no_subscription_at_default_limit(self, limit_service, mock_db):
        """No subscription at default limit should not allow adding."""
        limit_service.get_workspace_plan = AsyncMock(return_value=(None, None))
        limit_service.get_service_count = AsyncMock(
            return_value=DEFAULT_FREE_SERVICE_LIMIT
        )

        can_add, details = await limit_service.check_can_add_service(mock_db, "ws-123")

        assert can_add is False
        assert details["limit"] == DEFAULT_FREE_SERVICE_LIMIT


class TestLimitServiceCheckCanStartRCA:
    """Tests for LimitService.check_can_start_rca method."""

    @pytest.fixture
    def limit_service(self):
        return LimitService()

    @pytest.fixture
    def mock_pro_plan(self):
        plan = MagicMock(spec=Plan)
        plan.name = "Pro"
        plan.plan_type = PlanType.PRO
        plan.rca_session_limit_daily = 100
        return plan

    @pytest.fixture
    def mock_free_plan(self):
        plan = MagicMock(spec=Plan)
        plan.name = "Free"
        plan.plan_type = PlanType.FREE
        plan.rca_session_limit_daily = 10
        return plan

    @pytest.fixture
    def mock_subscription(self):
        subscription = MagicMock(spec=Subscription)
        subscription.workspace_id = "ws-123"
        return subscription

    @pytest.mark.asyncio
    async def test_pro_plan_under_daily_limit(
        self, limit_service, mock_db, mock_pro_plan, mock_subscription
    ):
        """Pro plan should allow RCA when under daily limit."""
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_pro_plan)
        )
        limit_service.get_rca_sessions_today = AsyncMock(return_value=50)

        can_start, details = await limit_service.check_can_start_rca(mock_db, "ws-123")

        assert can_start is True
        assert details["daily_limit"] == 100
        assert details["sessions_today"] == 50
        assert details["remaining"] == 50
        assert details["is_paid"] is True

    @pytest.mark.asyncio
    async def test_pro_plan_at_daily_limit(
        self, limit_service, mock_db, mock_pro_plan, mock_subscription
    ):
        """Pro plan should NOT allow RCA when at daily limit."""
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_pro_plan)
        )
        limit_service.get_rca_sessions_today = AsyncMock(return_value=100)

        can_start, details = await limit_service.check_can_start_rca(mock_db, "ws-123")

        assert can_start is False
        assert details["remaining"] == 0
        assert details["is_paid"] is True

    @pytest.mark.asyncio
    async def test_free_plan_under_daily_limit(
        self, limit_service, mock_db, mock_free_plan, mock_subscription
    ):
        """Free plan should allow RCA when under daily limit."""
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_free_plan)
        )
        limit_service.get_rca_sessions_today = AsyncMock(return_value=5)

        can_start, details = await limit_service.check_can_start_rca(mock_db, "ws-123")

        assert can_start is True
        assert details["daily_limit"] == 10
        assert details["remaining"] == 5
        assert details["is_paid"] is False

    @pytest.mark.asyncio
    async def test_no_subscription_uses_defaults(self, limit_service, mock_db):
        """No subscription should use default free RCA limits."""
        limit_service.get_workspace_plan = AsyncMock(return_value=(None, None))
        limit_service.get_rca_sessions_today = AsyncMock(return_value=5)

        can_start, details = await limit_service.check_can_start_rca(mock_db, "ws-123")

        assert can_start is True
        assert details["daily_limit"] == DEFAULT_FREE_RCA_DAILY_LIMIT
        assert details["remaining"] == 5
        assert details["plan_name"] == "Free"

    @pytest.mark.asyncio
    async def test_remaining_never_negative(
        self, limit_service, mock_db, mock_free_plan, mock_subscription
    ):
        """Remaining should never be negative even if over limit."""
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_free_plan)
        )
        limit_service.get_rca_sessions_today = AsyncMock(return_value=15)  # Over limit

        can_start, details = await limit_service.check_can_start_rca(mock_db, "ws-123")

        assert can_start is False
        assert details["remaining"] == 0  # max(0, 10-15) = 0


class TestLimitServiceEnforceServiceLimit:
    """Tests for LimitService.enforce_service_limit method."""

    @pytest.fixture
    def limit_service(self):
        return LimitService()

    @pytest.mark.asyncio
    async def test_raises_402_when_limit_exceeded(self, limit_service, mock_db):
        """Should raise HTTPException 402 when service limit exceeded."""
        limit_service.check_can_add_service = AsyncMock(
            return_value=(
                False,
                {"current_count": 5, "limit": 5, "plan_name": "Free", "is_paid": False},
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await limit_service.enforce_service_limit(mock_db, "ws-123")

        assert exc_info.value.status_code == 402
        assert exc_info.value.detail["error"] == "Service limit exceeded"
        assert exc_info.value.detail["limit_type"] == "service"
        assert exc_info.value.detail["current"] == 5
        assert exc_info.value.detail["limit"] == 5
        assert exc_info.value.detail["upgrade_available"] is True
        assert "Upgrade to Pro" in exc_info.value.detail["message"]

    @pytest.mark.asyncio
    async def test_no_exception_when_under_limit(self, limit_service, mock_db):
        """Should not raise exception when under limit."""
        limit_service.check_can_add_service = AsyncMock(
            return_value=(
                True,
                {"current_count": 3, "limit": 5, "plan_name": "Free", "is_paid": False},
            )
        )

        # Should not raise
        await limit_service.enforce_service_limit(mock_db, "ws-123")

    @pytest.mark.asyncio
    async def test_error_message_includes_plan_name(self, limit_service, mock_db):
        """Error message should include the plan name."""
        limit_service.check_can_add_service = AsyncMock(
            return_value=(
                False,
                {
                    "current_count": 5,
                    "limit": 5,
                    "plan_name": "Starter",
                    "is_paid": False,
                },
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await limit_service.enforce_service_limit(mock_db, "ws-123")

        assert "Starter plan" in exc_info.value.detail["message"]


class TestLimitServiceEnforceRCALimit:
    """Tests for LimitService.enforce_rca_limit method."""

    @pytest.fixture
    def limit_service(self):
        return LimitService()

    @pytest.mark.asyncio
    async def test_raises_402_when_limit_exceeded_free(self, limit_service, mock_db):
        """Should raise HTTPException 402 with upgrade message for free plan."""
        limit_service.check_can_start_rca = AsyncMock(
            return_value=(
                False,
                {
                    "sessions_today": 10,
                    "daily_limit": 10,
                    "remaining": 0,
                    "plan_name": "Free",
                    "is_paid": False,
                },
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await limit_service.enforce_rca_limit(mock_db, "ws-123")

        assert exc_info.value.status_code == 402
        assert exc_info.value.detail["error"] == "Daily RCA session limit exceeded"
        assert exc_info.value.detail["limit_type"] == "rca_session"
        assert exc_info.value.detail["upgrade_available"] is True
        assert "Upgrade to Pro" in exc_info.value.detail["message"]

    @pytest.mark.asyncio
    async def test_raises_402_when_limit_exceeded_pro(self, limit_service, mock_db):
        """Should raise HTTPException 402 with reset message for pro plan."""
        limit_service.check_can_start_rca = AsyncMock(
            return_value=(
                False,
                {
                    "sessions_today": 100,
                    "daily_limit": 100,
                    "remaining": 0,
                    "plan_name": "Pro",
                    "is_paid": True,
                },
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await limit_service.enforce_rca_limit(mock_db, "ws-123")

        assert exc_info.value.status_code == 402
        assert exc_info.value.detail["upgrade_available"] is False  # Already on Pro
        assert "midnight UTC" in exc_info.value.detail["message"]

    @pytest.mark.asyncio
    async def test_no_exception_when_under_limit(self, limit_service, mock_db):
        """Should not raise exception when under limit."""
        limit_service.check_can_start_rca = AsyncMock(
            return_value=(
                True,
                {
                    "sessions_today": 5,
                    "daily_limit": 10,
                    "remaining": 5,
                    "plan_name": "Free",
                    "is_paid": False,
                },
            )
        )

        # Should not raise
        await limit_service.enforce_rca_limit(mock_db, "ws-123")


class TestLimitServiceGetUsageStats:
    """Tests for LimitService.get_usage_stats method."""

    @pytest.fixture
    def limit_service(self):
        return LimitService()

    @pytest.fixture
    def mock_pro_plan(self):
        plan = MagicMock(spec=Plan)
        plan.name = "Pro"
        plan.plan_type = PlanType.PRO
        plan.base_service_count = 10
        plan.rca_session_limit_daily = 100
        return plan

    @pytest.fixture
    def mock_subscription(self):
        subscription = MagicMock(spec=Subscription)
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.current_period_end = datetime(2024, 12, 31, tzinfo=timezone.utc)
        return subscription

    @pytest.mark.asyncio
    async def test_pro_plan_usage_stats(
        self, limit_service, mock_db, mock_pro_plan, mock_subscription
    ):
        """Pro plan usage stats should show unlimited services."""
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_pro_plan)
        )
        limit_service.get_service_count = AsyncMock(return_value=15)
        limit_service.get_rca_sessions_today = AsyncMock(return_value=25)

        stats = await limit_service.get_usage_stats(mock_db, "ws-123")

        assert stats["plan_name"] == "Pro"
        assert stats["plan_type"] == "pro"
        assert stats["is_paid"] is True
        assert stats["service_count"] == 15
        assert stats["service_limit"] is None  # Unlimited for Pro
        assert stats["services_remaining"] is None  # Unlimited
        assert stats["can_add_service"] is True
        assert stats["rca_sessions_today"] == 25
        assert stats["rca_session_limit_daily"] == 100
        assert stats["rca_sessions_remaining"] == 75
        assert stats["can_start_rca"] is True
        assert stats["subscription_status"] == "active"

    @pytest.mark.asyncio
    async def test_free_plan_usage_stats_no_subscription(self, limit_service, mock_db):
        """Free plan (no subscription) usage stats should use defaults."""
        limit_service.get_workspace_plan = AsyncMock(return_value=(None, None))
        limit_service.get_service_count = AsyncMock(return_value=3)
        limit_service.get_rca_sessions_today = AsyncMock(return_value=5)

        stats = await limit_service.get_usage_stats(mock_db, "ws-123")

        assert stats["plan_name"] == "Free"
        assert stats["plan_type"] == "free"
        assert stats["is_paid"] is False
        assert stats["service_limit"] == DEFAULT_FREE_SERVICE_LIMIT
        assert stats["services_remaining"] == 2  # 5 - 3
        assert stats["can_add_service"] is True
        assert stats["rca_session_limit_daily"] == DEFAULT_FREE_RCA_DAILY_LIMIT
        assert stats["rca_sessions_remaining"] == 5  # 10 - 5
        assert stats["can_start_rca"] is True
        assert stats["subscription_status"] is None
        assert stats["current_period_end"] is None

    @pytest.mark.asyncio
    async def test_at_limit_cannot_add(self, limit_service, mock_db):
        """When at limit, can_add_service should be False."""
        limit_service.get_workspace_plan = AsyncMock(return_value=(None, None))
        limit_service.get_service_count = AsyncMock(return_value=5)
        limit_service.get_rca_sessions_today = AsyncMock(return_value=0)

        stats = await limit_service.get_usage_stats(mock_db, "ws-123")

        assert stats["can_add_service"] is False
        assert stats["services_remaining"] == 0

    @pytest.mark.asyncio
    async def test_rca_at_limit_cannot_start(self, limit_service, mock_db):
        """When at RCA limit, can_start_rca should be False."""
        limit_service.get_workspace_plan = AsyncMock(return_value=(None, None))
        limit_service.get_service_count = AsyncMock(return_value=0)
        limit_service.get_rca_sessions_today = AsyncMock(
            return_value=DEFAULT_FREE_RCA_DAILY_LIMIT
        )

        stats = await limit_service.get_usage_stats(mock_db, "ws-123")

        assert stats["can_start_rca"] is False
        assert stats["rca_sessions_remaining"] == 0
