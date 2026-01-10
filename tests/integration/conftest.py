"""
Shared fixtures for integration tests.

This conftest.py provides async test database and client fixtures that ALL
integration tests should use. This ensures consistency across test files
written by different developers or Claude windows.

IMPORTANT: All integration tests in this project MUST:
1. Use async tests with @pytest.mark.asyncio
2. Use the `client` fixture (AsyncClient) - NOT TestClient
3. Use the `test_db` fixture (AsyncSession) - NOT sync Session
4. Use `await` for all HTTP calls and DB operations
5. Prefix all routes with /api/v1/

Example:
    @pytest.mark.asyncio
    async def test_something(client, test_db):
        response = await client.post("/api/v1/auth/signup", json={...})
        assert response.status_code == 201
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app


# =============================================================================
# Test Database Configuration
# =============================================================================

# Using aiosqlite for async SQLite support
# This requires `pip install aiosqlite`
SQLALCHEMY_TEST_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_db():
    """
    Create a fresh async in-memory database for each test.

    This fixture:
    - Creates tables before each test
    - Yields an AsyncSession for the test to use
    - Drops all tables after the test completes
    - Disposes of the engine to clean up resources

    The test DB is completely isolated - no data persists between tests.
    """
    engine = create_async_engine(
        SQLALCHEMY_TEST_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # Provide session to test
    async with async_session() as session:
        yield session

    # Cleanup: drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_db):
    """
    Create async test client with database override.

    This fixture:
    - Overrides the app's get_db dependency to use the test database
    - Provides an AsyncClient for making HTTP requests
    - Uses base_url="http://test" (requests go directly to the app)
    - Clears dependency overrides after the test

    IMPORTANT: Always use `await` with client methods:
        response = await client.post("/api/v1/auth/signup", json={...})
    """

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# =============================================================================
# API Prefix Constant
# =============================================================================

# All API routes are prefixed with this. Use it in your tests!
API_PREFIX = "/api/v1"


# =============================================================================
# Authentication Helpers
# =============================================================================


def get_auth_headers(user) -> dict:
    """
    Generate JWT auth headers for a user.

    Creates a valid access token that can be used in Authorization headers.
    """
    from app.auth.google.service import AuthService

    auth_service = AuthService()
    access_token = auth_service.create_access_token(
        data={"sub": user.id, "email": user.email}
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def test_user(test_db):
    """
    Create a test user in the database.

    Returns a User model instance that can be used for authentication.
    """
    import uuid

    from app.models import User

    user = User(
        id=str(uuid.uuid4()),
        name="Test User",
        email="testuser@example.com",
        is_verified=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


@pytest_asyncio.fixture
async def second_user(test_db):
    """
    Create a second test user for multi-user scenarios.
    """
    import uuid

    from app.models import User

    user = User(
        id=str(uuid.uuid4()),
        name="Second User",
        email="seconduser@example.com",
        is_verified=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(test_user):
    """
    Generate auth headers for the test_user.

    Usage:
        async def test_something(client, auth_headers):
            response = await client.get("/api/v1/workspaces", headers=auth_headers)
            assert response.status_code == 200
    """
    return get_auth_headers(test_user)


@pytest_asyncio.fixture
async def auth_client(test_db, test_user):
    """
    Create an authenticated test client with pre-configured auth headers.

    This fixture creates a client that automatically includes JWT auth headers
    for the test_user in every request.

    Usage:
        async def test_something(auth_client, test_user):
            response = await auth_client.get("/api/v1/workspaces")
            assert response.status_code == 200
    """

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    headers = get_auth_headers(test_user)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# =============================================================================
# Test Data Helpers
# =============================================================================


@pytest_asyncio.fixture
async def test_workspace(test_db, test_user):
    """
    Create a test workspace with the test_user as owner.
    """
    import uuid

    from app.models import Membership, Role, Workspace, WorkspaceType

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Test Workspace",
        type=WorkspaceType.TEAM,
        visible_to_org=False,
        is_paid=False,
    )
    test_db.add(workspace)
    await test_db.flush()

    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(membership)
    await test_db.commit()
    await test_db.refresh(workspace)
    return workspace


@pytest_asyncio.fixture
async def test_environment(test_db, test_workspace):
    """
    Create a test environment in the test workspace.
    """
    import uuid

    from app.models import Environment

    environment = Environment(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        name="Production",
        is_default=True,
    )
    test_db.add(environment)
    await test_db.commit()
    await test_db.refresh(environment)
    return environment
