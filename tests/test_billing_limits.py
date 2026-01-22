"""
Test suite for billing limit enforcement (VIB-291).
Tests LimitService, usage endpoints, and 402 error responses.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import HTTPException

from app.billing.services.limit_service import (
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
    plan.base_service_count = 5
    plan.rca_session_limit_daily = 10
    plan.is_active = True
    return plan


@pytest.fixture
def sample_pro_plan():
    """Create a sample Pro plan."""
    plan = MagicMock(spec=Plan)
    plan.id = str(uuid.uuid4())
    plan.name = "Pro"
    plan.plan_type = PlanType.PRO
    plan.base_service_count = 5
    plan.rca_session_limit_daily = 100
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
        count_result.scalar.return_value = 3  # Under limit of 5

        mock_db.execute.side_effect = [sub_result, plan_result, count_result]

        can_add, details = await limit_service.check_can_add_service(
            mock_db, sample_subscription.workspace_id
        )

        assert can_add is True
        assert details["current_count"] == 3
        assert details["limit"] == 5
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
        count_result.scalar.return_value = 5  # At limit

        mock_db.execute.side_effect = [sub_result, plan_result, count_result]

        can_add, details = await limit_service.check_can_add_service(
            mock_db, sample_subscription.workspace_id
        )

        assert can_add is False
        assert details["current_count"] == 5
        assert details["limit"] == 5

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
        assert details["limit"] is None  # Unlimited
        assert details["is_paid"] is True

    @pytest.mark.asyncio
    async def test_no_subscription_uses_defaults(self, limit_service, mock_db):
        """No subscription uses default free tier limits."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = None

        count_result = MagicMock()
        count_result.scalar.return_value = 4

        mock_db.execute.side_effect = [sub_result, count_result]

        can_add, details = await limit_service.check_can_add_service(
            mock_db, "workspace-123"
        )

        assert can_add is True
        assert details["limit"] == DEFAULT_FREE_SERVICE_LIMIT
        assert details["plan_name"] == "Free"


class TestLimitServiceCheckCanStartRca:
    """Tests for check_can_start_rca."""

    @pytest.mark.asyncio
    async def test_free_plan_under_daily_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Free plan under daily limit can start RCA."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        session_count_result = MagicMock()
        session_count_result.scalar.return_value = 5  # Under limit of 10

        mock_db.execute.side_effect = [sub_result, plan_result, session_count_result]

        can_start, details = await limit_service.check_can_start_rca(
            mock_db, sample_subscription.workspace_id
        )

        assert can_start is True
        assert details["sessions_today"] == 5
        assert details["daily_limit"] == 10
        assert details["remaining"] == 5

    @pytest.mark.asyncio
    async def test_free_plan_at_daily_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Free plan at daily limit cannot start RCA."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        session_count_result = MagicMock()
        session_count_result.scalar.return_value = 10  # At limit

        mock_db.execute.side_effect = [sub_result, plan_result, session_count_result]

        can_start, details = await limit_service.check_can_start_rca(
            mock_db, sample_subscription.workspace_id
        )

        assert can_start is False
        assert details["remaining"] == 0

    @pytest.mark.asyncio
    async def test_pro_plan_higher_limit(
        self, limit_service, mock_db, sample_subscription, sample_pro_plan
    ):
        """Pro plan has higher daily limit."""
        sample_subscription.plan_id = sample_pro_plan.id

        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_pro_plan

        session_count_result = MagicMock()
        session_count_result.scalar.return_value = 50

        mock_db.execute.side_effect = [sub_result, plan_result, session_count_result]

        can_start, details = await limit_service.check_can_start_rca(
            mock_db, sample_subscription.workspace_id
        )

        assert can_start is True
        assert details["daily_limit"] == 100
        assert details["remaining"] == 50
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
        count_result.scalar.return_value = 3

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
        count_result.scalar.return_value = 5  # At limit

        mock_db.execute.side_effect = [sub_result, plan_result, count_result]

        with pytest.raises(HTTPException) as exc_info:
            await limit_service.enforce_service_limit(
                mock_db, sample_subscription.workspace_id
            )

        assert exc_info.value.status_code == 402
        detail = exc_info.value.detail
        assert detail["error"] == "Service limit exceeded"
        assert detail["limit_type"] == "service"
        assert detail["current"] == 5
        assert detail["limit"] == 5
        assert detail["upgrade_available"] is True


