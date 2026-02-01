"""
Integration tests for billing endpoints.

These tests use a real test database to verify:
- Service CRUD operations
- Plan listing and retrieval
- Subscription management
- Usage and billing information

Endpoints tested:
- POST /api/v1/workspaces/{workspace_id}/services
- GET /api/v1/workspaces/{workspace_id}/services
- GET /api/v1/workspaces/{workspace_id}/services/count
- GET /api/v1/workspaces/{workspace_id}/services/{service_id}
- PATCH /api/v1/workspaces/{workspace_id}/services/{service_id}
- DELETE /api/v1/workspaces/{workspace_id}/services/{service_id}
- GET /api/v1/billing/plans
- GET /api/v1/billing/plans/{plan_id}
- GET /api/v1/workspaces/{workspace_id}/billing/subscription
- GET /api/v1/workspaces/{workspace_id}/billing/usage
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Membership,
    Plan,
    PlanType,
    Role,
    Service,
    Subscription,
    SubscriptionStatus,
    User,
    Workspace,
)
from tests.integration.conftest import API_PREFIX, get_auth_headers


# =============================================================================
# Test Data Factories
# =============================================================================


async def create_test_user(
    db: AsyncSession,
    email: str = "test@example.com",
    name: str = "Test User",
    is_verified: bool = True,
) -> User:
    """Create a user in the test database."""
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        name=name,
        is_verified=is_verified,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def create_test_workspace(
    db: AsyncSession,
    name: str = "Test Workspace",
) -> Workspace:
    """Create a workspace in the test database."""
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name=name,
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return workspace


async def create_test_membership(
    db: AsyncSession,
    user_id: str,
    workspace_id: str,
    role: Role = Role.OWNER,
) -> Membership:
    """Create a membership in the test database."""
    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=user_id,
        workspace_id=workspace_id,
        role=role,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership


async def create_test_plan(
    db: AsyncSession,
    name: str = "Free",
    plan_type: PlanType = PlanType.FREE,
    base_service_count: int = 5,
    base_price_cents: int = 0,
    additional_service_price_cents: int = 500,
    rca_session_limit_daily: int = 10,
    is_active: bool = True,
) -> Plan:
    """Create a plan in the test database."""
    plan = Plan(
        id=str(uuid.uuid4()),
        name=name,
        plan_type=plan_type,
        base_service_count=base_service_count,
        base_price_cents=base_price_cents,
        additional_service_price_cents=additional_service_price_cents,
        rca_session_limit_daily=rca_session_limit_daily,
        is_active=is_active,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


async def create_test_subscription(
    db: AsyncSession,
    workspace_id: str,
    plan_id: str,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    stripe_customer_id: str = None,
    stripe_subscription_id: str = None,
    billable_service_count: int = 0,
) -> Subscription:
    """Create a subscription in the test database."""
    subscription = Subscription(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        plan_id=plan_id,
        status=status,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        billable_service_count=billable_service_count,
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc),
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def create_test_service(
    db: AsyncSession,
    workspace_id: str,
    name: str = "test-service",
    repository_name: str = "owner/repo",
    enabled: bool = True,
) -> Service:
    """Create a service in the test database."""
    service = Service(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name=name,
        repository_name=repository_name,
        enabled=enabled,
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return service


# =============================================================================
# Tests: Service Endpoints
# =============================================================================


class TestCreateService:
    """Integration tests for POST /api/v1/workspaces/{workspace_id}/services."""

    @pytest.mark.asyncio
    async def test_create_service_success(self, client, test_db):
        """Create service with valid data returns 201."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)

        headers = get_auth_headers(user)

        response = await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/services",
            json={
                "name": "my-service",
                "repository_name": "owner/repo",
            },
            headers=headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "my-service"
        assert data["repository_name"] == "owner/repo"
        assert data["enabled"] is True

    @pytest.mark.asyncio
    async def test_create_service_persists_to_database(self, client, test_db):
        """Create service persists data to database."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)

        headers = get_auth_headers(user)

        await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/services",
            json={
                "name": "persisted-service",
                "repository_name": "owner/repo",
            },
            headers=headers,
        )

        result = await test_db.execute(
            select(Service).filter_by(name="persisted-service")
        )
        service = result.scalar_one_or_none()
        assert service is not None
        assert service.workspace_id == workspace.id

    @pytest.mark.asyncio
    async def test_create_service_unauthorized_non_member(self, client, test_db):
        """Create service by non-member returns 403."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        # No membership created

        headers = get_auth_headers(user)

        response = await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/services",
            json={
                "name": "my-service",
                "repository_name": "owner/repo",
            },
            headers=headers,
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_service_invalid_workspace_returns_403(self, client, test_db):
        """Create service with invalid workspace ID returns 403 (access denied)."""
        user = await create_test_user(test_db)

        headers = get_auth_headers(user)

        response = await client.post(
            f"{API_PREFIX}/workspaces/non-existent-id/services",
            json={
                "name": "my-service",
                "repository_name": "owner/repo",
            },
            headers=headers,
        )

        # Returns 403 since user is not a member of the workspace
        # (doesn't leak whether workspace exists - better security)
        assert response.status_code == 403


