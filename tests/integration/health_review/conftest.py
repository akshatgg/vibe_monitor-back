"""
Fixtures for health review integration tests.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest_asyncio

from app.models import Service


@pytest_asyncio.fixture
async def test_service(test_db, test_workspace):
    """
    Create a test service in the test workspace.
    """
    service = Service(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        name="test-service",
        repository_name="org/test-repo",
        enabled=True,
    )
    test_db.add(service)
    await test_db.commit()
    await test_db.refresh(service)
    return service


@pytest_asyncio.fixture
async def multiple_services(test_db, test_workspace):
    """
    Create multiple test services in the test workspace.
    """
    services = []
    for i in range(4):
        service = Service(
            id=str(uuid.uuid4()),
            workspace_id=test_workspace.id,
            name=f"service-{i + 1}",
            repository_name=f"org/service-{i + 1}",
            enabled=True,
        )
        test_db.add(service)
        services.append(service)

    await test_db.commit()
    for svc in services:
        await test_db.refresh(svc)
    return services


@pytest_asyncio.fixture
def mock_sqs_publish():
    """
    Mock the SQS publish function to avoid actual AWS calls.
    """
    with patch(
        "app.health_review_system.api.router.publish_health_review_job",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock:
        yield mock
