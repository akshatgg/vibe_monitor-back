"""Schemas for Health Review API endpoints."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CreateReviewRequest(BaseModel):
    """Request to create a health review."""

    week_start: Optional[datetime] = Field(
        None, description="Start of the review period. Defaults to last week."
    )
    week_end: Optional[datetime] = Field(
        None, description="End of the review period. Defaults to now."
    )


class ReviewSummary(BaseModel):
    """Summary of a health review."""

    id: UUID
    service_id: UUID
    service_name: str
    status: str
    overall_health_score: Optional[int] = None
    review_week_start: datetime
    review_week_end: datetime
    generated_at: Optional[datetime] = None
    error_count_analyzed: Optional[int] = None
    logging_gaps_count: Optional[int] = None
    metrics_gaps_count: Optional[int] = None


class ReviewDetail(BaseModel):
    """Detailed health review response."""

    id: UUID
    service_id: UUID
    service_name: str
    status: str
    overall_health_score: Optional[int] = None
    summary: Optional[str] = None
    recommendations: Optional[str] = None
    review_week_start: datetime
    review_week_end: datetime
    generated_at: Optional[datetime] = None
    generation_duration_seconds: Optional[int] = None
    analyzed_commit_sha: Optional[str] = None
    codebase_changed: Optional[bool] = None
    error_count_analyzed: Optional[int] = None
    log_volume_analyzed: Optional[int] = None
    metric_count_analyzed: Optional[int] = None

    # Related data counts
    errors_count: int = 0
    logging_gaps_count: int = 0
    metrics_gaps_count: int = 0
    slis_count: int = 0

    # Inline child records (populated when include=all)
    errors: Optional[List["ReviewErrorResponse"]] = None
    logging_gaps: Optional[List["LoggingGapResponse"]] = None
    metrics_gaps: Optional[List["MetricsGapResponse"]] = None
    slis: Optional[List["SLIResponse"]] = None


class LoggingGapResponse(BaseModel):
    """Logging gap response."""

    id: UUID
    gap_description: str
    gap_category: Optional[str] = None
    priority: str
    affected_files: Optional[List[str]] = None
    affected_functions: Optional[List[str]] = None
    suggested_log_statement: Optional[str] = None
    rationale: Optional[str] = None
    pr_status: str
    acknowledged: bool
    acknowledged_at: Optional[datetime] = None
    acknowledged_by_user_id: Optional[UUID] = None


class MetricsGapResponse(BaseModel):
    """Metrics gap response."""

    id: UUID
    gap_description: str
    gap_category: Optional[str] = None
    metric_type: Optional[str] = None
    priority: str
    affected_components: Optional[List[str]] = None
    suggested_metric_names: Optional[List[str]] = None
    implementation_guide: Optional[str] = None
    example_code: Optional[str] = None
    pr_status: str
    acknowledged: bool
    acknowledged_at: Optional[datetime] = None
    acknowledged_by_user_id: Optional[UUID] = None


class SLIResponse(BaseModel):
    """SLI response."""

    id: UUID
    sli_name: str
    sli_category: Optional[str] = None
    score: int
    previous_week_score: Optional[int] = None
    score_trend: Optional[str] = None
    target_value: Optional[str] = None
    actual_value: Optional[str] = None
    measurement_unit: Optional[str] = None
    analysis: Optional[str] = None


class ReviewErrorResponse(BaseModel):
    """Error response."""

    id: UUID
    error_type: str
    error_fingerprint: Optional[str] = None
    occurrence_count: int
    error_message_sample: Optional[str] = None
    stack_trace_sample: Optional[str] = None


class ReviewListResponse(BaseModel):
    """List of reviews response."""

    reviews: List[ReviewSummary]
    total: int


class CreateReviewResponse(BaseModel):
    """Response after creating a review."""

    review_id: UUID
    status: str
    message: str


# ========== Bulk Review Schemas ==========


class BulkCreateReviewRequest(BaseModel):
    """Optional request body for bulk review."""

    week_start: Optional[datetime] = Field(
        None, description="Start of the review period. Defaults to last week."
    )
    week_end: Optional[datetime] = Field(
        None, description="End of the review period. Defaults to now."
    )


class BulkReviewItem(BaseModel):
    """Single service result in bulk response."""

    service_id: UUID
    service_name: str
    review_id: Optional[UUID] = None
    skipped: bool = False
    reason: Optional[str] = None


class BulkCreateReviewResponse(BaseModel):
    """Response after queueing bulk reviews."""

    queued_count: int
    skipped_count: int
    reviews: List[BulkReviewItem]
    message: str


# ========== Workspace Reviews Schemas (for Frontend) ==========


class ServiceReviewSummary(BaseModel):
    """Review summary for a single service in workspace view."""

    id: UUID
    service_id: UUID
    service_name: str
    status: str
    overall_health_score: Optional[int] = None
    summary: Optional[str] = None
    review_week_start: datetime
    review_week_end: datetime
    generated_at: Optional[datetime] = None
    triggered_by: Optional[str] = None
    error_count_analyzed: Optional[int] = None
    logging_gaps_count: int = 0
    metrics_gaps_count: int = 0
    slis_count: int = 0


class WorkspaceReviewsResponse(BaseModel):
    """Response containing all service reviews for a workspace."""

    workspace_id: UUID
    total_services: int
    services_with_reviews: int
    reviews: List[ServiceReviewSummary]


# ========== Review Schedule Schemas ==========


class ReviewScheduleResponse(BaseModel):
    """Response for review schedule settings."""

    id: UUID
    service_id: UUID
    enabled: bool
    frequency: str
    generation_day_of_week: int  # 0=Monday, 6=Sunday
    generation_hour_utc: int  # 0-23
    timezone: str
    next_scheduled_at: Optional[datetime] = None
    last_review_generated_at: Optional[datetime] = None
    last_review_status: Optional[str] = None
    consecutive_failures: int = 0


class UpdateReviewScheduleRequest(BaseModel):
    """Request to update review schedule settings."""

    enabled: Optional[bool] = Field(None, description="Enable/disable automated reviews")
    generation_day_of_week: Optional[int] = Field(
        None, ge=0, le=6, description="Day of week (0=Monday, 6=Sunday)"
    )
    generation_hour_utc: Optional[int] = Field(
        None, ge=0, le=23, description="Hour in UTC (0-23)"
    )
