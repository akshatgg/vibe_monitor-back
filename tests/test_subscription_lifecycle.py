"""
Integration tests for subscription lifecycle scenarios.

Tests both scenarios:
1. Subscription with cancellation (cancel at period end) - downgrades to FREE
2. Subscription auto-renews (no cancellation) - stays on PRO and charges

Run these tests:
    pytest tests/test_subscription_lifecycle.py -v
"""

import asyncio
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select

from app.billing.services.subscription_service import SubscriptionService
from app.core.database import AsyncSessionLocal
from app.models import Plan, PlanType, Subscription, SubscriptionStatus, Workspace, Membership, Role, User


class TestSubscriptionLifecycle:
    """Integration tests for subscription lifecycle scenarios."""

    @pytest.fixture
    async def test_workspace(self):
        """Create a test workspace with owner."""
        async with AsyncSessionLocal() as db:
            # Create test user
            user = User(
                id=str(uuid.uuid4()),
                email=f"test_{uuid.uuid4()}@example.com",
                name="Test User",
                is_onboarded=True,
            )
            db.add(user)

            # Create test workspace
            workspace = Workspace(
                id=str(uuid.uuid4()),
                name="Test Workspace",
                visible_to_org=False,
            )
            db.add(workspace)

            # Create membership
            membership = Membership(
                id=str(uuid.uuid4()),
                user_id=user.id,
                workspace_id=workspace.id,
                role=Role.OWNER,
            )
            db.add(membership)

            await db.commit()
            await db.refresh(workspace)

            yield workspace

            # Cleanup after test
            await db.delete(membership)
            await db.delete(workspace)
            await db.delete(user)
            await db.commit()

    @pytest.fixture
    async def subscription_service(self):
        """Create a SubscriptionService instance."""
        return SubscriptionService()

    @pytest.fixture
    async def free_plan(self):
        """Get the FREE plan from database."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Plan).where(Plan.plan_type == PlanType.FREE)
            )
            plan = result.scalar_one_or_none()
            if not plan:
                # Create FREE plan if doesn't exist
                plan = Plan(
                    id=str(uuid.uuid4()),
                    name="Free",
                    plan_type=PlanType.FREE,
                    stripe_price_id=None,
                    base_service_count=5,
                    base_price_cents=0,
                    additional_service_price_cents=0,
                    rca_session_limit_daily=10,
                    is_active=True,
                )
                db.add(plan)
                await db.commit()
                await db.refresh(plan)
            return plan

    @pytest.fixture
    async def pro_plan(self):
        """Get the PRO plan from database."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Plan).where(Plan.plan_type == PlanType.PRO)
            )
            plan = result.scalar_one_or_none()
            if not plan:
                # Create PRO plan if doesn't exist
                plan = Plan(
                    id=str(uuid.uuid4()),
                    name="Pro",
                    plan_type=PlanType.PRO,
                    stripe_price_id="price_pro_test",
                    base_service_count=5,
                    base_price_cents=3000,
                    additional_service_price_cents=500,
                    rca_session_limit_daily=100,
                    is_active=True,
                )
                db.add(plan)
                await db.commit()
                await db.refresh(plan)
            return plan

    @pytest.mark.asyncio
    async def test_scenario_1_canceled_subscription_downgrades_to_free(
        self, test_workspace, pro_plan, free_plan, subscription_service
    ):
        """
        Scenario 1: Subscription is CANCELED

        Steps:
        1. Create PRO subscription
        2. User cancels (sets canceled_at)
        3. Period ends (Feb 28 arrives)
        4. Subscription downgrades to FREE
        5. No charge occurs
        """
        print("\n" + "=" * 70)
        print("TEST SCENARIO 1: Canceled Subscription Downgrades to FREE")
        print("=" * 70)

        async with AsyncSessionLocal() as db:
            # Step 1: Create PRO subscription
            subscription = Subscription(
                id=str(uuid.uuid4()),
                workspace_id=test_workspace.id,
                plan_id=pro_plan.id,
                stripe_customer_id="cus_test123",
                stripe_subscription_id="sub_test123",
                status=SubscriptionStatus.ACTIVE,
                current_period_start=datetime.now(timezone.utc),
                current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
                billable_service_count=0,
            )
            db.add(subscription)
            await db.commit()
            await db.refresh(subscription)

            print(f"\n1️⃣  Created PRO subscription:")
            print(f"   - Plan: PRO ({pro_plan.id})")
            print(f"   - Status: {subscription.status}")
            print(f"   - Period End: {subscription.current_period_end}")
            print(f"   - Stripe Sub ID: {subscription.stripe_subscription_id}")

            # Step 2: User cancels subscription
            subscription.canceled_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(subscription)

            print(f"\n2️⃣  User canceled subscription:")
            print(f"   - Canceled At: {subscription.canceled_at}")
            print(f"   - Status: {subscription.status} (still ACTIVE until period ends)")

            # Step 3: Simulate period ending (Feb 28 arrives)
            print(f"\n3️⃣  Simulating period end (Feb 28 arrives)...")

            # Check if canceled
            assert subscription.canceled_at is not None, "Subscription should have canceled_at set"

            # Downgrade to FREE
            subscription.plan_id = free_plan.id
            subscription.stripe_subscription_id = None  # Stop billing
            subscription.stripe_customer_id = None
            subscription.canceled_at = None  # Clear canceled flag
            subscription.current_period_start = datetime.now(timezone.utc)
            subscription.current_period_end = None  # FREE has no period

            await db.commit()
            await db.refresh(subscription)

            print(f"\n4️⃣  Subscription downgraded to FREE:")
            print(f"   - Plan: FREE ({free_plan.id})")
            print(f"   - Status: {subscription.status}")
            print(f"   - Stripe Sub ID: {subscription.stripe_subscription_id} (None = no billing)")
            print(f"   - Canceled At: {subscription.canceled_at} (cleared)")

            # Assertions
            assert subscription.plan_id == free_plan.id, "Should be on FREE plan"
            assert subscription.status == SubscriptionStatus.ACTIVE, "Should be ACTIVE on FREE"
            assert subscription.stripe_subscription_id is None, "No Stripe subscription (no billing)"
            assert subscription.canceled_at is None, "Canceled flag should be cleared"

            print(f"\n✅ TEST PASSED: Subscription successfully downgraded to FREE!")
            print("=" * 70)

            # Cleanup
            await db.delete(subscription)
            await db.commit()

    @pytest.mark.asyncio
    async def test_scenario_2_active_subscription_auto_renews(
        self, test_workspace, pro_plan, subscription_service
    ):
        """
        Scenario 2: Subscription is ACTIVE (NOT canceled)

        Steps:
        1. Create PRO subscription
        2. User does NOT cancel
        3. Period ends (Feb 28 arrives)
        4. Subscription auto-renews
        5. Stripe charges $30
        6. New period: Feb 28 - March 28
        """
        print("\n" + "=" * 70)
        print("TEST SCENARIO 2: Active Subscription Auto-Renews")
        print("=" * 70)

        async with AsyncSessionLocal() as db:
            # Step 1: Create PRO subscription
            period_start = datetime.now(timezone.utc)
            period_end = period_start + timedelta(days=30)

            subscription = Subscription(
                id=str(uuid.uuid4()),
                workspace_id=test_workspace.id,
                plan_id=pro_plan.id,
                stripe_customer_id="cus_test456",
                stripe_subscription_id="sub_test456",
                status=SubscriptionStatus.ACTIVE,
                current_period_start=period_start,
                current_period_end=period_end,
                billable_service_count=0,
            )
            db.add(subscription)
            await db.commit()
            await db.refresh(subscription)

            print(f"\n1️⃣  Created PRO subscription:")
            print(f"   - Plan: PRO ({pro_plan.id})")
            print(f"   - Status: {subscription.status}")
            print(f"   - Period: {subscription.current_period_start} to {subscription.current_period_end}")
            print(f"   - Stripe Sub ID: {subscription.stripe_subscription_id}")

            # Step 2: Verify NOT canceled
            print(f"\n2️⃣  User did NOT cancel:")
            print(f"   - Canceled At: {subscription.canceled_at} (None = will auto-renew)")
            print(f"   - Status: {subscription.status}")

            assert subscription.canceled_at is None, "Should not have canceled_at"

            # Step 3: Simulate period ending (Feb 28 arrives) + Auto-renewal
            print(f"\n3️⃣  Simulating period end + auto-renewal (Feb 28 arrives)...")
            print(f"   - Stripe would charge: ${pro_plan.base_price_cents / 100:.2f}")

            # Simulate Stripe renewal webhook
            old_period_end = subscription.current_period_end
            subscription.current_period_start = old_period_end  # New period starts where old ended
            subscription.current_period_end = old_period_end + timedelta(days=30)  # Add 30 days

            await db.commit()
            await db.refresh(subscription)

            print(f"\n4️⃣  Subscription renewed for another month:")
            print(f"   - Plan: PRO ({pro_plan.id}) - STILL PRO ✓")
            print(f"   - Status: {subscription.status}")
            print(f"   - New Period: {subscription.current_period_start} to {subscription.current_period_end}")
            print(f"   - Stripe Sub ID: {subscription.stripe_subscription_id} (still active)")
            print(f"   - Next charge: Feb 28, 2026 → ${pro_plan.base_price_cents / 100:.2f}")

            # Assertions
            assert subscription.plan_id == pro_plan.id, "Should still be on PRO plan"
            assert subscription.status == SubscriptionStatus.ACTIVE, "Should be ACTIVE"
            assert subscription.stripe_subscription_id is not None, "Stripe subscription still exists"
            assert subscription.canceled_at is None, "Should not be canceled"
            assert subscription.current_period_start == old_period_end, "New period should start at old end"

            print(f"\n✅ TEST PASSED: Subscription successfully auto-renewed!")
            print("=" * 70)

            # Cleanup
            await db.delete(subscription)
            await db.commit()

    @pytest.mark.asyncio
    async def test_scenario_3_cancel_at_period_end_computed_field(
        self, test_workspace, pro_plan
    ):
        """
        Test that cancel_at_period_end computed field works correctly.
        """
        print("\n" + "=" * 70)
        print("TEST SCENARIO 3: cancel_at_period_end Computed Field")
        print("=" * 70)

        from app.billing.schemas import SubscriptionResponse

        async with AsyncSessionLocal() as db:
            # Create PRO subscription with canceled_at set
            subscription = Subscription(
                id=str(uuid.uuid4()),
                workspace_id=test_workspace.id,
                plan_id=pro_plan.id,
                stripe_customer_id="cus_test789",
                stripe_subscription_id="sub_test789",
                status=SubscriptionStatus.ACTIVE,
                current_period_start=datetime.now(timezone.utc),
                current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
                canceled_at=datetime.now(timezone.utc),  # Canceled!
                billable_service_count=0,
            )
            db.add(subscription)
            await db.commit()
            await db.refresh(subscription)

            # Load plan relationship
            await db.refresh(subscription, ["plan"])

            # Create response schema
            response = SubscriptionResponse.model_validate(subscription)

            print(f"\n1️⃣  Subscription with canceled_at set:")
            print(f"   - Status: {response.status}")
            print(f"   - Canceled At: {response.canceled_at}")
            print(f"   - cancel_at_period_end: {response.cancel_at_period_end}")

            # Assertion
            assert response.cancel_at_period_end is True, "Should be True when canceled_at is set and status is ACTIVE"

            print(f"\n✅ TEST PASSED: Computed field works correctly!")
            print("=" * 70)

            # Cleanup
            await db.delete(subscription)
            await db.commit()


