"""
Test suite for billing limit enforcement (VIB-291).
Tests LimitService, usage endpoints, and 402 error responses.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from fastapi import HTTPException

from app.workspace.client_workspace_services.limit_service import (
    LimitService,
    DEFAULT_FREE_SERVICE_LIMIT,
)
from app.billing.schemas import UsageResponse
from app.models import Plan, PlanType, Subscription, SubscriptionStatus


@pytest.fixture
def limit_service():
    """Create a LimitService instance."""
    return LimitService()


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def sample_free_plan():
    """Create a sample free plan."""
    plan = MagicMock(spec=Plan)
    plan.id = str(uuid.uuid4())
    plan.name = "Free"
    plan.plan_type = PlanType.FREE
    plan.base_service_count = 2
    plan.aiu_limit_weekly_base = 100_000  # 100K AIU/week
    plan.aiu_limit_weekly_per_service = 0  # No scaling
    plan.is_active = True
    return plan


@pytest.fixture
def sample_pro_plan():
    """Create a sample Pro plan."""
    plan = MagicMock(spec=Plan)
    plan.id = str(uuid.uuid4())
    plan.name = "Pro"
    plan.plan_type = PlanType.PRO
    plan.base_service_count = 3
    plan.aiu_limit_weekly_base = 3_000_000  # 3M AIU/week
    plan.aiu_limit_weekly_per_service = 500_000  # 500K per extra service
    plan.is_active = True
    return plan


@pytest.fixture
def sample_subscription(sample_free_plan):
    """Create a sample subscription."""
    subscription = MagicMock(spec=Subscription)
    subscription.id = str(uuid.uuid4())
    subscription.workspace_id = str(uuid.uuid4())
    subscription.plan_id = sample_free_plan.id
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_end = datetime.now(timezone.utc)
    return subscription


class TestLimitServiceGetWorkspacePlan:
    """Tests for get_workspace_plan."""

    @pytest.mark.asyncio
    async def test_no_subscription(self, limit_service, mock_db):
        """Should return None, None when no subscription exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        subscription, plan = await limit_service.get_workspace_plan(
            mock_db, "workspace-123"
        )

        assert subscription is None
        assert plan is None

    @pytest.mark.asyncio
    async def test_with_subscription(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Should return subscription and plan when they exist."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        mock_db.execute.side_effect = [sub_result, plan_result]

        subscription, plan = await limit_service.get_workspace_plan(
            mock_db, sample_subscription.workspace_id
        )

        assert subscription == sample_subscription
        assert plan == sample_free_plan


class TestLimitServiceCheckCanAddService:
    """Tests for check_can_add_service."""

    @pytest.mark.asyncio
    async def test_free_plan_under_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Free plan with services under limit can add more."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        count_result = MagicMock()
        count_result.scalar.return_value = 1  # Under limit of 2

        mock_db.execute.side_effect = [sub_result, plan_result, count_result]

        can_add, details = await limit_service.check_can_add_service(
            mock_db, sample_subscription.workspace_id
        )

        assert can_add is True
        assert details["current_count"] == 1
        assert details["limit"] == 2
        assert details["is_paid"] is False

    @pytest.mark.asyncio
    async def test_free_plan_at_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Free plan at limit cannot add more."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        count_result = MagicMock()
        count_result.scalar.return_value = 2  # At limit

        mock_db.execute.side_effect = [sub_result, plan_result, count_result]

        can_add, details = await limit_service.check_can_add_service(
            mock_db, sample_subscription.workspace_id
        )

        assert can_add is False
        assert details["current_count"] == 2
        assert details["limit"] == 2

    @pytest.mark.asyncio
    async def test_pro_plan_unlimited(
        self, limit_service, mock_db, sample_subscription, sample_pro_plan
    ):
        """Pro plan has unlimited services."""
        sample_subscription.plan_id = sample_pro_plan.id

        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_pro_plan

        count_result = MagicMock()
        count_result.scalar.return_value = 50  # Many services

        mock_db.execute.side_effect = [sub_result, plan_result, count_result]

        can_add, details = await limit_service.check_can_add_service(
            mock_db, sample_subscription.workspace_id
        )

        assert can_add is True
        assert details["limit"] == 3  # Base count (can exceed with $5/each additional)
        assert details["is_paid"] is True

    @pytest.mark.asyncio
    async def test_no_subscription_uses_defaults(self, limit_service, mock_db):
        """No subscription uses default free tier limits."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = None

        count_result = MagicMock()
        count_result.scalar.return_value = 1

        mock_db.execute.side_effect = [sub_result, count_result]

        can_add, details = await limit_service.check_can_add_service(
            mock_db, "workspace-123"
        )

        assert can_add is True
        assert details["limit"] == DEFAULT_FREE_SERVICE_LIMIT
        assert details["plan_name"] == "Free"


class TestLimitServiceCheckCanStartRca:
    """Tests for check_can_start_rca (now uses weekly AIU)."""

    @pytest.mark.asyncio
    async def test_free_plan_under_weekly_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Free plan under weekly limit can use AIU."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        aiu_count_result = MagicMock()
        aiu_count_result.scalar.return_value = 50_000  # Under limit of 100K

        mock_db.execute.side_effect = [sub_result, plan_result, aiu_count_result]

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False

            can_start, details = await limit_service.check_can_start_rca(
                mock_db, sample_subscription.workspace_id
            )

            assert can_start is True
            assert details["aiu_used_this_week"] == 50_000
            assert details["aiu_weekly_limit"] == 100_000
            assert details["aiu_remaining"] == 50_000

    @pytest.mark.asyncio
    async def test_free_plan_at_weekly_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Free plan at weekly limit cannot use more AIU."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        aiu_count_result = MagicMock()
        aiu_count_result.scalar.return_value = 100_000  # At limit

        mock_db.execute.side_effect = [sub_result, plan_result, aiu_count_result]

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False

            can_start, details = await limit_service.check_can_start_rca(
                mock_db, sample_subscription.workspace_id
            )

            assert can_start is False
            assert details["aiu_remaining"] == 0

    @pytest.mark.asyncio
    async def test_pro_plan_higher_limit(
        self, limit_service, mock_db, sample_subscription, sample_pro_plan
    ):
        """Pro plan has higher weekly limit."""
        sample_subscription.plan_id = sample_pro_plan.id
        sample_subscription.billable_service_count = 0  # No extra services

        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_pro_plan

        aiu_count_result = MagicMock()
        aiu_count_result.scalar.return_value = 1_500_000  # 1.5M used

        mock_db.execute.side_effect = [sub_result, plan_result, aiu_count_result]

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False

            can_start, details = await limit_service.check_can_start_rca(
                mock_db, sample_subscription.workspace_id
            )

            assert can_start is True
            assert details["aiu_weekly_limit"] == 3_000_000  # 3M base
            assert details["aiu_remaining"] == 1_500_000
            assert details["is_paid"] is True


class TestLimitServiceEnforceServiceLimit:
    """Tests for enforce_service_limit."""

    @pytest.mark.asyncio
    async def test_enforce_allows_when_under_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Should not raise when under limit."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        count_result = MagicMock()
        count_result.scalar.return_value = 1

        mock_db.execute.side_effect = [sub_result, plan_result, count_result]

        # Should not raise
        await limit_service.enforce_service_limit(
            mock_db, sample_subscription.workspace_id
        )
        assert True  # No exception raised

    @pytest.mark.asyncio
    async def test_enforce_raises_402_at_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Should raise 402 when at limit."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        count_result = MagicMock()
        count_result.scalar.return_value = 2  # At limit

        mock_db.execute.side_effect = [sub_result, plan_result, count_result]

        with pytest.raises(HTTPException) as exc_info:
            await limit_service.enforce_service_limit(
                mock_db, sample_subscription.workspace_id
            )

        assert exc_info.value.status_code == 402
        detail = exc_info.value.detail
        assert detail["error"] == "Service limit exceeded"
        assert detail["limit_type"] == "service"
        assert detail["current"] == 2
        assert detail["limit"] == 2
        assert detail["upgrade_available"] is True


class TestLimitServiceEnforceRcaLimit:
    """Tests for enforce_rca_limit (now enforces weekly AIU)."""

    @pytest.mark.asyncio
    async def test_enforce_allows_when_under_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Should not raise when under limit."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        aiu_count_result = MagicMock()
        aiu_count_result.scalar.return_value = 50_000

        mock_db.execute.side_effect = [sub_result, plan_result, aiu_count_result]

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False

            # Should not raise
            await limit_service.enforce_rca_limit(mock_db, sample_subscription.workspace_id)
            assert True  # No exception raised

    @pytest.mark.asyncio
    async def test_enforce_raises_402_at_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Should raise 402 when at weekly AIU limit."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        aiu_count_result = MagicMock()
        aiu_count_result.scalar.return_value = 100_000  # At limit

        mock_db.execute.side_effect = [sub_result, plan_result, aiu_count_result]

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False

            with pytest.raises(HTTPException) as exc_info:
                await limit_service.enforce_rca_limit(
                    mock_db, sample_subscription.workspace_id
                )

            assert exc_info.value.status_code == 402
            detail = exc_info.value.detail
            assert detail["error"] == "Weekly AIU limit exceeded"
            assert detail["limit_type"] == "aiu_weekly"
            assert detail["current"] == 100_000
            assert detail["limit"] == 100_000
            assert detail["upgrade_available"] is True

    @pytest.mark.asyncio
    async def test_pro_plan_no_upgrade_message(
        self, limit_service, mock_db, sample_subscription, sample_pro_plan
    ):
        """Pro plan at limit should not suggest upgrade."""
        sample_subscription.plan_id = sample_pro_plan.id
        sample_subscription.billable_service_count = 0

        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_pro_plan

        aiu_count_result = MagicMock()
        aiu_count_result.scalar.return_value = 3_000_000  # At Pro limit

        mock_db.execute.side_effect = [sub_result, plan_result, aiu_count_result]

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False

            with pytest.raises(HTTPException) as exc_info:
                await limit_service.enforce_rca_limit(
                    mock_db, sample_subscription.workspace_id
                )

            detail = exc_info.value.detail
            assert detail["upgrade_available"] is False
            assert "Monday" in detail["message"]  # Weekly reset


class TestLimitServiceGetUsageStats:
    """Tests for get_usage_stats."""

    @pytest.mark.asyncio
    async def test_free_plan_usage_stats(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Should return correct usage stats for free plan."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        service_count_result = MagicMock()
        service_count_result.scalar.return_value = 1

        aiu_count_result = MagicMock()
        aiu_count_result.scalar.return_value = 70_000  # 70K AIU used

        mock_db.execute.side_effect = [
            sub_result,
            plan_result,
            service_count_result,
            aiu_count_result,
        ]

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False

            stats = await limit_service.get_usage_stats(
                mock_db, sample_subscription.workspace_id
            )

            assert stats["plan_name"] == "Free"
            assert stats["plan_type"] == "FREE"
            assert stats["is_paid"] is False
            assert stats["service_count"] == 1
            assert stats["service_limit"] == 2
            assert stats["services_remaining"] == 1
            assert stats["can_add_service"] is True
            assert stats["aiu_used_this_week"] == 70_000
            assert stats["aiu_weekly_limit"] == 100_000
            assert stats["aiu_remaining"] == 30_000
            assert stats["can_use_aiu"] is True

    @pytest.mark.asyncio
    async def test_pro_plan_unlimited_services(
        self, limit_service, mock_db, sample_subscription, sample_pro_plan
    ):
        """Pro plan should show unlimited services."""
        sample_subscription.plan_id = sample_pro_plan.id
        sample_subscription.billable_service_count = 0  # No additional services yet

        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_pro_plan

        service_count_result = MagicMock()
        service_count_result.scalar.return_value = 3  # At base limit

        aiu_count_result = MagicMock()
        aiu_count_result.scalar.return_value = 1_500_000  # 1.5M AIU used

        mock_db.execute.side_effect = [
            sub_result,
            plan_result,
            service_count_result,
            aiu_count_result,
        ]

        with patch("app.workspace.client_workspace_services.limit_service.is_byollm_workspace", new_callable=AsyncMock) as mock_byollm:
            mock_byollm.return_value = False

            stats = await limit_service.get_usage_stats(
                mock_db, sample_subscription.workspace_id
            )

            assert stats["plan_name"] == "Pro"
            assert stats["is_paid"] is True
            assert stats["service_limit"] == 3  # Base count included in Pro
            assert stats["services_remaining"] == 0  # 3 - 3 = 0 (before paying $5/each)
            assert stats["can_add_service"] is True  # Can always add more
            assert stats["aiu_weekly_limit"] == 3_000_000  # 3M base
            assert stats["aiu_remaining"] == 1_500_000


class TestUsageResponseSchema:
    """Tests for UsageResponse schema."""

    def test_usage_response_valid(self):
        """UsageResponse should accept valid data."""
        response = UsageResponse(
            plan_name="Free",
            plan_type="free",
            is_paid=False,
            is_byollm=False,
            service_count=1,
            service_limit=2,
            services_remaining=1,
            can_add_service=True,
            aiu_used_this_week=50_000,
            aiu_weekly_limit=100_000,
            aiu_remaining=50_000,
            can_use_aiu=True,
        )
        assert response.plan_name == "Free"
        assert response.can_add_service is True
        assert response.aiu_weekly_limit == 100_000

    def test_usage_response_unlimited_services(self):
        """UsageResponse should handle Pro plan services."""
        response = UsageResponse(
            plan_name="Pro",
            plan_type="pro",
            is_paid=True,
            is_byollm=False,
            service_count=50,
            service_limit=3,  # Pro base count (can exceed with $5/each additional)
            services_remaining=0,  # max(0, 3-50) = 0 (paying for 47 additional services)
            can_add_service=True,
            aiu_used_this_week=1_500_000,
            aiu_weekly_limit=3_000_000,
            aiu_remaining=1_500_000,
            can_use_aiu=True,
        )
        assert response.service_limit == 3
        assert response.services_remaining == 0
        assert response.is_paid is True
        assert response.aiu_weekly_limit == 3_000_000