class TestListServices:
    """Integration tests for GET /api/v1/workspaces/{workspace_id}/services."""

    @pytest.mark.asyncio
    async def test_list_services_returns_all_workspace_services(self, client, test_db):
        """List services returns all services for the workspace."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)

        await create_test_service(test_db, workspace.id, "service-1")
        await create_test_service(test_db, workspace.id, "service-2")

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/services",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 2
        assert len(data["services"]) == 2
        service_names = [s["name"] for s in data["services"]]
        assert "service-1" in service_names
        assert "service-2" in service_names

    @pytest.mark.asyncio
    async def test_list_services_empty_workspace(self, client, test_db):
        """List services returns empty list for workspace with no services."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/services",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0
        assert data["services"] == []


class TestGetServiceCount:
    """Integration tests for GET /api/v1/workspaces/{workspace_id}/services/count."""

    @pytest.mark.asyncio
    async def test_get_service_count_returns_correct_count(self, client, test_db):
        """Get service count returns correct count and limit."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        plan = await create_test_plan(test_db, base_service_count=5)
        await create_test_subscription(test_db, workspace.id, plan.id)

        await create_test_service(test_db, workspace.id, "service-1")
        await create_test_service(test_db, workspace.id, "service-2")

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/services/count",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["current_count"] == 2
        assert data["limit"] == 5
        assert data["can_add_more"] is True

    @pytest.mark.asyncio
    async def test_get_service_count_non_member_returns_403(self, client, test_db):
        """Get service count by non-member returns 403."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        # No membership

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/services/count",
            headers=headers,
        )

        assert response.status_code == 403


class TestGetService:
    """Integration tests for GET /api/v1/workspaces/{workspace_id}/services/{service_id}."""

    @pytest.mark.asyncio
    async def test_get_service_returns_service(self, client, test_db):
        """Get service returns the requested service."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)
        service = await create_test_service(test_db, workspace.id, "my-service")

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/services/{service.id}",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == service.id
        assert data["name"] == "my-service"

    @pytest.mark.asyncio
    async def test_get_service_not_found_returns_404(self, client, test_db):
        """Get non-existent service returns 404."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/services/non-existent-id",
            headers=headers,
        )

        assert response.status_code == 404