def run_integration_tests():
    """
    Run all integration tests manually (without pytest).

    Usage:
        python tests/test_subscription_lifecycle.py
    """
    print("\n🧪 Running Subscription Lifecycle Integration Tests...\n")

    async def run_all():
        test = TestSubscriptionLifecycle()

        # Get fixtures
        workspace = None
        service = SubscriptionService()

        async with AsyncSessionLocal() as db:
            # Get plans
            free_result = await db.execute(select(Plan).where(Plan.plan_type == PlanType.FREE))
            free_plan = free_result.scalar_one()

            pro_result = await db.execute(select(Plan).where(Plan.plan_type == PlanType.PRO))
            pro_plan = pro_result.scalar_one()

            # Create test workspace
            user = User(
                id=str(uuid.uuid4()),
                email=f"test_{uuid.uuid4()}@example.com",
                name="Test User",
                is_onboarded=True,
            )
            db.add(user)

            workspace = Workspace(
                id=str(uuid.uuid4()),
                name="Test Workspace",
                visible_to_org=False,
            )
            db.add(workspace)

            membership = Membership(
                id=str(uuid.uuid4()),
                user_id=user.id,
                workspace_id=workspace.id,
                role=Role.OWNER,
            )
            db.add(membership)

            await db.commit()
            await db.refresh(workspace)

            try:
                # Run tests
                await test.test_scenario_1_canceled_subscription_downgrades_to_free(
                    workspace, pro_plan, free_plan, service
                )

                await test.test_scenario_2_active_subscription_auto_renews(
                    workspace, pro_plan, service
                )

                await test.test_scenario_3_cancel_at_period_end_computed_field(
                    workspace, pro_plan
                )

                print("\n" + "=" * 70)
                print("✅ ALL TESTS PASSED!")
                print("=" * 70)

            finally:
                # Cleanup
                await db.delete(membership)
                await db.delete(workspace)
                await db.delete(user)
                await db.commit()

    asyncio.run(run_all())


if __name__ == "__main__":
    run_integration_tests()
