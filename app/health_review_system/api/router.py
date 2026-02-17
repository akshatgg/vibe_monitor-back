"""
Health Review API Router.

Provides endpoints for:
- Creating health reviews (triggers async processing)
- Listing reviews for a service
- Getting review details
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google.service import AuthService
from app.core.database import get_db
from app.health_review_system.api.schemas import (
    BulkCreateReviewRequest,
    BulkCreateReviewResponse,
    BulkReviewItem,
    CreateReviewRequest,
    CreateReviewResponse,
    GapCategoryInfo,
    LOGGING_GAP_CATEGORY_LABELS,
    LoggingGapResponse,
    METRICS_GAP_CATEGORY_LABELS,
    MetricsGapResponse,
    PaginatedLoggingGapsResponse,
    PaginatedMetricsGapsResponse,
    ReviewDetail,
    ReviewErrorResponse,
    ReviewListResponse,
    ReviewScheduleResponse,
    ReviewSummary,
    ServiceReviewSummary,
    SLIResponse,
    UpdateReviewScheduleRequest,
    WorkspaceReviewsResponse,
)
from app.models import (
    ReviewError,
    ReviewLoggingGap,
    ReviewMetricsGap,
    ReviewSchedule,
    ReviewSLI,
    ReviewStatus,
    ReviewTriggeredBy,
    Service,
    ServiceReview,
    User,
)
from app.workers.health_review_worker import publish_health_review_job
from app.email_service.service import verify_scheduler_token
from app.health_review_system.scheduler.service import health_review_scheduler

logger = logging.getLogger(__name__)
auth_service = AuthService()

router = APIRouter(prefix="/health-reviews", tags=["health-reviews"])


@router.post(
    "/services/{service_id}/reviews",
    response_model=CreateReviewResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_review(
    service_id: str,
    request: CreateReviewRequest = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Trigger a health review for a service.

    Creates a ServiceReview record and publishes a job to the SQS queue
    for async processing.

    Args:
        service_id: The service ID to review
        request: Optional time range for the review

    Returns:
        CreateReviewResponse with the review_id and status
    """
    # Fetch the service
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service {service_id} not found",
        )

    # Calculate review period (default: last 7 days)
    now = datetime.now(timezone.utc)
    if request and request.week_end:
        week_end = request.week_end
    else:
        week_end = now

    if request and request.week_start:
        week_start = request.week_start
    else:
        week_start = week_end - timedelta(days=7)

    # Check for existing review in same period (QUEUED, GENERATING, or COMPLETED)
    # Only allow new review if previous one FAILED
    existing_stmt = (
        select(ServiceReview)
        .where(ServiceReview.service_id == service_id)
        .where(ServiceReview.review_week_start == week_start)
        .where(ServiceReview.review_week_end == week_end)
        .where(ServiceReview.status.in_([ReviewStatus.QUEUED, ReviewStatus.GENERATING, ReviewStatus.COMPLETED]))
        .order_by(ServiceReview.created_at.desc())
        .limit(1)
    )
    existing_result = await db.execute(existing_stmt)
    existing_review = existing_result.scalar_one_or_none()

    if existing_review:
        if existing_review.status == ReviewStatus.COMPLETED:
            return CreateReviewResponse(
                review_id=existing_review.id,
                status=existing_review.status.value,
                message="Review already exists for this period",
            )
        return CreateReviewResponse(
            review_id=existing_review.id,
            status=existing_review.status.value,
            message="Review already in progress for this period",
        )

    # Create new review
    review_id = str(uuid.uuid4())
    review = ServiceReview(
        id=review_id,
        service_id=service_id,
        workspace_id=service.workspace_id,
        status=ReviewStatus.QUEUED,
        triggered_by=ReviewTriggeredBy.API,
        review_week_start=week_start,
        review_week_end=week_end,
    )
    db.add(review)
    await db.commit()

    # Publish job to SQS
    published = await publish_health_review_job(
        review_id=review_id,
        workspace_id=service.workspace_id,
        service_id=service_id,
    )

    if not published:
        logger.error(f"Failed to publish health review job for review {review_id}")
        # Still return success - the review is created, worker can pick it up
        # via polling or retry mechanism

    logger.info(f"Created health review {review_id} for service {service_id}")

    return CreateReviewResponse(
        review_id=uuid.UUID(review_id),
        status=ReviewStatus.QUEUED.value,
        message="Health review queued for processing",
    )