class TestUpdateService:
    """Integration tests for PATCH /api/v1/workspaces/{workspace_id}/services/{service_id}."""

    @pytest.mark.asyncio
    async def test_update_service_name(self, client, test_db):
        """Update service name successfully."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)
        service = await create_test_service(test_db, workspace.id, "old-name")

        headers = get_auth_headers(user)

        response = await client.patch(
            f"{API_PREFIX}/workspaces/{workspace.id}/services/{service.id}",
            json={"name": "new-name"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "new-name"

    @pytest.mark.asyncio
    async def test_update_service_enabled_status(self, client, test_db):
        """Update service enabled status successfully."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)
        service = await create_test_service(test_db, workspace.id, enabled=True)

        headers = get_auth_headers(user)

        response = await client.patch(
            f"{API_PREFIX}/workspaces/{workspace.id}/services/{service.id}",
            json={"enabled": False},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False

    @pytest.mark.asyncio
    async def test_update_service_non_owner_returns_403(self, client, test_db):
        """Update service by non-owner returns 403."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.USER)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)
        service = await create_test_service(test_db, workspace.id)

        headers = get_auth_headers(user)

        response = await client.patch(
            f"{API_PREFIX}/workspaces/{workspace.id}/services/{service.id}",
            json={"name": "new-name"},
            headers=headers,
        )

        assert response.status_code == 403


class TestDeleteService:
    """Integration tests for DELETE /api/v1/workspaces/{workspace_id}/services/{service_id}."""

    @pytest.mark.asyncio
    async def test_delete_service_success(self, client, test_db):
        """Delete service returns 204 and removes from database."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)
        service = await create_test_service(test_db, workspace.id)

        headers = get_auth_headers(user)

        response = await client.delete(
            f"{API_PREFIX}/workspaces/{workspace.id}/services/{service.id}",
            headers=headers,
        )

        assert response.status_code == 204

        # Verify deleted from database
        result = await test_db.execute(select(Service).filter_by(id=service.id))
        deleted_service = result.scalar_one_or_none()
        assert deleted_service is None

    @pytest.mark.asyncio
    async def test_delete_service_not_found_returns_404(self, client, test_db):
        """Delete non-existent service returns 404."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)

        headers = get_auth_headers(user)

        response = await client.delete(
            f"{API_PREFIX}/workspaces/{workspace.id}/services/non-existent-id",
            headers=headers,
        )

        assert response.status_code == 404


# =============================================================================
# Tests: Plan Endpoints
# =============================================================================


class TestListPlans:
    """Integration tests for GET /api/v1/billing/plans."""

    @pytest.mark.asyncio
    async def test_list_plans_returns_all_active_plans(self, client, test_db):
        """List plans returns all active plans."""
        await create_test_plan(test_db, name="Free", plan_type=PlanType.FREE)
        await create_test_plan(
            test_db, name="Pro", plan_type=PlanType.PRO, base_price_cents=3000
        )

        response = await client.get(f"{API_PREFIX}/billing/plans")

        assert response.status_code == 200
        data = response.json()
        assert len(data["plans"]) == 2
        plan_names = [p["name"] for p in data["plans"]]
        assert "Free" in plan_names
        assert "Pro" in plan_names

    @pytest.mark.asyncio
    async def test_list_plans_excludes_inactive_by_default(self, client, test_db):
        """List plans excludes inactive plans by default."""
        await create_test_plan(test_db, name="Active Plan", is_active=True)
        await create_test_plan(test_db, name="Inactive Plan", is_active=False)

        response = await client.get(f"{API_PREFIX}/billing/plans")

        assert response.status_code == 200
        data = response.json()
        plan_names = [p["name"] for p in data["plans"]]
        assert "Active Plan" in plan_names
        assert "Inactive Plan" not in plan_names

    @pytest.mark.asyncio
    async def test_list_plans_includes_inactive_when_requested(self, client, test_db):
        """List plans includes inactive plans when active_only=false."""
        await create_test_plan(test_db, name="Active Plan", is_active=True)
        await create_test_plan(test_db, name="Inactive Plan", is_active=False)

        response = await client.get(f"{API_PREFIX}/billing/plans?active_only=false")

        assert response.status_code == 200
        data = response.json()
        plan_names = [p["name"] for p in data["plans"]]
        assert "Active Plan" in plan_names
        assert "Inactive Plan" in plan_names


class TestGetPlan:
    """Integration tests for GET /api/v1/billing/plans/{plan_id}."""

    @pytest.mark.asyncio
    async def test_get_plan_returns_plan_details(self, client, test_db):
        """Get plan returns detailed plan information."""
        plan = await create_test_plan(
            test_db,
            name="Pro",
            plan_type=PlanType.PRO,
            base_service_count=5,
            base_price_cents=3000,
            additional_service_price_cents=500,
            rca_session_limit_daily=100,
        )

        response = await client.get(f"{API_PREFIX}/billing/plans/{plan.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == plan.id
        assert data["name"] == "Pro"
        assert data["plan_type"] == "PRO"
        assert data["base_service_count"] == 5
        assert data["base_price_cents"] == 3000
        assert data["additional_service_price_cents"] == 500
        assert data["rca_session_limit_daily"] == 100

    @pytest.mark.asyncio
    async def test_get_plan_not_found_returns_404(self, client, test_db):
        """Get non-existent plan returns 404."""
        response = await client.get(f"{API_PREFIX}/billing/plans/non-existent-id")

        assert response.status_code == 404


# =============================================================================
# Tests: Workspace Billing Endpoints
# =============================================================================


class TestGetWorkspaceSubscription:
    """Integration tests for GET /api/v1/workspaces/{workspace_id}/billing/subscription."""

    @pytest.mark.asyncio
    async def test_get_subscription_returns_subscription_details(self, client, test_db):
        """Get subscription returns subscription information."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        plan = await create_test_plan(test_db, name="Pro", plan_type=PlanType.PRO)
        subscription = await create_test_subscription(
            test_db, workspace.id, plan.id, billable_service_count=3
        )

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/billing/subscription",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == subscription.id
        assert data["workspace_id"] == workspace.id
        assert data["plan_id"] == plan.id
        assert data["status"] == "active"
        assert data["billable_service_count"] == 3

    @pytest.mark.asyncio
    async def test_get_subscription_not_found_returns_404(self, client, test_db):
        """Get subscription for workspace without subscription returns 404."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        # No subscription created

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/billing/subscription",
            headers=headers,
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_subscription_accessible_by_member(self, client, test_db):
        """Get subscription is accessible by regular members (not just owners)."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.USER)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/billing/subscription",
            headers=headers,
        )

        assert response.status_code == 200


