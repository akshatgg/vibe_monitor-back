"""
Integration tests for chat endpoints.

These tests use a real test database to verify:
- Chat session CRUD operations
- Chat turn management
- Feedback submission
- Session search

Endpoints tested:
- POST /api/v1/workspaces/{workspace_id}/chat
- GET /api/v1/workspaces/{workspace_id}/sessions
- GET /api/v1/workspaces/{workspace_id}/sessions/search
- GET /api/v1/workspaces/{workspace_id}/sessions/{session_id}
- PATCH /api/v1/workspaces/{workspace_id}/sessions/{session_id}
- DELETE /api/v1/workspaces/{workspace_id}/sessions/{session_id}
- GET /api/v1/workspaces/{workspace_id}/turns/{turn_id}
- POST /api/v1/workspaces/{workspace_id}/turns/{turn_id}/feedback
- POST /api/v1/workspaces/{workspace_id}/turns/{turn_id}/comment
"""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChatSession,
    ChatTurn,
    Job,
    JobSource,
    JobStatus,
    Membership,
    Plan,
    PlanType,
    Role,
    Subscription,
    SubscriptionStatus,
    TurnComment,
    TurnFeedback,
    TurnStatus,
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
) -> Plan:
    """Create a plan in the test database."""
    plan = Plan(
        id=str(uuid.uuid4()),
        name=name,
        plan_type=plan_type,
        base_service_count=5,
        base_price_cents=0,
        additional_service_price_cents=500,
        rca_session_limit_daily=10,
        is_active=True,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


async def create_test_subscription(
    db: AsyncSession,
    workspace_id: str,
    plan_id: str,
) -> Subscription:
    """Create a subscription in the test database."""
    subscription = Subscription(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        plan_id=plan_id,
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def create_test_chat_session(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
    title: str = "Test Session",
    source: JobSource = JobSource.WEB,
) -> ChatSession:
    """Create a chat session in the test database."""
    session = ChatSession(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        user_id=user_id,
        title=title,
        source=source,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def create_test_chat_turn(
    db: AsyncSession,
    session_id: str,
    user_message: str = "Test message",
    final_response: str = None,
    status: TurnStatus = TurnStatus.COMPLETED,
    job_id: str = None,
) -> ChatTurn:
    """Create a chat turn in the test database."""
    turn = ChatTurn(
        id=str(uuid.uuid4()),
        session_id=session_id,
        user_message=user_message,
        final_response=final_response,
        status=status,
        job_id=job_id,
    )
    db.add(turn)
    await db.commit()
    await db.refresh(turn)
    return turn


async def create_test_job(
    db: AsyncSession,
    workspace_id: str,
    status: JobStatus = JobStatus.QUEUED,
    source: JobSource = JobSource.WEB,
) -> Job:
    """Create a job in the test database."""
    job = Job(
        id=str(uuid.uuid4()),
        vm_workspace_id=workspace_id,
        status=status,
        source=source,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def create_test_turn_feedback(
    db: AsyncSession,
    turn_id: str,
    user_id: str,
    is_positive: bool = True,
) -> TurnFeedback:
    """Create turn feedback in the test database."""
    feedback = TurnFeedback(
        id=str(uuid.uuid4()),
        turn_id=turn_id,
        user_id=user_id,
        is_positive=is_positive,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return feedback


# =============================================================================
# Tests: Chat Session Endpoints
# =============================================================================


class TestListSessions:
    """Integration tests for GET /api/v1/workspaces/{workspace_id}/sessions."""

    @pytest.mark.asyncio
    async def test_list_sessions_returns_user_sessions(self, client, test_db):
        """List sessions returns sessions for the current user."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        await create_test_chat_session(
            test_db, workspace.id, user.id, title="Session 1"
        )
        await create_test_chat_session(
            test_db, workspace.id, user.id, title="Session 2"
        )

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/sessions",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        titles = [s["title"] for s in data]
        assert "Session 1" in titles
        assert "Session 2" in titles

    @pytest.mark.asyncio
    async def test_list_sessions_does_not_return_other_users_sessions(
        self, client, test_db
    ):
        """List sessions does not return sessions belonging to other users."""
        user1 = await create_test_user(test_db, email="user1@example.com")
        user2 = await create_test_user(test_db, email="user2@example.com")
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user1.id, workspace.id)
        await create_test_membership(test_db, user2.id, workspace.id)

        await create_test_chat_session(
            test_db, workspace.id, user1.id, title="User1 Session"
        )
        await create_test_chat_session(
            test_db, workspace.id, user2.id, title="User2 Session"
        )

        headers = get_auth_headers(user1)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/sessions",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "User1 Session"

    @pytest.mark.asyncio
    async def test_list_sessions_with_pagination(self, client, test_db):
        """List sessions supports limit and offset pagination."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        for i in range(5):
            await create_test_chat_session(
                test_db, workspace.id, user.id, title=f"Session {i}"
            )

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/sessions?limit=2&offset=1",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, client, test_db):
        """List sessions returns empty list when no sessions exist."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/sessions",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data == []


class TestGetSession:
    """Integration tests for GET /api/v1/workspaces/{workspace_id}/sessions/{session_id}."""

    @pytest.mark.asyncio
    async def test_get_session_returns_session_with_turns(self, client, test_db):
        """Get session returns session details with turns."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        session = await create_test_chat_session(
            test_db, workspace.id, user.id, title="Test Session"
        )
        await create_test_chat_turn(test_db, session.id, user_message="First question")
        await create_test_chat_turn(test_db, session.id, user_message="Second question")

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/sessions/{session.id}",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == session.id
        assert data["title"] == "Test Session"
        assert len(data["turns"]) == 2

    @pytest.mark.asyncio
    async def test_get_session_not_found_returns_404(self, client, test_db):
        """Get non-existent session returns 404."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/sessions/non-existent-id",
            headers=headers,
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_session_other_user_returns_404(self, client, test_db):
        """Get session belonging to another user returns 404."""
        user1 = await create_test_user(test_db, email="user1@example.com")
        user2 = await create_test_user(test_db, email="user2@example.com")
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user1.id, workspace.id)
        await create_test_membership(test_db, user2.id, workspace.id)

        session = await create_test_chat_session(
            test_db, workspace.id, user2.id, title="User2's Session"
        )

        headers = get_auth_headers(user1)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/sessions/{session.id}",
            headers=headers,
        )

        assert response.status_code == 404


class TestUpdateSession:
    """Integration tests for PATCH /api/v1/workspaces/{workspace_id}/sessions/{session_id}."""

    @pytest.mark.asyncio
    async def test_update_session_not_found_returns_404(self, client, test_db):
        """Update non-existent session returns 404."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        headers = get_auth_headers(user)

        response = await client.patch(
            f"{API_PREFIX}/workspaces/{workspace.id}/sessions/non-existent-id",
            json={"title": "New Title"},
            headers=headers,
        )

        assert response.status_code == 404


class TestDeleteSession:
    """Integration tests for DELETE /api/v1/workspaces/{workspace_id}/sessions/{session_id}."""

    @pytest.mark.asyncio
    async def test_delete_session_success(self, client, test_db):
        """Delete session returns 204 and removes from database."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        session = await create_test_chat_session(
            test_db, workspace.id, user.id, title="To Delete"
        )

        headers = get_auth_headers(user)

        response = await client.delete(
            f"{API_PREFIX}/workspaces/{workspace.id}/sessions/{session.id}",
            headers=headers,
        )

        assert response.status_code == 204

        # Verify deleted from database
        result = await test_db.execute(select(ChatSession).filter_by(id=session.id))
        deleted_session = result.scalar_one_or_none()
        assert deleted_session is None

    @pytest.mark.asyncio
    async def test_delete_session_cascades_to_turns(self, client, test_db):
        """Delete session also deletes associated turns."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        session = await create_test_chat_session(test_db, workspace.id, user.id)
        turn = await create_test_chat_turn(test_db, session.id)

        headers = get_auth_headers(user)

        await client.delete(
            f"{API_PREFIX}/workspaces/{workspace.id}/sessions/{session.id}",
            headers=headers,
        )

        # Verify turn is also deleted
        result = await test_db.execute(select(ChatTurn).filter_by(id=turn.id))
        deleted_turn = result.scalar_one_or_none()
        assert deleted_turn is None

    @pytest.mark.asyncio
    async def test_delete_session_not_found_returns_404(self, client, test_db):
        """Delete non-existent session returns 404."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        headers = get_auth_headers(user)

        response = await client.delete(
            f"{API_PREFIX}/workspaces/{workspace.id}/sessions/non-existent-id",
            headers=headers,
        )

        assert response.status_code == 404


# =============================================================================
# Tests: Chat Turn Endpoints
# =============================================================================


class TestGetTurn:
    """Integration tests for GET /api/v1/workspaces/{workspace_id}/turns/{turn_id}."""

    @pytest.mark.asyncio
    async def test_get_turn_returns_turn_details(self, client, test_db):
        """Get turn returns turn details with steps."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        session = await create_test_chat_session(test_db, workspace.id, user.id)
        turn = await create_test_chat_turn(
            test_db,
            session.id,
            user_message="What caused the error?",
            final_response="The error was caused by...",
            status=TurnStatus.COMPLETED,
        )

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/{turn.id}",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == turn.id
        assert data["user_message"] == "What caused the error?"
        assert data["final_response"] == "The error was caused by..."
        assert data["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_get_turn_not_found_returns_404(self, client, test_db):
        """Get non-existent turn returns 404."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/non-existent-id",
            headers=headers,
        )

        assert response.status_code == 404


# =============================================================================
# Tests: Feedback Endpoints
# =============================================================================


class TestSubmitFeedback:
    """Integration tests for POST /api/v1/workspaces/{workspace_id}/turns/{turn_id}/feedback."""

    @pytest.mark.asyncio
    async def test_submit_positive_feedback(self, client, test_db):
        """Submit positive feedback (thumbs up) successfully."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        session = await create_test_chat_session(test_db, workspace.id, user.id)
        turn = await create_test_chat_turn(test_db, session.id)

        headers = get_auth_headers(user)

        response = await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/{turn.id}/feedback",
            json={"is_positive": True},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["turn_id"] == turn.id
        assert data["is_positive"] is True

    @pytest.mark.asyncio
    async def test_submit_negative_feedback(self, client, test_db):
        """Submit negative feedback (thumbs down) successfully."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        session = await create_test_chat_session(test_db, workspace.id, user.id)
        turn = await create_test_chat_turn(test_db, session.id)

        headers = get_auth_headers(user)

        response = await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/{turn.id}/feedback",
            json={"is_positive": False},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_positive"] is False

    @pytest.mark.asyncio
    async def test_submit_feedback_with_comment(self, client, test_db):
        """Submit feedback with optional comment."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        session = await create_test_chat_session(test_db, workspace.id, user.id)
        turn = await create_test_chat_turn(test_db, session.id)

        headers = get_auth_headers(user)

        response = await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/{turn.id}/feedback",
            json={
                "is_positive": True,
                "comment": "Very helpful analysis!",
            },
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_positive"] is True
        assert data["comment"] == "Very helpful analysis!"

    @pytest.mark.asyncio
    async def test_submit_feedback_persists_to_database(self, client, test_db):
        """Submit feedback persists data to database."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        session = await create_test_chat_session(test_db, workspace.id, user.id)
        turn = await create_test_chat_turn(test_db, session.id)

        headers = get_auth_headers(user)

        await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/{turn.id}/feedback",
            json={"is_positive": True},
            headers=headers,
        )

        result = await test_db.execute(
            select(TurnFeedback).filter_by(turn_id=turn.id, user_id=user.id)
        )
        feedback = result.scalar_one_or_none()
        assert feedback is not None
        assert feedback.is_positive is True

    @pytest.mark.asyncio
    async def test_submit_feedback_turn_not_found_returns_404(self, client, test_db):
        """Submit feedback for non-existent turn returns 404."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        headers = get_auth_headers(user)

        response = await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/non-existent-id/feedback",
            json={"is_positive": True},
            headers=headers,
        )

        assert response.status_code == 404


class TestAddFeedbackComment:
    """Integration tests for POST /api/v1/workspaces/{workspace_id}/turns/{turn_id}/comment."""

    @pytest.mark.asyncio
    async def test_add_comment_success(self, client, test_db):
        """Add comment to turn successfully."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        session = await create_test_chat_session(test_db, workspace.id, user.id)
        turn = await create_test_chat_turn(test_db, session.id)

        headers = get_auth_headers(user)

        response = await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/{turn.id}/comment",
            json={"comment": "This could be improved by..."},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["comment"] == "This could be improved by..."

    @pytest.mark.asyncio
    async def test_add_comment_persists_to_database(self, client, test_db):
        """Add comment persists to database."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        session = await create_test_chat_session(test_db, workspace.id, user.id)
        turn = await create_test_chat_turn(test_db, session.id)

        headers = get_auth_headers(user)

        await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/{turn.id}/comment",
            json={"comment": "Detailed feedback comment"},
            headers=headers,
        )

        result = await test_db.execute(
            select(TurnComment).filter_by(turn_id=turn.id, user_id=user.id)
        )
        comment = result.scalar_one_or_none()
        assert comment is not None
        assert comment.comment == "Detailed feedback comment"

    @pytest.mark.asyncio
    async def test_add_comment_turn_not_found_returns_404(self, client, test_db):
        """Add comment for non-existent turn returns 404."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        headers = get_auth_headers(user)

        response = await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/non-existent-id/comment",
            json={"comment": "Some comment"},
            headers=headers,
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_add_multiple_comments(self, client, test_db):
        """User can add multiple comments to the same turn."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        session = await create_test_chat_session(test_db, workspace.id, user.id)
        turn = await create_test_chat_turn(test_db, session.id)

        headers = get_auth_headers(user)

        await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/{turn.id}/comment",
            json={"comment": "First comment"},
            headers=headers,
        )
        await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/turns/{turn.id}/comment",
            json={"comment": "Second comment"},
            headers=headers,
        )

        result = await test_db.execute(
            select(TurnComment).filter_by(turn_id=turn.id, user_id=user.id)
        )
        comments = result.scalars().all()
        assert len(comments) == 2


# =============================================================================
# Tests: Send Message (Chat) Endpoint
# =============================================================================


class TestSendMessage:
    """Integration tests for POST /api/v1/workspaces/{workspace_id}/chat."""

    @pytest.mark.asyncio
    @patch("app.chat.router.check_rate_limit_with_byollm_bypass")
    async def test_send_message_creates_session_and_turn(
        self, mock_rate_limit, client, test_db
    ):
        """Send message creates new session and turn when no session_id provided."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)
        plan = await create_test_plan(test_db)
        await create_test_subscription(test_db, workspace.id, plan.id)

        headers = get_auth_headers(user)
        mock_rate_limit.return_value = (True, 0, 10)  # allowed, count, limit

        response = await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/chat",
            data={"message": "What caused the database timeout?"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "turn_id" in data
        assert "session_id" in data

    @pytest.mark.asyncio
    @patch("app.chat.router.check_rate_limit_with_byollm_bypass")
    async def test_send_message_rate_limited_returns_429(
        self, mock_rate_limit, client, test_db
    ):
        """Send message returns 429 when rate limit exceeded."""
        user = await create_test_user(test_db)
        workspace = await create_test_workspace(test_db)
        await create_test_membership(test_db, user.id, workspace.id)

        headers = get_auth_headers(user)
        mock_rate_limit.return_value = (False, 10, 10)  # not allowed, at limit

        response = await client.post(
            f"{API_PREFIX}/workspaces/{workspace.id}/chat",
            data={"message": "Rate limited message"},
            headers=headers,
        )

        assert response.status_code == 429
        data = response.json()
        assert "limit" in data["detail"]