@router.get(
    "/services/{service_id}/reviews",
    response_model=ReviewListResponse,
)
async def list_reviews(
    service_id: str,
    limit: int = 6,
    offset: int = 0,
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    List health reviews for a service.

    Args:
        service_id: The service ID
        limit: Max reviews to return (default 6)
        offset: Pagination offset
        status_filter: Optional filter by status (QUEUED, GENERATING, COMPLETED, FAILED)

    Returns:
        List of review summaries
    """
    # Verify service exists
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service {service_id} not found",
        )

    # Build base query conditions
    conditions = [ServiceReview.service_id == service_id]

    # Apply status filter if provided
    if status_filter:
        try:
            status_enum = ReviewStatus(status_filter.upper())
            conditions.append(ServiceReview.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}. Valid values: QUEUED, GENERATING, COMPLETED, FAILED",
            )

    # Subquery to get the latest review ID for each unique week
    # This deduplicates reviews so we only show one per week
    latest_per_week = (
        select(
            ServiceReview.review_week_start,
            ServiceReview.review_week_end,
            func.max(ServiceReview.created_at).label("max_created")
        )
        .where(*conditions)
        .group_by(ServiceReview.review_week_start, ServiceReview.review_week_end)
        .subquery()
    )

    # Get total count of unique weeks
    count_stmt = select(func.count()).select_from(latest_per_week)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar()

    # Get reviews - join with subquery to get only latest per week
    stmt = (
        select(ServiceReview)
        .join(
            latest_per_week,
            (ServiceReview.review_week_start == latest_per_week.c.review_week_start)
            & (ServiceReview.review_week_end == latest_per_week.c.review_week_end)
            & (ServiceReview.created_at == latest_per_week.c.max_created)
        )
        .where(*conditions)
        .order_by(ServiceReview.review_week_start.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    reviews = result.scalars().all()

    # Build response
    summaries = []
    for review in reviews:
        # Get gap counts
        logging_gaps_count = await db.scalar(
            select(func.count())
            .select_from(ReviewLoggingGap)
            .where(ReviewLoggingGap.review_id == review.id)
        )
        metrics_gaps_count = await db.scalar(
            select(func.count())
            .select_from(ReviewMetricsGap)
            .where(ReviewMetricsGap.review_id == review.id)
        )

        summaries.append(
            ReviewSummary(
                id=review.id,
                service_id=review.service_id,
                service_name=service.name,
                status=review.status.value,
                overall_health_score=review.overall_health_score,
                review_week_start=review.review_week_start,
                review_week_end=review.review_week_end,
                generated_at=review.generated_at,
                error_count_analyzed=review.error_count_analyzed,
                logging_gaps_count=logging_gaps_count,
                metrics_gaps_count=metrics_gaps_count,
            )
        )

    return ReviewListResponse(reviews=summaries, total=total)


@router.get(
    "/reviews/{review_id}",
    response_model=ReviewDetail,
)
async def get_review(
    review_id: str,
    include: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Get detailed health review.

    Args:
        review_id: The review ID
        include: Optional - pass "all" to include child records (logging_gaps, metrics_gaps, slis) inline

    Returns:
        Full review details, optionally with child records inline
    """
    review = await db.get(ServiceReview, review_id)
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found",
        )

    service = await db.get(Service, review.service_id)

    # Get counts

    logging_gaps_count = await db.scalar(
        select(func.count())
        .select_from(ReviewLoggingGap)
        .where(ReviewLoggingGap.review_id == review_id)
    )
    metrics_gaps_count = await db.scalar(
        select(func.count())
        .select_from(ReviewMetricsGap)
        .where(ReviewMetricsGap.review_id == review_id)
    )
    slis_count = await db.scalar(
        select(func.count())
        .select_from(ReviewSLI)
        .where(ReviewSLI.review_id == review_id)
    )

    # Build base response
    response = ReviewDetail(
        id=review.id,
        service_id=review.service_id,
        service_name=service.name if service else "Unknown",
        status=review.status.value,
        overall_health_score=review.overall_health_score,
        summary=review.summary,
        recommendations=review.recommendations,
        review_week_start=review.review_week_start,
        review_week_end=review.review_week_end,
        generated_at=review.generated_at,
        generation_duration_seconds=review.generation_duration_seconds,
        analyzed_commit_sha=review.analyzed_commit_sha,
        codebase_changed=review.codebase_changed,
        error_count_analyzed=review.error_count_analyzed,
        log_volume_analyzed=review.log_volume_analyzed,
        metric_count_analyzed=review.metric_count_analyzed,
        errors_count=review.error_count_analyzed or 0,
        logging_gaps_count=logging_gaps_count,
        metrics_gaps_count=metrics_gaps_count,
        slis_count=slis_count,
    )

    # Include child records if requested
    # Note: logging_gaps and metrics_gaps are now served via their own paginated endpoints
    if include and include.lower() == "all":
        # Fetch errors
        errors_stmt = select(ReviewError).where(ReviewError.review_id == review_id)
        errors_result = await db.execute(errors_stmt)
        errors = errors_result.scalars().all()
        response.errors = [
            ReviewErrorResponse(
                id=err.id,
                error_type=err.error_type,
                error_fingerprint=err.error_fingerprint,
                occurrence_count=err.occurrence_count,
                error_message_sample=err.error_message_sample,
                stack_trace_sample=err.stack_trace_sample,
            )
            for err in errors
        ]

        # Fetch SLIs
        slis_stmt = select(ReviewSLI).where(ReviewSLI.review_id == review_id)
        slis_result = await db.execute(slis_stmt)
        slis = slis_result.scalars().all()
        response.slis = [
            SLIResponse(
                id=sli.id,
                sli_name=sli.sli_name,
                sli_category=sli.sli_category,
                score=sli.score,
                previous_week_score=sli.previous_week_score,
                score_trend=sli.score_trend.value if sli.score_trend else None,
                target_value=sli.target_value,
                actual_value=sli.actual_value,
                measurement_unit=sli.measurement_unit,
                analysis=sli.analysis,
            )
            for sli in slis
        ]

    return response


