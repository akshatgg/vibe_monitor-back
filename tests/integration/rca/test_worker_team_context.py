"""
Integration tests for worker.py team context fetching functions.
"""

import pytest

from app.models import Team, TeamMembership, User, Workspace, Service
from app.worker import fetch_team_context


@pytest.mark.asyncio
async def test_fetch_team_context_with_teams(test_db):
    """Should fetch complete team context with members and services"""
    # Create workspace
    workspace = Workspace(
        id="test-workspace-id",
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    # Create users
    user1 = User(
        id="user1",
        email="alice@example.com",
        name="Alice Smith",
    )
    user2 = User(
        id="user2",
        email="bob@example.com",
        name="Bob Jones",
    )
    test_db.add(user1)
    test_db.add(user2)
    await test_db.flush()

    # Create teams
    team1 = Team(
        id="team1",
        workspace_id=workspace.id,
        name="Backend Team",
        geography="US-East",
    )
    team2 = Team(
        id="team2",
        workspace_id=workspace.id,
        name="Frontend Team",
        geography="US-West",
    )
    test_db.add(team1)
    test_db.add(team2)
    await test_db.flush()

    # Create team memberships
    membership1 = TeamMembership(
        id="membership1",
        team_id=team1.id,
        user_id=user1.id,
    )
    membership2 = TeamMembership(
        id="membership2",
        team_id=team1.id,
        user_id=user2.id,
    )
    membership3 = TeamMembership(
        id="membership3",
        team_id=team2.id,
        user_id=user1.id,
    )
    test_db.add(membership1)
    test_db.add(membership2)
    test_db.add(membership3)
    await test_db.flush()

    # Create services
    service1 = Service(
        id="service1",
        workspace_id=workspace.id,
        team_id=team1.id,
        name="auth-service",
        repository_name="auth",
        enabled=True,
    )
    service2 = Service(
        id="service2",
        workspace_id=workspace.id,
        team_id=team1.id,
        name="api-service",
        repository_name="api",
        enabled=True,
    )
    service3 = Service(
        id="service3",
        workspace_id=workspace.id,
        team_id=team2.id,
        name="web-service",
        repository_name="web",
        enabled=True,
    )
    # Disabled service - should be excluded
    service4 = Service(
        id="service4",
        workspace_id=workspace.id,
        team_id=team1.id,
        name="disabled-service",
        repository_name="disabled",
        enabled=False,
    )
    test_db.add(service1)
    test_db.add(service2)
    test_db.add(service3)
    test_db.add(service4)
    await test_db.commit()

    # Fetch team context
    result = await fetch_team_context(workspace.id, test_db)

    # Verify result structure
    assert "teams" in result
    assert len(result["teams"]) == 2
    assert "error" not in result

    # Verify Backend Team
    backend_team = next((t for t in result["teams"] if t["name"] == "Backend Team"), None)
    assert backend_team is not None
    assert backend_team["geography"] == "US-East"
    assert set(backend_team["members"]) == {"Alice Smith", "Bob Jones"}
    assert set(backend_team["services"]) == {"auth-service", "api-service"}
    assert "disabled-service" not in backend_team["services"]

    # Verify Frontend Team
    frontend_team = next((t for t in result["teams"] if t["name"] == "Frontend Team"), None)
    assert frontend_team is not None
    assert frontend_team["geography"] == "US-West"
    assert frontend_team["members"] == ["Alice Smith"]
    assert frontend_team["services"] == ["web-service"]


@pytest.mark.asyncio
async def test_fetch_team_context_no_teams(test_db):
    """Should return empty teams list when workspace has no teams"""
    # Create workspace without teams
    workspace = Workspace(
        id="test-workspace-id",
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.commit()

    result = await fetch_team_context(workspace.id, test_db)

    assert result == {"teams": []}


@pytest.mark.asyncio
async def test_fetch_team_context_user_without_name(test_db):
    """Should fall back to email when user name is not set"""
    # Create workspace
    workspace = Workspace(
        id="test-workspace-id",
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    # Create user without name (use empty string to satisfy NOT NULL constraint)
    user = User(
        id="user1",
        email="noemail@example.com",
        name="",  # Empty string instead of None to satisfy database constraint
    )
    test_db.add(user)
    await test_db.flush()

    # Create team
    team = Team(
        id="team1",
        workspace_id=workspace.id,
        name="Backend Team",
        geography="US-East",
    )
    test_db.add(team)
    await test_db.flush()

    # Create team membership
    membership = TeamMembership(
        id="membership1",
        team_id=team.id,
        user_id=user.id,
    )
    test_db.add(membership)
    await test_db.commit()

    result = await fetch_team_context(workspace.id, test_db)

    # Should mask email domain to protect PII
    assert len(result["teams"]) == 1
    assert result["teams"][0]["members"] == ["noemail@[REDACTED]"]


@pytest.mark.asyncio
async def test_fetch_team_context_team_without_geography(test_db):
    """Should handle teams without geography field"""
    # Create workspace
    workspace = Workspace(
        id="test-workspace-id",
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    # Create team without geography
    team = Team(
        id="team1",
        workspace_id=workspace.id,
        name="Backend Team",
        geography=None,
    )
    test_db.add(team)
    await test_db.commit()

    result = await fetch_team_context(workspace.id, test_db)

    assert len(result["teams"]) == 1
    assert result["teams"][0]["geography"] is None


@pytest.mark.asyncio
async def test_fetch_team_context_team_without_members(test_db):
    """Should handle teams with no members"""
    # Create workspace
    workspace = Workspace(
        id="test-workspace-id",
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    # Create team without members
    team = Team(
        id="team1",
        workspace_id=workspace.id,
        name="Backend Team",
        geography="US-East",
    )
    test_db.add(team)
    await test_db.commit()

    result = await fetch_team_context(workspace.id, test_db)

    assert len(result["teams"]) == 1
    assert result["teams"][0]["members"] == []


@pytest.mark.asyncio
async def test_fetch_team_context_team_without_services(test_db):
    """Should handle teams with no services"""
    # Create workspace
    workspace = Workspace(
        id="test-workspace-id",
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    # Create team without services
    team = Team(
        id="team1",
        workspace_id=workspace.id,
        name="Backend Team",
        geography="US-East",
    )
    test_db.add(team)
    await test_db.commit()

    result = await fetch_team_context(workspace.id, test_db)

    assert len(result["teams"]) == 1
    assert result["teams"][0]["services"] == []


@pytest.mark.asyncio
async def test_fetch_team_context_excludes_disabled_services(test_db):
    """Should exclude disabled services from team context"""
    # Create workspace
    workspace = Workspace(
        id="test-workspace-id",
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    # Create team
    team = Team(
        id="team1",
        workspace_id=workspace.id,
        name="Backend Team",
        geography="US-East",
    )
    test_db.add(team)
    await test_db.flush()

    # Create enabled and disabled services
    service1 = Service(
        id="service1",
        workspace_id=workspace.id,
        team_id=team.id,
        name="enabled-service",
        repository_name="enabled",
        enabled=True,
    )
    service2 = Service(
        id="service2",
        workspace_id=workspace.id,
        team_id=team.id,
        name="disabled-service",
        repository_name="disabled",
        enabled=False,
    )
    test_db.add(service1)
    test_db.add(service2)
    await test_db.commit()

    result = await fetch_team_context(workspace.id, test_db)

    assert len(result["teams"]) == 1
    assert result["teams"][0]["services"] == ["enabled-service"]
    assert "disabled-service" not in result["teams"][0]["services"]


@pytest.mark.asyncio
async def test_fetch_team_context_sorts_teams_by_name(test_db):
    """Should return teams sorted by name"""
    # Create workspace
    workspace = Workspace(
        id="test-workspace-id",
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    # Create teams in non-alphabetical order
    team_zebra = Team(
        id="team1",
        workspace_id=workspace.id,
        name="Zebra Team",
        geography="US-East",
    )
    team_alpha = Team(
        id="team2",
        workspace_id=workspace.id,
        name="Alpha Team",
        geography="US-West",
    )
    team_beta = Team(
        id="team3",
        workspace_id=workspace.id,
        name="Beta Team",
        geography="EU",
    )
    test_db.add(team_zebra)
    test_db.add(team_alpha)
    test_db.add(team_beta)
    await test_db.commit()

    result = await fetch_team_context(workspace.id, test_db)

    # Verify teams are sorted by name
    assert len(result["teams"]) == 3
    assert result["teams"][0]["name"] == "Alpha Team"
    assert result["teams"][1]["name"] == "Beta Team"
    assert result["teams"][2]["name"] == "Zebra Team"


@pytest.mark.asyncio
async def test_fetch_team_context_masks_emails(test_db):
    """Should mask email addresses in team members to protect PII"""
    # Create workspace
    workspace = Workspace(
        id="test-workspace-id",
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    # Create users - one with name, one without (will use email)
    user1 = User(
        id="user1",
        email="alice@example.com",
        name="Alice Smith",
    )
    user2 = User(
        id="user2",
        email="bob@company.com",
        name="",  # No name, will use email
    )
    test_db.add(user1)
    test_db.add(user2)
    await test_db.flush()

    # Create team
    team = Team(
        id="team1",
        workspace_id=workspace.id,
        name="Backend Team",
        geography="US-East",
    )
    test_db.add(team)
    await test_db.flush()

    # Create team memberships
    membership1 = TeamMembership(
        id="membership1",
        team_id=team.id,
        user_id=user1.id,
    )
    membership2 = TeamMembership(
        id="membership2",
        team_id=team.id,
        user_id=user2.id,
    )
    test_db.add(membership1)
    test_db.add(membership2)
    await test_db.commit()

    result = await fetch_team_context(workspace.id, test_db)

    # User with name should show name, user without name should show masked email
    assert len(result["teams"]) == 1
    members = result["teams"][0]["members"]
    assert "Alice Smith" in members  # Name preserved
    assert "bob@[REDACTED]" in members  # Email masked
    assert "bob@company.com" not in members  # Original email not exposed


@pytest.mark.asyncio
async def test_fetch_team_context_orphaned_membership(test_db, caplog):
    """Should log warning for orphaned team memberships"""
    # Create workspace
    workspace = Workspace(
        id="test-workspace-id",
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    # Create team
    team = Team(
        id="team1",
        workspace_id=workspace.id,
        name="Backend Team",
        geography="US-East",
    )
    test_db.add(team)
    await test_db.flush()

    # Create orphaned membership (user_id points to non-existent user)
    membership = TeamMembership(
        id="membership1",
        team_id=team.id,
        user_id="non-existent-user-id",
    )
    test_db.add(membership)
    await test_db.commit()

    # Clear any existing log records
    caplog.clear()

    result = await fetch_team_context(workspace.id, test_db)

    # Should handle gracefully and log warning
    assert len(result["teams"]) == 1
    assert result["teams"][0]["members"] == []

    # Check for warning log about orphaned membership
    warning_logs = [
        record.message
        for record in caplog.records
        if record.levelname == "WARNING" and "orphaned" in record.message.lower()
    ]
    assert len(warning_logs) > 0


@pytest.mark.asyncio
async def test_fetch_team_context_database_error(test_db):
    """Should handle database errors gracefully"""
    from unittest.mock import AsyncMock
    from sqlalchemy.exc import SQLAlchemyError

    # Create workspace
    workspace = Workspace(
        id="test-workspace-id",
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.commit()

    # Create a mock database session that raises an error
    mock_db = AsyncMock()
    mock_db.execute.side_effect = SQLAlchemyError("Connection lost")

    result = await fetch_team_context(workspace.id, mock_db)

    # Should return empty teams list with sanitized error
    assert result["teams"] == []
    assert "error" in result
    # Error message should be sanitized (not expose internal details)
    assert result["error"] == "Failed to fetch team context"
    assert "Connection lost" not in result["error"]
