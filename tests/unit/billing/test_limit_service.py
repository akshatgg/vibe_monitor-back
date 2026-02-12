"""
Unit tests for billing limit_service.py.
Tests limit enforcement logic, error messages, and usage calculations.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.workspace.client_workspace_services.limit_service import (
    DEFAULT_FREE_AIU_WEEKLY,
    DEFAULT_FREE_SERVICE_LIMIT,
    LimitService,
)
from app.models import Plan, PlanType, Subscription, SubscriptionStatus


class TestConstants:
    """Tests for default limit constants."""

    def test_default_free_service_limit(self):
        """Default free service limit should be 2."""
        assert DEFAULT_FREE_SERVICE_LIMIT == 2

    def test_default_free_aiu_weekly(self):
        """Default free weekly AIU limit should be 100K."""
        assert DEFAULT_FREE_AIU_WEEKLY == 100_000


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
        plan.base_service_count = 3
        plan.aiu_limit_weekly_base = 3_000_000
        plan.aiu_limit_weekly_per_service = 500_000
        return plan

    @pytest.fixture
    def mock_free_plan(self):
        """Create a mock Free plan."""
        plan = MagicMock(spec=Plan)
        plan.name = "Free"
        plan.plan_type = PlanType.FREE
        plan.base_service_count = 2
        plan.aiu_limit_weekly_base = 100_000
        plan.aiu_limit_weekly_per_service = 0
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
        assert details["limit"] == 3  # Shows base count (not enforced, can exceed with $5/each)
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
        limit_service.get_service_count = AsyncMock(return_value=1)

        can_add, details = await limit_service.check_can_add_service(mock_db, "ws-123")

        assert can_add is True
        assert details["limit"] == 2
        assert details["current_count"] == 1
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
        limit_service.get_service_count = AsyncMock(return_value=2)

        can_add, details = await limit_service.check_can_add_service(mock_db, "ws-123")

        assert can_add is False
        assert details["limit"] == 2
        assert details["current_count"] == 2

    @pytest.mark.asyncio
    async def test_no_subscription_uses_defaults(self, limit_service, mock_db):
        """No subscription should use default free limits."""
        limit_service.get_workspace_plan = AsyncMock(return_value=(None, None))
        limit_service.get_service_count = AsyncMock(return_value=1)

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
    """Tests for LimitService.check_can_start_rca method (weekly AIU)."""

    @pytest.fixture
    def limit_service(self):
        return LimitService()

    @pytest.fixture
    def mock_pro_plan(self):
        plan = MagicMock(spec=Plan)
        plan.name = "Pro"
        plan.plan_type = PlanType.PRO
        plan.aiu_limit_weekly_base = 3_000_000
        plan.aiu_limit_weekly_per_service = 500_000
        return plan

    @pytest.fixture
    def mock_free_plan(self):
        plan = MagicMock(spec=Plan)
        plan.name = "Free"
        plan.plan_type = PlanType.FREE
        plan.aiu_limit_weekly_base = 100_000
        plan.aiu_limit_weekly_per_service = 0
        return plan

    @pytest.fixture
    def mock_subscription(self):
        subscription = MagicMock(spec=Subscription)
        subscription.workspace_id = "ws-123"
        subscription.billable_service_count = 0
        return subscription

    @pytest.mark.asyncio
    async def test_pro_plan_under_weekly_limit(
        self, limit_service, mock_db, mock_pro_plan, mock_subscription
    ):
        """Pro plan should allow AIU when under weekly limit."""
        mock_subscription.billable_service_count = 0
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_pro_plan)
        )
        limit_service.get_aiu_usage_this_week = AsyncMock(return_value=1_500_000)

        can_start, details = await limit_service.check_can_start_rca(mock_db, "ws-123")

        assert can_start is True
        assert details["aiu_weekly_limit"] == 3_000_000
        assert details["aiu_used_this_week"] == 1_500_000
        assert details["aiu_remaining"] == 1_500_000
        assert details["is_paid"] is True

    @pytest.mark.asyncio
    async def test_pro_plan_at_weekly_limit(
        self, limit_service, mock_db, mock_pro_plan, mock_subscription
    ):
        """Pro plan should NOT allow AIU when at weekly limit."""
        mock_subscription.billable_service_count = 0
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_pro_plan)
        )
        limit_service.get_aiu_usage_this_week = AsyncMock(return_value=3_000_000)

        can_start, details = await limit_service.check_can_start_rca(mock_db, "ws-123")

        assert can_start is False
        assert details["aiu_remaining"] == 0
        assert details["is_paid"] is True

    @pytest.mark.asyncio
    async def test_pro_plan_with_extra_services_aiu_calculation(
        self, limit_service, mock_db, mock_pro_plan, mock_subscription
    ):
        """Pro plan with extra services: verify AIU limit = base + (extra × per_service).

        Scenario: Pro user with 5 total services (3 base + 2 extra)
        Expected: 3M base + (2 × 500K) = 4M AIU/week
        """
        # User is paying for 2 additional services beyond the base 3
        mock_subscription.billable_service_count = 2

        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_pro_plan)
        )
        limit_service.get_aiu_usage_this_week = AsyncMock(return_value=1_500_000)

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False

            can_start, details = await limit_service.check_can_start_rca(mock_db, "ws-123")

            # Verify calculation: 3M + (2 × 500K) = 4M
            assert can_start is True
            assert details["aiu_weekly_limit"] == 4_000_000  # 3M base + 1M for 2 extra services
            assert details["aiu_used_this_week"] == 1_500_000
            assert details["aiu_remaining"] == 2_500_000  # 4M - 1.5M used
            assert details["is_paid"] is True

    @pytest.mark.asyncio
    async def test_free_plan_under_weekly_limit(
        self, limit_service, mock_db, mock_free_plan, mock_subscription
    ):
        """Free plan should allow AIU when under weekly limit."""
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_free_plan)
        )
        limit_service.get_aiu_usage_this_week = AsyncMock(return_value=50_000)

        can_start, details = await limit_service.check_can_start_rca(mock_db, "ws-123")

        assert can_start is True
        assert details["aiu_weekly_limit"] == 100_000
        assert details["aiu_remaining"] == 50_000
        assert details["is_paid"] is False

    @pytest.mark.asyncio
    async def test_no_subscription_uses_defaults(self, limit_service, mock_db):
        """No subscription should use default free AIU limits."""
        limit_service.get_workspace_plan = AsyncMock(return_value=(None, None))
        limit_service.get_aiu_usage_this_week = AsyncMock(return_value=50_000)

        can_start, details = await limit_service.check_can_start_rca(mock_db, "ws-123")

        assert can_start is True
        assert details["aiu_weekly_limit"] == DEFAULT_FREE_AIU_WEEKLY
        assert details["aiu_remaining"] == 50_000
        assert details["plan_name"] == "Free"

    @pytest.mark.asyncio
    async def test_remaining_never_negative(
        self, limit_service, mock_db, mock_free_plan, mock_subscription
    ):
        """Remaining should never be negative even if over limit."""
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_free_plan)
        )
        limit_service.get_aiu_usage_this_week = AsyncMock(return_value=150_000)  # Over limit

        can_start, details = await limit_service.check_can_start_rca(mock_db, "ws-123")

        assert can_start is False
        assert details["aiu_remaining"] == 0  # max(0, 100K-150K) = 0


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
                {"current_count": 2, "limit": 2, "plan_name": "Free", "is_paid": False},
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await limit_service.enforce_service_limit(mock_db, "ws-123")

        assert exc_info.value.status_code == 402
        assert exc_info.value.detail["error"] == "Service limit exceeded"
        assert exc_info.value.detail["limit_type"] == "service"
        assert exc_info.value.detail["current"] == 2
        assert exc_info.value.detail["limit"] == 2
        assert exc_info.value.detail["upgrade_available"] is True
        assert "Upgrade to Pro" in exc_info.value.detail["message"]

    @pytest.mark.asyncio
    async def test_no_exception_when_under_limit(self, limit_service, mock_db):
        """Should not raise exception when under limit."""
        limit_service.check_can_add_service = AsyncMock(
            return_value=(
                True,
                {"current_count": 1, "limit": 2, "plan_name": "Free", "is_paid": False},
            )
        )

        # Should not raise
        await limit_service.enforce_service_limit(mock_db, "ws-123")
        assert True  # No exception raised

    @pytest.mark.asyncio
    async def test_error_message_includes_plan_name(self, limit_service, mock_db):
        """Error message should include the plan name."""
        limit_service.check_can_add_service = AsyncMock(
            return_value=(
                False,
                {
                    "current_count": 2,
                    "limit": 2,
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
                    "aiu_used_this_week": 100_000,
                    "aiu_weekly_limit": 100_000,
                    "aiu_remaining": 0,
                    "plan_name": "Free",
                    "is_paid": False,
                },
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await limit_service.enforce_rca_limit(mock_db, "ws-123")

        assert exc_info.value.status_code == 402
        assert exc_info.value.detail["error"] == "Weekly AIU limit exceeded"
        assert exc_info.value.detail["limit_type"] == "aiu_weekly"
        assert exc_info.value.detail["upgrade_available"] is True
        assert "Upgrade to Pro" in exc_info.value.detail["message"]

    @pytest.mark.asyncio
    async def test_raises_402_when_limit_exceeded_pro(self, limit_service, mock_db):
        """Should raise HTTPException 402 with reset message for pro plan."""
        limit_service.check_can_start_rca = AsyncMock(
            return_value=(
                False,
                {
                    "aiu_used_this_week": 3_000_000,
                    "aiu_weekly_limit": 3_000_000,
                    "aiu_remaining": 0,
                    "plan_name": "Pro",
                    "is_paid": True,
                },
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await limit_service.enforce_rca_limit(mock_db, "ws-123")

        assert exc_info.value.status_code == 402
        assert exc_info.value.detail["upgrade_available"] is False  # Already on Pro
        assert "Monday" in exc_info.value.detail["message"]  # Weekly reset

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
        assert True  # No exception raised


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
        plan.base_service_count = 3
        plan.aiu_limit_weekly_base = 3_000_000
        plan.aiu_limit_weekly_per_service = 500_000
        return plan

    @pytest.fixture
    def mock_subscription(self):
        subscription = MagicMock(spec=Subscription)
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.current_period_end = datetime(2024, 12, 31, tzinfo=timezone.utc)
        subscription.billable_service_count = 0  # No additional services
        return subscription

    @pytest.mark.asyncio
    async def test_pro_plan_usage_stats(
        self, limit_service, mock_db, mock_pro_plan, mock_subscription
    ):
        """Pro plan usage stats should show base service count for reference."""
        limit_service.get_workspace_plan = AsyncMock(
            return_value=(mock_subscription, mock_pro_plan)
        )
        limit_service.get_service_count = AsyncMock(return_value=2)  # Under base (not paying extra yet)
        limit_service.get_aiu_usage_this_week = AsyncMock(return_value=1_500_000)

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False
            stats = await limit_service.get_usage_stats(mock_db, "ws-123")

        assert stats["plan_name"] == "Pro"
        assert stats["plan_type"] == "PRO"
        assert stats["is_paid"] is True
        assert stats["service_count"] == 2
        assert stats["service_limit"] == 3  # Base count included in Pro plan
        assert stats["services_remaining"] == 1  # 3 - 2 = 1 (services before paying $5/each)
        assert stats["can_add_service"] is True  # Can always add (unlimited with payment)
        assert stats["aiu_used_this_week"] == 1_500_000
        assert stats["aiu_weekly_limit"] == 3_000_000
        assert stats["aiu_remaining"] == 1_500_000
        assert stats["can_use_aiu"] is True
        assert stats["subscription_status"] == "ACTIVE"

    @pytest.mark.asyncio
    async def test_free_plan_usage_stats_no_subscription(self, limit_service, mock_db):
        """Free plan (no subscription) usage stats should use defaults."""
        limit_service.get_workspace_plan = AsyncMock(return_value=(None, None))
        limit_service.get_service_count = AsyncMock(return_value=1)
        limit_service.get_aiu_usage_this_week = AsyncMock(return_value=50_000)

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False
            stats = await limit_service.get_usage_stats(mock_db, "ws-123")

        assert stats["plan_name"] == "Free"
        assert stats["plan_type"] == "FREE"
        assert stats["is_paid"] is False
        assert stats["service_limit"] == DEFAULT_FREE_SERVICE_LIMIT
        assert stats["services_remaining"] == 1  # 2 - 1
        assert stats["can_add_service"] is True
        assert stats["aiu_weekly_limit"] == DEFAULT_FREE_AIU_WEEKLY
        assert stats["aiu_remaining"] == 50_000
        assert stats["can_use_aiu"] is True
        assert stats["subscription_status"] is None
        assert stats["current_period_end"] is None

    @pytest.mark.asyncio
    async def test_at_limit_cannot_add(self, limit_service, mock_db):
        """When at limit, can_add_service should be False."""
        limit_service.get_workspace_plan = AsyncMock(return_value=(None, None))
        limit_service.get_service_count = AsyncMock(return_value=2)
        limit_service.get_aiu_usage_this_week = AsyncMock(return_value=0)

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False
            stats = await limit_service.get_usage_stats(mock_db, "ws-123")

        assert stats["can_add_service"] is False
        assert stats["services_remaining"] == 0

    @pytest.mark.asyncio
    async def test_rca_at_limit_cannot_start(self, limit_service, mock_db):
        """When at AIU limit, can_use_aiu should be False."""
        limit_service.get_workspace_plan = AsyncMock(return_value=(None, None))
        limit_service.get_service_count = AsyncMock(return_value=0)
        limit_service.get_aiu_usage_this_week = AsyncMock(
            return_value=DEFAULT_FREE_AIU_WEEKLY
        )

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False
            stats = await limit_service.get_usage_stats(mock_db, "ws-123")

        assert stats["can_use_aiu"] is False
        assert stats["aiu_remaining"] == 0