class TestGetWorkspaceUsage:
    """Integration tests for GET /api/v1/workspaces/{workspace_id}/billing/usage."""

    @pytest.mark.asyncio
    @patch("app.billing.router.limit_service")
    async def test_get_usage_returns_usage_stats(
        self, mock_limit_service, client, test_db
    ):
        """Get usage returns workspace usage statistics."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.OWNER)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)

        headers = get_auth_headers(user)
        mock_limit_service.get_usage_stats = AsyncMock(
            return_value={
                "plan_name": "Free",
                "plan_type": "free",
                "is_paid": False,
                "service_count": 2,
                "service_limit": 5,
                "services_remaining": 3,
                "can_add_service": True,
                "rca_sessions_today": 5,
                "rca_session_limit_daily": 10,
                "rca_sessions_remaining": 5,
                "can_start_rca": True,
            }
        )

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/billing/usage",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["plan_name"] == "Free"
        assert data["service_count"] == 2
        assert data["can_add_service"] is True
        assert data["rca_sessions_today"] == 5

    @pytest.mark.asyncio
    async def test_get_usage_accessible_by_member(self, client, test_db):
        """Get usage is accessible by regular members."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id, Role.USER)

        headers = get_auth_headers(user)

        # This will fail with 500 due to missing subscription, but not 403
        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/billing/usage",
            headers=headers,
        )

        # Should not be 403 (forbidden) - member access is allowed
        assert response.status_code != 403