class TestLimitServiceEnforceRcaLimit:
    """Tests for enforce_rca_limit."""

    @pytest.mark.asyncio
    async def test_enforce_allows_when_under_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Should not raise when under limit."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        session_count_result = MagicMock()
        session_count_result.scalar.return_value = 5

        mock_db.execute.side_effect = [sub_result, plan_result, session_count_result]

        # Should not raise
        await limit_service.enforce_rca_limit(mock_db, sample_subscription.workspace_id)
        assert True  # No exception raised

    @pytest.mark.asyncio
    async def test_enforce_raises_402_at_limit(
        self, limit_service, mock_db, sample_subscription, sample_free_plan
    ):
        """Should raise 402 when at daily limit."""
        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_free_plan

        session_count_result = MagicMock()
        session_count_result.scalar.return_value = 10  # At limit

        mock_db.execute.side_effect = [sub_result, plan_result, session_count_result]

        with pytest.raises(HTTPException) as exc_info:
            await limit_service.enforce_rca_limit(
                mock_db, sample_subscription.workspace_id
            )

        assert exc_info.value.status_code == 402
        detail = exc_info.value.detail
        assert detail["error"] == "Daily RCA session limit exceeded"
        assert detail["limit_type"] == "rca_session"
        assert detail["current"] == 10
        assert detail["limit"] == 10
        assert detail["upgrade_available"] is True

    @pytest.mark.asyncio
    async def test_pro_plan_no_upgrade_message(
        self, limit_service, mock_db, sample_subscription, sample_pro_plan
    ):
        """Pro plan at limit should not suggest upgrade."""
        sample_subscription.plan_id = sample_pro_plan.id

        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_pro_plan

        session_count_result = MagicMock()
        session_count_result.scalar.return_value = 100  # At Pro limit

        mock_db.execute.side_effect = [sub_result, plan_result, session_count_result]

        with pytest.raises(HTTPException) as exc_info:
            await limit_service.enforce_rca_limit(
                mock_db, sample_subscription.workspace_id
            )

        detail = exc_info.value.detail
        assert detail["upgrade_available"] is False
        assert "midnight UTC" in detail["message"]


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
        service_count_result.scalar.return_value = 3

        rca_count_result = MagicMock()
        rca_count_result.scalar.return_value = 7

        mock_db.execute.side_effect = [
            sub_result,
            plan_result,
            service_count_result,
            rca_count_result,
        ]

        stats = await limit_service.get_usage_stats(
            mock_db, sample_subscription.workspace_id
        )

        assert stats["plan_name"] == "Free"
        assert stats["plan_type"] == "free"
        assert stats["is_paid"] is False
        assert stats["service_count"] == 3
        assert stats["service_limit"] == 5
        assert stats["services_remaining"] == 2
        assert stats["can_add_service"] is True
        assert stats["rca_sessions_today"] == 7
        assert stats["rca_session_limit_daily"] == 10
        assert stats["rca_sessions_remaining"] == 3
        assert stats["can_start_rca"] is True

    @pytest.mark.asyncio
    async def test_pro_plan_unlimited_services(
        self, limit_service, mock_db, sample_subscription, sample_pro_plan
    ):
        """Pro plan should show unlimited services."""
        sample_subscription.plan_id = sample_pro_plan.id

        sub_result = MagicMock()
        sub_result.scalar_one_or_none.return_value = sample_subscription

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = sample_pro_plan

        service_count_result = MagicMock()
        service_count_result.scalar.return_value = 25

        rca_count_result = MagicMock()
        rca_count_result.scalar.return_value = 50

        mock_db.execute.side_effect = [
            sub_result,
            plan_result,
            service_count_result,
            rca_count_result,
        ]

        stats = await limit_service.get_usage_stats(
            mock_db, sample_subscription.workspace_id
        )

        assert stats["plan_name"] == "Pro"
        assert stats["is_paid"] is True
        assert stats["service_limit"] is None  # Unlimited
        assert stats["services_remaining"] is None
        assert stats["can_add_service"] is True
        assert stats["rca_session_limit_daily"] == 100
        assert stats["rca_sessions_remaining"] == 50


class TestUsageResponseSchema:
    """Tests for UsageResponse schema."""

    def test_usage_response_valid(self):
        """UsageResponse should accept valid data."""
        response = UsageResponse(
            plan_name="Free",
            plan_type="free",
            is_paid=False,
            service_count=3,
            service_limit=5,
            services_remaining=2,
            can_add_service=True,
            rca_sessions_today=5,
            rca_session_limit_daily=10,
            rca_sessions_remaining=5,
            can_start_rca=True,
        )
        assert response.plan_name == "Free"
        assert response.can_add_service is True

    def test_usage_response_unlimited_services(self):
        """UsageResponse should handle unlimited services (Pro)."""
        response = UsageResponse(
            plan_name="Pro",
            plan_type="pro",
            is_paid=True,
            service_count=50,
            service_limit=None,  # Unlimited
            services_remaining=None,
            can_add_service=True,
            rca_sessions_today=50,
            rca_session_limit_daily=100,
            rca_sessions_remaining=50,
            can_start_rca=True,
        )
        assert response.service_limit is None
        assert response.services_remaining is None
        assert response.is_paid is True
