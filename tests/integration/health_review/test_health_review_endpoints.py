"""
Integration tests for Health Review API endpoints.

Tests the full HTTP request/response cycle with real in-memory database.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import ReviewStatus, ServiceReview


# =============================================================================
# Single Service Review Endpoint Tests
# =============================================================================


class TestCreateReviewEndpoint:
    """Integration tests for POST /health-reviews/services/{service_id}/reviews"""

    @pytest.mark.asyncio
    async def test_create_review_success(
        self, auth_client, test_service, test_db, mock_sqs_publish
    ):
        """Test successful review creation via HTTP endpoint."""
        response = await auth_client.post(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews"
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "QUEUED"
        assert data["message"] == "Health review queued for processing"
        assert "review_id" in data

        # Verify review was created in database
        review = await test_db.get(ServiceReview, data["review_id"])
        assert review is not None
        assert review.service_id == test_service.id
        assert review.status == ReviewStatus.QUEUED

        # Verify SQS was called
        mock_sqs_publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_review_service_not_found(self, auth_client, mock_sqs_publish):
        """Test review creation with non-existent service."""
        fake_service_id = str(uuid.uuid4())
        response = await auth_client.post(
            f"/api/v1/health-reviews/services/{fake_service_id}/reviews"
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        mock_sqs_publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_review_with_custom_time_range(
        self, auth_client, test_service, test_db, mock_sqs_publish
    ):
        """Test review creation with custom time range."""
        week_end = datetime.now(timezone.utc)
        week_start = week_end - timedelta(days=14)

        response = await auth_client.post(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews",
            json={
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
            },
        )

        assert response.status_code == 202
        data = response.json()

        # Verify the time range was used
        review = await test_db.get(ServiceReview, data["review_id"])
        assert review is not None
        # Compare dates (ignoring microseconds)
        assert review.review_week_start.date() == week_start.date()
        assert review.review_week_end.date() == week_end.date()

    @pytest.mark.asyncio
    async def test_create_review_duplicate_prevention(
        self, auth_client, test_service, test_db, mock_sqs_publish
    ):
        """Test that duplicate reviews in same period are prevented."""
        # Use explicit timestamps to ensure both requests use same period
        week_end = datetime.now(timezone.utc).replace(microsecond=0)
        week_start = (week_end - timedelta(days=7)).replace(microsecond=0)
        time_range = {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
        }

        # First request - should succeed
        response1 = await auth_client.post(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews",
            json=time_range,
        )
        assert response1.status_code == 202
        first_review_id = response1.json()["review_id"]

        # Second request with same time range - should return existing review
        response2 = await auth_client.post(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews",
            json=time_range,
        )
        assert response2.status_code == 202
        data = response2.json()
        assert data["message"] == "Review already in progress for this period"
        assert data["review_id"] == first_review_id

    @pytest.mark.asyncio
    async def test_create_review_unauthorized(self, client, test_service):
        """Test review creation without authentication."""
        response = await client.post(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews"
        )

        # Should fail authentication
        assert response.status_code in [401, 403]


# =============================================================================
# Bulk Review Endpoint Tests
# =============================================================================


class TestBulkReviewEndpoint:
    """Integration tests for POST /health-reviews/workspaces/{workspace_id}/bulk-reviews"""

    @pytest.mark.asyncio
    async def test_bulk_review_success(
        self, auth_client, test_workspace, multiple_services, test_db, mock_sqs_publish
    ):
        """Test successful bulk review creation."""
        response = await auth_client.post(
            f"/api/v1/health-reviews/workspaces/{test_workspace.id}/bulk-reviews"
        )

        assert response.status_code == 202
        data = response.json()
        assert data["queued_count"] == 4
        assert data["skipped_count"] == 0
        assert len(data["reviews"]) == 4
        assert "4 services queued" in data["message"]

        # Verify all reviews were created in database
        for review_item in data["reviews"]:
            review = await test_db.get(ServiceReview, review_item["review_id"])
            assert review is not None
            assert review.status == ReviewStatus.QUEUED
            assert not review_item["skipped"]

        # Verify SQS was called for each service
        assert mock_sqs_publish.call_count == 4

    @pytest.mark.asyncio
    async def test_bulk_review_empty_workspace(
        self, auth_client, test_workspace, mock_sqs_publish
    ):
        """Test bulk review when workspace has no services."""
        response = await auth_client.post(
            f"/api/v1/health-reviews/workspaces/{test_workspace.id}/bulk-reviews"
        )

        assert response.status_code == 202
        data = response.json()
        assert data["queued_count"] == 0
        assert data["skipped_count"] == 0
        assert data["message"] == "No services found in workspace"
        mock_sqs_publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_review_skips_in_progress(
        self, auth_client, test_workspace, multiple_services, test_db, mock_sqs_publish
    ):
        """Test that bulk review skips services with existing in-progress reviews."""
        # Use explicit timestamps that match what bulk endpoint will calculate
        week_end = datetime.now(timezone.utc).replace(microsecond=0)
        week_start = (week_end - timedelta(days=7)).replace(microsecond=0)

        # Create an existing review for the first service with matching time range
        first_service = multiple_services[0]
        existing_review = ServiceReview(
            id=str(uuid.uuid4()),
            service_id=first_service.id,
            workspace_id=test_workspace.id,
            status=ReviewStatus.QUEUED,
            review_week_start=week_start,
            review_week_end=week_end,
        )
        test_db.add(existing_review)
        await test_db.commit()

        # Now trigger bulk review with same time range
        response = await auth_client.post(
            f"/api/v1/health-reviews/workspaces/{test_workspace.id}/bulk-reviews",
            json={
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["queued_count"] == 3  # 4 - 1 skipped
        assert data["skipped_count"] == 1

        # Find the skipped one
        skipped = [r for r in data["reviews"] if r["skipped"]]
        assert len(skipped) == 1
        assert skipped[0]["service_id"] == first_service.id
        assert "already in progress" in skipped[0]["reason"].lower()

    @pytest.mark.asyncio
    async def test_bulk_review_with_custom_time_range(
        self, auth_client, test_workspace, multiple_services, test_db, mock_sqs_publish
    ):
        """Test bulk review with custom time range."""
        week_end = datetime.now(timezone.utc)
        week_start = week_end - timedelta(days=30)

        response = await auth_client.post(
            f"/api/v1/health-reviews/workspaces/{test_workspace.id}/bulk-reviews",
            json={
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["queued_count"] == 4

        # Verify time range was applied
        review = await test_db.get(ServiceReview, data["reviews"][0]["review_id"])
        assert review.review_week_start.date() == week_start.date()
        assert review.review_week_end.date() == week_end.date()

    @pytest.mark.asyncio
    async def test_bulk_review_unauthorized(self, client, test_workspace):
        """Test bulk review without authentication."""
        response = await client.post(
            f"/api/v1/health-reviews/workspaces/{test_workspace.id}/bulk-reviews"
        )

        assert response.status_code in [401, 403]


# =============================================================================
# List Reviews Endpoint Tests
# =============================================================================


class TestListReviewsEndpoint:
    """Integration tests for GET /health-reviews/services/{service_id}/reviews"""

    @pytest.mark.asyncio
    async def test_list_reviews_success(
        self, auth_client, test_service, test_db, mock_sqs_publish
    ):
        """Test listing reviews for a service."""
        # First create a review
        await auth_client.post(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews"
        )

        # Now list reviews
        response = await auth_client.get(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["reviews"]) >= 1
        assert data["reviews"][0]["service_id"] == test_service.id

    @pytest.mark.asyncio
    async def test_list_reviews_empty(self, auth_client, test_service):
        """Test listing reviews when none exist."""
        response = await auth_client.get(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["reviews"] == []

    @pytest.mark.asyncio
    async def test_list_reviews_pagination(
        self, auth_client, test_service, test_db, mock_sqs_publish
    ):
        """Test pagination when listing reviews."""
        # Create multiple reviews with different time periods
        for i in range(8):
            now = datetime.now(timezone.utc) - timedelta(days=i * 7)
            review = ServiceReview(
                id=str(uuid.uuid4()),
                service_id=test_service.id,
                workspace_id=test_service.workspace_id,
                status=ReviewStatus.COMPLETED,
                review_week_start=now - timedelta(days=7),
                review_week_end=now,
            )
            test_db.add(review)
        await test_db.commit()

        # Test default limit (should be 6)
        response = await auth_client.get(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 8
        assert len(data["reviews"]) == 6  # Default limit is 6

        # Test custom pagination
        response = await auth_client.get(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews?limit=2&offset=0"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 8
        assert len(data["reviews"]) == 2

    @pytest.mark.asyncio
    async def test_list_reviews_status_filter(
        self, auth_client, test_service, test_db, mock_sqs_publish
    ):
        """Test filtering reviews by status."""
        # Create reviews with different statuses
        for status in [ReviewStatus.COMPLETED, ReviewStatus.COMPLETED, ReviewStatus.FAILED]:
            now = datetime.now(timezone.utc)
            review = ServiceReview(
                id=str(uuid.uuid4()),
                service_id=test_service.id,
                workspace_id=test_service.workspace_id,
                status=status,
                review_week_start=now - timedelta(days=7),
                review_week_end=now,
            )
            test_db.add(review)
        await test_db.commit()

        # Filter by COMPLETED status
        response = await auth_client.get(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews?status_filter=COMPLETED"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert all(r["status"] == "COMPLETED" for r in data["reviews"])

        # Filter by FAILED status
        response = await auth_client.get(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews?status_filter=FAILED"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["reviews"][0]["status"] == "FAILED"


# =============================================================================
# Get Review Detail Endpoint Tests
# =============================================================================


class TestGetReviewEndpoint:
    """Integration tests for GET /health-reviews/reviews/{review_id}"""

    @pytest.mark.asyncio
    async def test_get_review_success(
        self, auth_client, test_service, test_db, mock_sqs_publish
    ):
        """Test getting review details."""
        # Create a review
        create_response = await auth_client.post(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews"
        )
        review_id = create_response.json()["review_id"]

        # Get review details
        response = await auth_client.get(f"/api/v1/health-reviews/reviews/{review_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == review_id
        assert data["service_id"] == test_service.id
        assert data["status"] == "QUEUED"

    @pytest.mark.asyncio
    async def test_get_review_not_found(self, auth_client):
        """Test getting non-existent review."""
        fake_review_id = str(uuid.uuid4())
        response = await auth_client.get(
            f"/api/v1/health-reviews/reviews/{fake_review_id}"
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_review_with_include_all(
        self, auth_client, test_service, test_db, mock_sqs_publish
    ):
        """Test getting review with include=all returns inline child records."""
        # Create a review
        create_response = await auth_client.post(
            f"/api/v1/health-reviews/services/{test_service.id}/reviews"
        )
        review_id = create_response.json()["review_id"]

        # Get review without include - should not have child arrays
        response = await auth_client.get(f"/api/v1/health-reviews/reviews/{review_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["errors"] is None
        assert data["slis"] is None

        # Get review with include=all - should have child arrays (empty but present)
        response = await auth_client.get(
            f"/api/v1/health-reviews/reviews/{review_id}?include=all"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["errors"] == []  # Empty list, not None
        assert data["slis"] == []


# =============================================================================
# Workspace Reviews Endpoint Tests
# =============================================================================


class TestGetWorkspaceReviewsEndpoint:
    """Integration tests for GET /health-reviews/workspaces/{workspace_id}/reviews"""

    @pytest.mark.asyncio
    async def test_get_workspace_reviews_success(
        self, auth_client, test_workspace, multiple_services, test_db, mock_sqs_publish
    ):
        """Test getting workspace reviews after creating reviews for services."""
        # Create reviews for some services
        for service in multiple_services[:2]:
            await auth_client.post(
                f"/api/v1/health-reviews/services/{service.id}/reviews"
            )

        # Get workspace reviews
        response = await auth_client.get(
            f"/api/v1/health-reviews/workspaces/{test_workspace.id}/reviews"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["workspace_id"] == test_workspace.id
        assert data["total_services"] == 4  # multiple_services creates 4 services
        assert data["services_with_reviews"] == 2
        assert len(data["reviews"]) == 2

        # Verify review structure
        for review in data["reviews"]:
            assert "id" in review
            assert "service_id" in review
            assert "service_name" in review
            assert "status" in review
            assert review["status"] == "QUEUED"

    @pytest.mark.asyncio
    async def test_get_workspace_reviews_empty(self, auth_client, test_workspace):
        """Test getting workspace reviews when no services exist."""
        response = await auth_client.get(
            f"/api/v1/health-reviews/workspaces/{test_workspace.id}/reviews"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["workspace_id"] == test_workspace.id
        assert data["total_services"] == 0
        assert data["services_with_reviews"] == 0
        assert data["reviews"] == []

    @pytest.mark.asyncio
    async def test_get_workspace_reviews_no_reviews_yet(
        self, auth_client, test_workspace, multiple_services
    ):
        """Test getting workspace reviews when services exist but no reviews created."""
        response = await auth_client.get(
            f"/api/v1/health-reviews/workspaces/{test_workspace.id}/reviews"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["workspace_id"] == test_workspace.id
        assert data["total_services"] == 4
        assert data["services_with_reviews"] == 0
        assert data["reviews"] == []

    @pytest.mark.asyncio
    async def test_get_workspace_reviews_latest_only(
        self, auth_client, test_workspace, test_service, test_db, mock_sqs_publish
    ):
        """Test that only the latest review per service is returned."""
        # Create multiple reviews for the same service with different time ranges
        for i in range(3):
            week_end = datetime.now(timezone.utc) - timedelta(days=i * 7)
            week_start = week_end - timedelta(days=7)
            review = ServiceReview(
                id=str(uuid.uuid4()),
                service_id=test_service.id,
                workspace_id=test_workspace.id,
                status=ReviewStatus.COMPLETED,
                review_week_start=week_start,
                review_week_end=week_end,
            )
            test_db.add(review)
        await test_db.commit()

        # Get workspace reviews
        response = await auth_client.get(
            f"/api/v1/health-reviews/workspaces/{test_workspace.id}/reviews"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["services_with_reviews"] == 1
        assert len(data["reviews"]) == 1  # Only latest review returned

    @pytest.mark.asyncio
    async def test_get_workspace_reviews_unauthorized(self, client, test_workspace):
        """Test workspace reviews without authentication."""
        response = await client.get(
            f"/api/v1/health-reviews/workspaces/{test_workspace.id}/reviews"
        )

        assert response.status_code in [401, 403]
