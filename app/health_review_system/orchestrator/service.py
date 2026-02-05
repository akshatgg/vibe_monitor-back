"""
ReviewOrchestrator - Coordinates the review generation pipeline.

Pipeline with parallel execution:
1. PARALLEL: CodebaseSync + DataCollector
2. SEQUENTIAL: LLMAnalyzer (needs both results)
3. PARALLEL: HealthScorer + SLIIndicator
4. Save all results atomically
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


from app.health_review_system.codebase_sync import CodebaseSyncService
from app.health_review_system.data_collector import DataCollectorService
from app.health_review_system.health_scorer import HealthScorerService
from app.health_review_system.llm_analyzer import LLMAnalyzerService
from app.health_review_system.orchestrator.schemas import (
    ReviewGenerationRequest,
    ReviewGenerationResult,
)
from app.health_review_system.sli_indicator import SLIIndicatorService
from app.models import (
    GapPriority,
    PRStatus,
    ReviewError,
    ReviewLoggingGap,
    ReviewMetricsGap,
    ReviewSchedule,
    ReviewSLI,
    ReviewStatus,
    ScoreTrend,
    Service,
    ServiceReview,
)

logger = logging.getLogger(__name__)


class ReviewOrchestrator:
    """
    Orchestrates the review generation pipeline with parallel execution.

    Pipeline flow:
    1. Update review status → GENERATING
    2. PARALLEL: CodebaseSyncService.sync() + DataCollectorService.collect()
    3. SEQUENTIAL: LLMAnalyzerService.analyze() (needs both results)
    4. PARALLEL: HealthScorerService.calculate() + SLIIndicatorService.calculate()
    5. Save all results in single DB transaction
    6. Update status → COMPLETED or FAILED
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.codebase_sync = CodebaseSyncService(db)
        self.data_collector = DataCollectorService(db)
        self.llm_analyzer = LLMAnalyzerService()
        self.health_scorer = HealthScorerService()
        self.sli_indicator = SLIIndicatorService()

    async def generate(
        self, request: ReviewGenerationRequest
    ) -> ReviewGenerationResult:
        """
        Generate a health review with parallel execution.

        Execution strategy:
        - Phase 1 (parallel): CodebaseSync + DataCollector
        - Phase 2 (sequential): LLMAnalyzer (depends on Phase 1)
        - Phase 3 (parallel): HealthScorer + SLIIndicator

        Args:
            request: Review generation request with IDs and time range

        Returns:
            ReviewGenerationResult with success status
        """
        start_time = datetime.now(timezone.utc)

        # Fetch review and service
        review = await self.db.get(ServiceReview, request.review_id)
        if not review:
            raise ValueError(f"Review {request.review_id} not found")

        service = await self.db.get(Service, request.service_id)
        if not service:
            raise ValueError(f"Service {request.service_id} not found")

        # Get previous review for comparison
        previous_review = await self._get_previous_review(
            request.service_id, request.review_id
        )

        try:
            # Update status to GENERATING
            review.status = ReviewStatus.GENERATING
            await self.db.commit()

            # ================================================================
            # PHASE 1: Sequential - CodebaseSync + DataCollector
            # (Running sequentially to avoid SQLAlchemy session concurrency issues)
            # ================================================================
            logger.info(f"Phase 1/3: Data gathering for review {review.id}")

            # Run CodebaseSync first
            codebase_result = await self.codebase_sync.sync(
                workspace_id=request.workspace_id,
                service=service,
                previous_review=previous_review,
            )

            # Then run DataCollector
            collected_data = await self.data_collector.collect(
                workspace_id=request.workspace_id,
                service=service,
                week_start=request.week_start,
                week_end=request.week_end,
            )

            logger.info(
                f"Phase 1 complete: codebase_changed={codebase_result.changed}, "
                f"logs={collected_data.log_count}, errors={len(collected_data.errors)}"
            )

            # ================================================================
            # PHASE 2: Sequential - LLMAnalyzer (needs both Phase 1 results)
            # ================================================================
            logger.info(f"Phase 2/3: LLM analysis for review {review.id}")

            analysis_result = await self.llm_analyzer.analyze(
                codebase=codebase_result.parsed_codebase,
                collected_data=collected_data,
                service=service,
            )

            logger.info(
                f"Phase 2 complete: logging_gaps={len(analysis_result.logging_gaps)}, "
                f"metrics_gaps={len(analysis_result.metrics_gaps)}"
            )

            # ================================================================
            # PHASE 3: Parallel - HealthScorer + SLIIndicator
            # ================================================================
            logger.info(f"Phase 3/3: Parallel scoring for review {review.id}")

            gaps_count = len(analysis_result.logging_gaps) + len(
                analysis_result.metrics_gaps
            )

            # Run scoring in parallel using asyncio.to_thread for sync functions
            async def run_health_scorer():
                return self.health_scorer.calculate(
                    metrics=collected_data.metrics,
                    gaps_count=gaps_count,
                )

            async def run_sli_indicator():
                return self.sli_indicator.calculate(
                    metrics=collected_data.metrics,
                    service=service,
                    previous_review=previous_review,
                )

            health_task = asyncio.create_task(
                run_health_scorer(),
                name="health_scorer",
            )

            sli_task = asyncio.create_task(
                run_sli_indicator(),
                name="sli_indicator",
            )

            health_scores, sli_result = await asyncio.gather(health_task, sli_task)

            logger.info(
                f"Phase 3 complete: overall_score={health_scores.overall}, "
                f"slis={len(sli_result.slis)}"
            )

            # ================================================================
            # SAVE: Atomic database transaction
            # ================================================================
            await self._save_results(
                review=review,
                codebase_result=codebase_result,
                collected_data=collected_data,
                analysis_result=analysis_result,
                health_scores=health_scores,
                sli_result=sli_result,
                start_time=start_time,
            )

            # Update schedule
            await self._update_schedule(request.service_id, review)

            duration = int((datetime.now(timezone.utc) - start_time).total_seconds())
            logger.info(f"Review {review.id} completed in {duration}s")

            return ReviewGenerationResult(
                success=True,
                review_id=review.id,
                generation_duration_seconds=duration,
            )

        except Exception as e:
            logger.exception(f"Review generation failed: {e}")

            # Update review to FAILED
            review.status = ReviewStatus.FAILED
            review.error_message = str(e)
            review.generated_at = datetime.now(timezone.utc)
            await self.db.commit()

            return ReviewGenerationResult(
                success=False,
                review_id=review.id,
                error_message=str(e),
            )

    async def _get_previous_review(
        self, service_id: str, current_review_id: str
    ) -> Optional[ServiceReview]:
        """Get the most recent completed review before current."""
        stmt = (
            select(ServiceReview)
            .where(ServiceReview.service_id == service_id)
            .where(ServiceReview.id != current_review_id)
            .where(ServiceReview.status == ReviewStatus.COMPLETED)
            .options(selectinload(ServiceReview.slis))  # Eager load slis for SLIIndicator
            .order_by(ServiceReview.review_week_start.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _save_results(
        self,
        review: ServiceReview,
        codebase_result,
        collected_data,
        analysis_result,
        health_scores,
        sli_result,
        start_time: datetime,
    ) -> None:
        """Save all results in a single transaction."""

        # Update review
        review.status = ReviewStatus.COMPLETED
        review.overall_health_score = health_scores.overall
        review.summary = analysis_result.summary
        review.recommendations = analysis_result.recommendations
        review.analyzed_commit_sha = codebase_result.commit_sha
        review.codebase_changed = codebase_result.changed
        review.generated_at = datetime.now(timezone.utc)
        review.generation_duration_seconds = int(
            (datetime.now(timezone.utc) - start_time).total_seconds()
        )
        review.error_count_analyzed = len(collected_data.errors)
        review.log_volume_analyzed = collected_data.log_count
        review.metric_count_analyzed = collected_data.metric_count

        # Save errors
        for error in analysis_result.analyzed_errors:
            self.db.add(
                ReviewError(
                    id=str(uuid.uuid4()),
                    review_id=review.id,
                    error_type=error.error_type,
                    error_message_sample=error.likely_cause,
                    error_fingerprint=error.fingerprint,
                    occurrence_count=error.count,
                    stack_trace_sample=error.code_location,
                )
            )

        # Save logging gaps
        for gap in analysis_result.logging_gaps:
            self.db.add(
                ReviewLoggingGap(
                    id=str(uuid.uuid4()),
                    review_id=review.id,
                    gap_description=gap.description,
                    gap_category=gap.category,
                    priority=GapPriority[gap.priority],
                    affected_files=gap.affected_files,
                    affected_functions=gap.affected_functions,
                    suggested_log_locations=gap.suggested_locations,
                    suggested_log_statement=gap.suggested_log_statement,
                    rationale=gap.rationale,
                    pr_status=PRStatus.NOT_CREATED,
                    acknowledged=False,
                )
            )

        # Save metrics gaps
        for gap in analysis_result.metrics_gaps:
            self.db.add(
                ReviewMetricsGap(
                    id=str(uuid.uuid4()),
                    review_id=review.id,
                    gap_description=gap.description,
                    gap_category=gap.category,
                    metric_type=gap.metric_type,
                    priority=GapPriority[gap.priority],
                    affected_components=gap.affected_components,
                    suggested_metric_names=gap.suggested_metric_names,
                    implementation_guide=gap.implementation_guide,
                    example_code=gap.example_code,
                    integration_provider=gap.integration_provider,
                    pr_status=PRStatus.NOT_CREATED,
                    acknowledged=False,
                )
            )

        # Save SLIs
        for sli in sli_result.slis:
            self.db.add(
                ReviewSLI(
                    id=str(uuid.uuid4()),
                    review_id=review.id,
                    sli_name=sli.name,
                    sli_category=sli.category,
                    score=sli.score,
                    previous_week_score=sli.previous_score,
                    score_trend=ScoreTrend[sli.trend] if sli.trend else None,
                    target_value=sli.target,
                    actual_value=sli.actual,
                    measurement_unit=sli.unit,
                    data_source=sli.data_source,
                    query_used=sli.query_used,
                    analysis=sli.analysis,
                )
            )

        await self.db.commit()

    async def _update_schedule(
        self, service_id: str, review: ServiceReview
    ) -> None:
        """Update review schedule with last review info."""
        stmt = select(ReviewSchedule).where(
            ReviewSchedule.service_id == service_id
        )
        result = await self.db.execute(stmt)
        schedule = result.scalar_one_or_none()

        if schedule:
            schedule.last_review_id = review.id
            schedule.last_review_generated_at = review.generated_at
            schedule.last_review_status = review.status.value
            schedule.consecutive_failures = 0
            schedule.last_error = None
            await self.db.commit()