@router.get(
    "/reviews/{review_id}/logging-gaps",
    response_model=PaginatedLoggingGapsResponse,
)
async def get_logging_gaps(
    review_id: str,
    category: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """Get paginated logging gaps for a review, filtered by category."""
    # Get all categories with counts for this review
    cat_stmt = (
        select(
            ReviewLoggingGap.gap_category,
            func.count().label("cnt"),
        )
        .where(ReviewLoggingGap.review_id == review_id)
        .group_by(ReviewLoggingGap.gap_category)
        .order_by(ReviewLoggingGap.gap_category)
    )
    cat_result = await db.execute(cat_stmt)
    cat_rows = cat_result.all()

    categories = [
        GapCategoryInfo(
            value=row[0] or "uncategorized",
            label=LOGGING_GAP_CATEGORY_LABELS.get(row[0], row[0] or "Uncategorized"),
            count=row[1],
        )
        for row in cat_rows
    ]

    # Auto-select first category if none specified
    if not category and categories:
        category = categories[0].value

    # Query filtered + paginated gaps
    gaps_stmt = (
        select(ReviewLoggingGap)
        .where(ReviewLoggingGap.review_id == review_id)
    )
    if category:
        gaps_stmt = gaps_stmt.where(ReviewLoggingGap.gap_category == category)

    # Total count for this filter
    count_stmt = select(func.count()).select_from(gaps_stmt.subquery())
    total = await db.scalar(count_stmt)

    # Fetch page
    gaps_stmt = gaps_stmt.order_by(ReviewLoggingGap.priority).offset(offset).limit(limit)
    result = await db.execute(gaps_stmt)
    gaps = result.scalars().all()

    return PaginatedLoggingGapsResponse(
        gaps=[
            LoggingGapResponse(
                id=gap.id,
                gap_description=gap.gap_description,
                gap_category=gap.gap_category,
                priority=gap.priority.value,
                affected_files=gap.affected_files,
                affected_functions=gap.affected_functions,
                suggested_log_statement=gap.suggested_log_statement,
                rationale=gap.rationale,
                pr_status=gap.pr_status.value,
                acknowledged=gap.acknowledged,
                acknowledged_at=gap.acknowledged_at,
                acknowledged_by_user_id=gap.acknowledged_by_user_id,
            )
            for gap in gaps
        ],
        total=total,
        categories=categories,
    )


@router.get(
    "/reviews/{review_id}/metrics-gaps",
    response_model=PaginatedMetricsGapsResponse,
)
async def get_metrics_gaps(
    review_id: str,
    category: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """Get paginated metrics gaps for a review, filtered by category."""
    # Get all categories with counts for this review
    cat_stmt = (
        select(
            ReviewMetricsGap.gap_category,
            func.count().label("cnt"),
        )
        .where(ReviewMetricsGap.review_id == review_id)
        .group_by(ReviewMetricsGap.gap_category)
        .order_by(ReviewMetricsGap.gap_category)
    )
    cat_result = await db.execute(cat_stmt)
    cat_rows = cat_result.all()

    categories = [
        GapCategoryInfo(
            value=row[0] or "uncategorized",
            label=METRICS_GAP_CATEGORY_LABELS.get(row[0], row[0] or "Uncategorized"),
            count=row[1],
        )
        for row in cat_rows
    ]

    # Auto-select first category if none specified
    if not category and categories:
        category = categories[0].value

    # Query filtered + paginated gaps
    gaps_stmt = (
        select(ReviewMetricsGap)
        .where(ReviewMetricsGap.review_id == review_id)
    )
    if category:
        gaps_stmt = gaps_stmt.where(ReviewMetricsGap.gap_category == category)

    # Total count for this filter
    count_stmt = select(func.count()).select_from(gaps_stmt.subquery())
    total = await db.scalar(count_stmt)

    # Fetch page
    gaps_stmt = gaps_stmt.order_by(ReviewMetricsGap.priority).offset(offset).limit(limit)
    result = await db.execute(gaps_stmt)
    gaps = result.scalars().all()

    return PaginatedMetricsGapsResponse(
        gaps=[
            MetricsGapResponse(
                id=gap.id,
                gap_description=gap.gap_description,
                gap_category=gap.gap_category,
                metric_type=gap.metric_type,
                priority=gap.priority.value,
                affected_components=gap.affected_components,
                suggested_metric_names=gap.suggested_metric_names,
                implementation_guide=gap.implementation_guide,
                example_code=gap.example_code,
                pr_status=gap.pr_status.value,
                acknowledged=gap.acknowledged,
                acknowledged_at=gap.acknowledged_at,
                acknowledged_by_user_id=gap.acknowledged_by_user_id,
            )
            for gap in gaps
        ],
        total=total,
        categories=categories,
    )


# ========== Acknowledge Gap Endpoints ==========


@router.post(
    "/reviews/{review_id}/logging-gaps/{gap_id}/acknowledge",
    response_model=LoggingGapResponse,
)
async def acknowledge_logging_gap(
    review_id: str,
    gap_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Acknowledge a logging gap.

    Marks the gap as acknowledged by the current user with timestamp.

    Args:
        review_id: The review ID
        gap_id: The logging gap ID

    Returns:
        Updated LoggingGapResponse
    """
    # Verify review exists
    review = await db.get(ServiceReview, review_id)
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found",
        )

    # Fetch the gap
    gap = await db.get(ReviewLoggingGap, gap_id)
    if not gap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Logging gap {gap_id} not found",
        )

    # Verify gap belongs to this review
    if str(gap.review_id) != review_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Logging gap {gap_id} does not belong to review {review_id}",
        )

    # Update acknowledgment fields
    gap.acknowledged = True
    gap.acknowledged_at = datetime.now(timezone.utc)
    gap.acknowledged_by_user_id = current_user.id

    await db.commit()
    await db.refresh(gap)

    logger.info(
        f"Logging gap {gap_id} acknowledged by user {current_user.id} for review {review_id}"
    )

    return LoggingGapResponse(
        id=gap.id,
        gap_description=gap.gap_description,
        gap_category=gap.gap_category,
        priority=gap.priority.value,
        affected_files=gap.affected_files,
        affected_functions=gap.affected_functions,
        suggested_log_statement=gap.suggested_log_statement,
        rationale=gap.rationale,
        pr_status=gap.pr_status.value,
        acknowledged=gap.acknowledged,
        acknowledged_at=gap.acknowledged_at,
        acknowledged_by_user_id=gap.acknowledged_by_user_id,
    )


@router.post(
    "/reviews/{review_id}/metrics-gaps/{gap_id}/acknowledge",
    response_model=MetricsGapResponse,
)
async def acknowledge_metrics_gap(
    review_id: str,
    gap_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Acknowledge a metrics gap.

    Marks the gap as acknowledged by the current user with timestamp.

    Args:
        review_id: The review ID
        gap_id: The metrics gap ID

    Returns:
        Updated MetricsGapResponse
    """
    # Verify review exists
    review = await db.get(ServiceReview, review_id)
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found",
        )

    # Fetch the gap
    gap = await db.get(ReviewMetricsGap, gap_id)
    if not gap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Metrics gap {gap_id} not found",
        )

    # Verify gap belongs to this review
    if str(gap.review_id) != review_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Metrics gap {gap_id} does not belong to review {review_id}",
        )

    # Update acknowledgment fields
    gap.acknowledged = True
    gap.acknowledged_at = datetime.now(timezone.utc)
    gap.acknowledged_by_user_id = current_user.id

    await db.commit()
    await db.refresh(gap)

    logger.info(
        f"Metrics gap {gap_id} acknowledged by user {current_user.id} for review {review_id}"
    )

    return MetricsGapResponse(
        id=gap.id,
        gap_description=gap.gap_description,
        gap_category=gap.gap_category,
        metric_type=gap.metric_type,
        priority=gap.priority.value,
        affected_components=gap.affected_components,
        suggested_metric_names=gap.suggested_metric_names,
        implementation_guide=gap.implementation_guide,
        example_code=gap.example_code,
        pr_status=gap.pr_status.value,
        acknowledged=gap.acknowledged,
        acknowledged_at=gap.acknowledged_at,
        acknowledged_by_user_id=gap.acknowledged_by_user_id,
    )


