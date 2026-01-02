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
