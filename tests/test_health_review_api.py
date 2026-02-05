"""
Tests for Health Review API endpoints.

Tests both single service review and bulk review functionality.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.health_review_system.api.schemas import (
    BulkCreateReviewRequest,
    BulkCreateReviewResponse,
    BulkReviewItem,
    CreateReviewRequest,
)
from app.models import (
    ReviewStatus,
    ReviewTriggeredBy,
    Service,
    ServiceReview,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_service():
    """Create a mock service."""
    service = MagicMock(spec=Service)
    service.id = str(uuid.uuid4())
    service.name = "test-service"
    service.workspace_id = str(uuid.uuid4())
    service.repository_name = "org/test-repo"
    service.enabled = True
    return service


@pytest.fixture
def mock_services(mock_service):
    """Create a list of mock services."""
    services = [mock_service]
    for i in range(3):
        svc = MagicMock(spec=Service)
        svc.id = str(uuid.uuid4())
        svc.name = f"service-{i+1}"
        svc.workspace_id = mock_service.workspace_id
        svc.repository_name = f"org/service-{i+1}"
        svc.enabled = True
        services.append(svc)
    return services


@pytest.fixture
def mock_review(mock_service):
    """Create a mock service review."""
    review = MagicMock(spec=ServiceReview)
    review.id = str(uuid.uuid4())
    review.service_id = mock_service.id
    review.workspace_id = mock_service.workspace_id
    review.status = ReviewStatus.QUEUED
    review.triggered_by = ReviewTriggeredBy.API
    review.review_week_start = datetime.now(timezone.utc) - timedelta(days=7)
    review.review_week_end = datetime.now(timezone.utc)
    return review


# =============================================================================
# Single Service Review Tests
# =============================================================================


class TestCreateReview:
    """Tests for POST /health-reviews/services/{service_id}/reviews"""

    @pytest.mark.asyncio
    async def test_create_review_success(self, mock_db, mock_user, mock_service):
        """Test successful review creation."""
        from app.health_review_system.api.router import create_review

        # Setup mocks
        mock_db.get = AsyncMock(return_value=mock_service)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No existing review
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.health_review_system.api.router.publish_health_review_job",
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await create_review(
                service_id=mock_service.id,
                request=None,
                db=mock_db,
                current_user=mock_user,
            )

        assert response.status == "QUEUED"
        assert response.message == "Health review queued for processing"
        assert response.review_id is not None
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_review_service_not_found(self, mock_db, mock_user):
        """Test review creation when service doesn't exist."""
        from fastapi import HTTPException
        from app.health_review_system.api.router import create_review

        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await create_review(
                service_id="non-existent-id",
                request=None,
                db=mock_db,
                current_user=mock_user,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_review_existing_in_progress(
        self, mock_db, mock_user, mock_service, mock_review
    ):
        """Test review creation when review already in progress."""
        from app.health_review_system.api.router import create_review

        mock_db.get = AsyncMock(return_value=mock_service)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_review
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await create_review(
            service_id=mock_service.id,
            request=None,
            db=mock_db,
            current_user=mock_user,
        )

        assert response.message == "Review already in progress for this period"
        assert str(response.review_id) == mock_review.id
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_review_with_custom_time_range(
        self, mock_db, mock_user, mock_service
    ):
        """Test review creation with custom time range."""
        from app.health_review_system.api.router import create_review

        mock_db.get = AsyncMock(return_value=mock_service)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        week_end = datetime.now(timezone.utc)
        week_start = week_end - timedelta(days=14)
        request = CreateReviewRequest(week_start=week_start, week_end=week_end)

        with patch(
            "app.health_review_system.api.router.publish_health_review_job",
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await create_review(
                service_id=mock_service.id,
                request=request,
                db=mock_db,
                current_user=mock_user,
            )

        assert response.status == "QUEUED"


# =============================================================================
# Bulk Review Tests
# =============================================================================


class TestCreateBulkReviews:
    """Tests for POST /health-reviews/workspaces/{workspace_id}/bulk-reviews"""

    @pytest.mark.asyncio
    async def test_bulk_review_success(self, mock_db, mock_user, mock_services):
        """Test successful bulk review creation."""
        from app.health_review_system.api.router import create_bulk_reviews

        workspace_id = mock_services[0].workspace_id

        # Mock fetching services
        mock_services_result = MagicMock()
        mock_services_result.scalars.return_value.all.return_value = mock_services

        # Mock checking existing reviews (none exist)
        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(
            side_effect=[mock_services_result] + [mock_existing_result] * len(mock_services)
        )

        with patch(
            "app.health_review_system.api.router.publish_health_review_job",
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await create_bulk_reviews(
                workspace_id=workspace_id,
                request=None,
                db=mock_db,
                current_user=mock_user,
            )

        assert response.queued_count == len(mock_services)
        assert response.skipped_count == 0
        assert len(response.reviews) == len(mock_services)
        assert all(not r.skipped for r in response.reviews)

    @pytest.mark.asyncio
    async def test_bulk_review_no_services(self, mock_db, mock_user):
        """Test bulk review when no services exist."""
        from app.health_review_system.api.router import create_bulk_reviews

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await create_bulk_reviews(
            workspace_id=str(uuid.uuid4()),
            request=None,
            db=mock_db,
            current_user=mock_user,
        )

        assert response.queued_count == 0
        assert response.skipped_count == 0
        assert response.message == "No services found in workspace"

    @pytest.mark.asyncio
    async def test_bulk_review_with_existing_reviews(
        self, mock_db, mock_user, mock_services, mock_review
    ):
        """Test bulk review skips services with existing in-progress reviews."""
        from app.health_review_system.api.router import create_bulk_reviews

        workspace_id = mock_services[0].workspace_id

        # Mock fetching services
        mock_services_result = MagicMock()
        mock_services_result.scalars.return_value.all.return_value = mock_services

        # First service has existing review, others don't
        mock_existing = MagicMock()
        mock_existing.scalar_one_or_none.side_effect = [
            mock_review,  # First service has existing
            None,         # Others don't
            None,
            None,
        ]

        mock_db.execute = AsyncMock(
            side_effect=[mock_services_result, mock_existing, mock_existing, mock_existing, mock_existing]
        )

        with patch(
            "app.health_review_system.api.router.publish_health_review_job",
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await create_bulk_reviews(
                workspace_id=workspace_id,
                request=None,
                db=mock_db,
                current_user=mock_user,
            )

        assert response.queued_count == 3
        assert response.skipped_count == 1
        assert len(response.reviews) == 4

    @pytest.mark.asyncio
    async def test_bulk_review_with_custom_time_range(
        self, mock_db, mock_user, mock_services
    ):
        """Test bulk review with custom time range."""
        from app.health_review_system.api.router import create_bulk_reviews

        workspace_id = mock_services[0].workspace_id

        mock_services_result = MagicMock()
        mock_services_result.scalars.return_value.all.return_value = mock_services

        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(
            side_effect=[mock_services_result] + [mock_existing_result] * len(mock_services)
        )

        week_end = datetime.now(timezone.utc)
        week_start = week_end - timedelta(days=30)
        request = BulkCreateReviewRequest(week_start=week_start, week_end=week_end)

        with patch(
            "app.health_review_system.api.router.publish_health_review_job",
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await create_bulk_reviews(
                workspace_id=workspace_id,
                request=request,
                db=mock_db,
                current_user=mock_user,
            )

        assert response.queued_count == len(mock_services)


# =============================================================================
# Schema Tests
# =============================================================================


class TestSchemas:
    """Tests for request/response schemas."""

    def test_create_review_request_defaults(self):
        """Test CreateReviewRequest with defaults."""
        request = CreateReviewRequest()
        assert request.week_start is None
        assert request.week_end is None

    def test_create_review_request_with_values(self):
        """Test CreateReviewRequest with values."""
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        request = CreateReviewRequest(week_start=week_ago, week_end=now)
        assert request.week_start == week_ago
        assert request.week_end == now

    def test_bulk_review_item(self):
        """Test BulkReviewItem schema."""
        item = BulkReviewItem(
            service_id=uuid.uuid4(),
            service_name="test-service",
            review_id=uuid.uuid4(),
        )
        assert item.skipped is False
        assert item.reason is None

    def test_bulk_review_item_skipped(self):
        """Test BulkReviewItem with skipped status."""
        item = BulkReviewItem(
            service_id=uuid.uuid4(),
            service_name="test-service",
            skipped=True,
            reason="Review already in progress",
        )
        assert item.skipped is True
        assert item.review_id is None

    def test_bulk_create_review_response(self):
        """Test BulkCreateReviewResponse schema."""
        response = BulkCreateReviewResponse(
            queued_count=3,
            skipped_count=1,
            reviews=[
                BulkReviewItem(
                    service_id=uuid.uuid4(),
                    service_name="svc1",
                    review_id=uuid.uuid4(),
                ),
                BulkReviewItem(
                    service_id=uuid.uuid4(),
                    service_name="svc2",
                    skipped=True,
                    reason="Already in progress",
                ),
            ],
            message="3 services queued for review, 1 skipped",
        )
        assert response.queued_count == 3
        assert response.skipped_count == 1
        assert len(response.reviews) == 2


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestHelperFunctions:
    """Tests for helper functions."""

    @pytest.mark.asyncio
    async def test_check_existing_review_found(self, mock_db, mock_review):
        """Test _check_existing_review when review exists."""
        from app.health_review_system.api.router import _check_existing_review

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_review
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _check_existing_review(
            db=mock_db,
            service_id=mock_review.service_id,
            week_start=mock_review.review_week_start,
            week_end=mock_review.review_week_end,
        )

        assert result == mock_review

    @pytest.mark.asyncio
    async def test_check_existing_review_not_found(self, mock_db):
        """Test _check_existing_review when no review exists."""
        from app.health_review_system.api.router import _check_existing_review

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _check_existing_review(
            db=mock_db,
            service_id=str(uuid.uuid4()),
            week_start=datetime.now(timezone.utc) - timedelta(days=7),
            week_end=datetime.now(timezone.utc),
        )

        assert result is None