@router.get(
    "/reviews/{review_id}/slis",
    response_model=List[SLIResponse],
)
async def get_slis(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """Get SLIs for a review."""
    stmt = select(ReviewSLI).where(ReviewSLI.review_id == review_id)
    result = await db.execute(stmt)
    slis = result.scalars().all()

    return [
        SLIResponse(
            id=sli.id,
            sli_name=sli.sli_name,
            sli_category=sli.sli_category,
            score=sli.score,
            previous_week_score=sli.previous_week_score,
            score_trend=sli.score_trend.value if sli.score_trend else None,
            target_value=sli.target_value,
            actual_value=sli.actual_value,
            measurement_unit=sli.measurement_unit,
            analysis=sli.analysis,
        )
        for sli in slis
    ]


@router.get(
    "/reviews/{review_id}/errors",
    response_model=List[ReviewErrorResponse],
)
async def get_errors(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """Get errors for a review."""
    stmt = select(ReviewError).where(ReviewError.review_id == review_id)
    result = await db.execute(stmt)
    errors = result.scalars().all()

    return [
        ReviewErrorResponse(
            id=err.id,
            error_type=err.error_type,
            error_fingerprint=err.error_fingerprint,
            occurrence_count=err.occurrence_count,
            error_message_sample=err.error_message_sample,
            stack_trace_sample=err.stack_trace_sample,
        )
        for err in errors
    ]


# ========== Bulk Review Endpoints ==========


async def _check_existing_review(
    db: AsyncSession,
    service_id: str,
    week_start: datetime,
    week_end: datetime,
) -> Optional[ServiceReview]:
    """Check for existing in-progress review for a service and period."""
    stmt = (
        select(ServiceReview)
        .where(ServiceReview.service_id == service_id)
        .where(ServiceReview.review_week_start == week_start)
        .where(ServiceReview.review_week_end == week_end)
        .where(ServiceReview.status.in_([ReviewStatus.QUEUED, ReviewStatus.GENERATING]))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.post(
    "/workspaces/{workspace_id}/bulk-reviews",
    response_model=BulkCreateReviewResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_bulk_reviews(
    workspace_id: str,
    request: BulkCreateReviewRequest = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Trigger health reviews for all services in a workspace.

    Creates ServiceReview records for each service and publishes jobs to the
    SQS queue for async processing. Each service is processed independently.

    Args:
        workspace_id: The workspace ID
        request: Optional time range for the reviews

    Returns:
        BulkCreateReviewResponse with list of review_ids and counts
    """
    # Fetch all services for the workspace
    stmt = select(Service).where(Service.workspace_id == workspace_id)
    result = await db.execute(stmt)
    services = result.scalars().all()

    if not services:
        return BulkCreateReviewResponse(
            queued_count=0,
            skipped_count=0,
            reviews=[],
            message="No services found in workspace",
        )

    # Calculate review period (default: last 7 days)
    now = datetime.now(timezone.utc)
    if request and request.week_end:
        week_end = request.week_end
    else:
        week_end = now

    if request and request.week_start:
        week_start = request.week_start
    else:
        week_start = week_end - timedelta(days=7)

    reviews = []
    queued = 0
    skipped = 0

    # Process each service
    for service in services:
        # Check for existing in-progress review
        existing = await _check_existing_review(db, service.id, week_start, week_end)
        if existing:
            reviews.append(
                BulkReviewItem(
                    service_id=service.id,
                    service_name=service.name,
                    review_id=existing.id,
                    skipped=True,
                    reason="Review already in progress for this period",
                )
            )
            skipped += 1
            continue

        # Create new review
        review_id = str(uuid.uuid4())
        review = ServiceReview(
            id=review_id,
            service_id=service.id,
            workspace_id=workspace_id,
            status=ReviewStatus.QUEUED,
            triggered_by=ReviewTriggeredBy.API,
            review_week_start=week_start,
            review_week_end=week_end,
        )
        db.add(review)

        reviews.append(
            BulkReviewItem(
                service_id=service.id,
                service_name=service.name,
                review_id=review_id,
            )
        )
        queued += 1

    # Commit all reviews in single transaction
    await db.commit()

    # Publish jobs to SQS for each queued review
    for item in reviews:
        if not item.skipped:
            published = await publish_health_review_job(
                review_id=str(item.review_id),
                workspace_id=workspace_id,
                service_id=str(item.service_id),
            )
            if not published:
                logger.error(
                    f"Failed to publish health review job for service {item.service_name}"
                )

    logger.info(
        f"Bulk health review: {queued} services queued, {skipped} skipped for workspace {workspace_id}"
    )

    return BulkCreateReviewResponse(
        queued_count=queued,
        skipped_count=skipped,
        reviews=reviews,
        message=f"{queued} services queued for review, {skipped} skipped",
    )


# ========== Workspace Reviews Endpoint (for Frontend) ==========


@router.get(
    "/workspaces/{workspace_id}/reviews",
    response_model=WorkspaceReviewsResponse,
)
async def get_workspace_reviews(
    workspace_id: str,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Get the latest health reviews for all services in a workspace.

    Returns the most recent review for each service, allowing the frontend
    to display a dashboard view of all service health statuses.

    Args:
        workspace_id: The workspace ID
        limit: Max reviews per service to return (default 10, typically 1 for latest)

    Returns:
        WorkspaceReviewsResponse with reviews for all services in the workspace
    """
    # Fetch all services for the workspace
    services_stmt = select(Service).where(Service.workspace_id == workspace_id)
    services_result = await db.execute(services_stmt)
    services = services_result.scalars().all()

    if not services:
        return WorkspaceReviewsResponse(
            workspace_id=workspace_id,
            total_services=0,
            services_with_reviews=0,
            reviews=[],
        )

    # Build a map of service_id -> service for quick lookup
    service_map = {service.id: service for service in services}
    service_ids = list(service_map.keys())

    # Get the latest review for each service (subquery for most recent per service)
    # Using a window function approach to get the latest review per service
    # Fetch latest reviews for each service
    reviews_stmt = (
        select(ServiceReview)
        .where(ServiceReview.service_id.in_(service_ids))
        .order_by(ServiceReview.service_id, desc(ServiceReview.review_week_end))
    )
    reviews_result = await db.execute(reviews_stmt)
    all_reviews = reviews_result.scalars().all()

    # Group reviews by service and take the latest
    service_reviews = {}
    for review in all_reviews:
        if review.service_id not in service_reviews:
            service_reviews[review.service_id] = review

    # Build response with gap counts
    review_summaries = []
    for service_id, review in service_reviews.items():
        service = service_map.get(service_id)
        if not service:
            continue

        # Get gap counts
        logging_gaps_count = await db.scalar(
            select(func.count())
            .select_from(ReviewLoggingGap)
            .where(ReviewLoggingGap.review_id == review.id)
        )
        metrics_gaps_count = await db.scalar(
            select(func.count())
            .select_from(ReviewMetricsGap)
            .where(ReviewMetricsGap.review_id == review.id)
        )
        slis_count = await db.scalar(
            select(func.count())
            .select_from(ReviewSLI)
            .where(ReviewSLI.review_id == review.id)
        )

        review_summaries.append(
            ServiceReviewSummary(
                id=review.id,
                service_id=review.service_id,
                service_name=service.name,
                status=review.status.value,
                overall_health_score=review.overall_health_score,
                summary=review.summary,
                review_week_start=review.review_week_start,
                review_week_end=review.review_week_end,
                generated_at=review.generated_at,
                triggered_by=review.triggered_by.value if review.triggered_by else None,
                error_count_analyzed=review.error_count_analyzed,
                logging_gaps_count=logging_gaps_count or 0,
                metrics_gaps_count=metrics_gaps_count or 0,
                slis_count=slis_count or 0,
            )
        )

    # Sort by service name for consistent ordering
    review_summaries.sort(key=lambda r: r.service_name)

    return WorkspaceReviewsResponse(
        workspace_id=workspace_id,
        total_services=len(services),
        services_with_reviews=len(service_reviews),
        reviews=review_summaries,
    )


# ========== Review Schedule Endpoints ==========


@router.get(
    "/services/{service_id}/schedule",
    response_model=ReviewScheduleResponse,
)
async def get_review_schedule(
    service_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Get the review schedule settings for a service.

    Args:
        service_id: The service ID

    Returns:
        ReviewScheduleResponse with schedule settings
    """
    # Verify service exists
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service {service_id} not found",
        )

    # Get schedule
    stmt = select(ReviewSchedule).where(ReviewSchedule.service_id == service_id)
    result = await db.execute(stmt)
    schedule = result.scalar_one_or_none()

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review schedule not found for service {service_id}",
        )

    return ReviewScheduleResponse(
        id=schedule.id,
        service_id=schedule.service_id,
        enabled=schedule.enabled,
        frequency=schedule.frequency,
        generation_day_of_week=schedule.generation_day_of_week,
        generation_hour_utc=schedule.generation_hour_utc,
        timezone=schedule.timezone,
        next_scheduled_at=schedule.next_scheduled_at,
        last_review_generated_at=schedule.last_review_generated_at,
        last_review_status=schedule.last_review_status,
        consecutive_failures=schedule.consecutive_failures,
    )


@router.patch(
    "/services/{service_id}/schedule",
    response_model=ReviewScheduleResponse,
)
async def update_review_schedule(
    service_id: str,
    request: UpdateReviewScheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Update the review schedule settings for a service.

    Users can:
    - Enable/disable automated reviews
    - Change the day and hour for weekly reviews

    Args:
        service_id: The service ID
        request: Update request with new settings

    Returns:
        Updated ReviewScheduleResponse
    """
    # Verify service exists
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service {service_id} not found",
        )

    # Get schedule
    stmt = select(ReviewSchedule).where(ReviewSchedule.service_id == service_id)
    result = await db.execute(stmt)
    schedule = result.scalar_one_or_none()

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review schedule not found for service {service_id}",
        )

    # Update fields if provided
    schedule_changed = False

    if request.enabled is not None:
        schedule.enabled = request.enabled
        schedule_changed = True
        logger.info(
            f"Review schedule for service {service_id} {'enabled' if request.enabled else 'disabled'}"
        )

    if request.generation_day_of_week is not None:
        schedule.generation_day_of_week = request.generation_day_of_week
        schedule_changed = True

    if request.generation_hour_utc is not None:
        schedule.generation_hour_utc = request.generation_hour_utc
        schedule_changed = True

    # Recalculate next_scheduled_at if schedule timing changed
    if schedule_changed and schedule.enabled:
        now = datetime.now(timezone.utc)
        day_of_week = schedule.generation_day_of_week
        hour_utc = schedule.generation_hour_utc

        # Find next occurrence of the target day
        days_ahead = day_of_week - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7

        next_date = now.date() + timedelta(days=days_ahead)
        next_run = datetime(
            next_date.year,
            next_date.month,
            next_date.day,
            hour_utc,
            0,
            0,
            tzinfo=timezone.utc,
        )

        # If calculated time is in the past, add a week
        if next_run <= now:
            next_run += timedelta(days=7)

        schedule.next_scheduled_at = next_run

    await db.commit()
    await db.refresh(schedule)

    return ReviewScheduleResponse(
        id=schedule.id,
        service_id=schedule.service_id,
        enabled=schedule.enabled,
        frequency=schedule.frequency,
        generation_day_of_week=schedule.generation_day_of_week,
        generation_hour_utc=schedule.generation_hour_utc,
        timezone=schedule.timezone,
        next_scheduled_at=schedule.next_scheduled_at,
        last_review_generated_at=schedule.last_review_generated_at,
        last_review_status=schedule.last_review_status,
        consecutive_failures=schedule.consecutive_failures,
    )


# ========== Scheduler Endpoint (Called by External Cron) ==========


@router.post("/scheduler/run")
async def run_health_review_scheduler(
    _: bool = Depends(verify_scheduler_token),
):
    """
    Trigger the health review scheduler to check for and process due reviews.

    This endpoint is called by an external scheduler (GitHub Actions cron).
    It checks all ReviewSchedule records where next_scheduled_at <= now()
    and triggers health reviews for those services.

    Authentication: Requires X-Scheduler-Token header.

    Returns:
        Dict with counts: triggered, skipped, failed
    """
    logger.info("Health review scheduler triggered via API")

    try:
        results = await health_review_scheduler.check_and_trigger_reviews()

        logger.info(
            f"Health review scheduler completed: "
            f"{results['triggered']} triggered, "
            f"{results['skipped']} skipped, "
            f"{results['failed']} failed"
        )

        return {
            "success": True,
            "triggered": results["triggered"],
            "skipped": results["skipped"],
            "failed": results["failed"],
            "message": f"Processed {results['triggered']} reviews",
        }

    except Exception as e:
        logger.exception(f"Health review scheduler failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scheduler failed: {str(e)}",
        )
