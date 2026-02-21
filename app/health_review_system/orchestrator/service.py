"""
ReviewOrchestrator - Coordinates the review generation pipeline.

Two modes controlled by USE_MOCK_LLM_ANALYZER:
- True (demo):  Data Gathering → MockLLMAnalyzer → Scoring → Save
- False (real):  Data Gathering → Fact Extraction → Rule Engine → LLM Enrichment + Scoring → Save
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.code_parser.parsers import get_parser_registry
from app.code_parser.repository import ParsedFileRepository, ParsedRepositoryRepository
from app.code_parser.schemas import ExtractedFacts
from app.core.config import settings
from app.health_review_system.codebase_sync import CodebaseSyncService
from app.health_review_system.llm_budget import LLMBudgetCallback
from app.health_review_system.data_collector import DataCollectorService
from app.health_review_system.health_scorer import HealthScorerService
from app.health_review_system.llm_analyzer.service import (
    LLMEnrichmentService,
    MockLLMAnalyzer,
)
from app.health_review_system.orchestrator.schemas import (
    ReviewGenerationRequest,
    ReviewGenerationResult,
)
from app.health_review_system.rule_engine import RuleEngineService
from app.health_review_system.rule_engine.schemas import RuleEngineResult
from app.health_review_system.sli_indicator import SLIIndicatorService
from app.health_review_system.verification import (
    GapVerdict,
    VerificationService,
)
from app.health_review_system.verification.schemas import CodebaseContext as CodebaseContextSchema
from app.health_review_system.verification.service import compute_gap_fingerprint
from app.models import (
    CodebaseContext as CodebaseContextModel,
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
    VerificationVerdict,
)

logger = logging.getLogger(__name__)


class ReviewOrchestrator:
    """
    Orchestrates the review generation pipeline.

    When USE_MOCK_LLM_ANALYZER=True (demo mode):
        Phase 1 → MockLLMAnalyzer → Scoring → Save

    When USE_MOCK_LLM_ANALYZER=False (real mode):
        Phase 1 → Fact Extraction → Rule Engine → LLM Enrichment + Scoring → Save
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.codebase_sync = CodebaseSyncService(db)
        self.data_collector = DataCollectorService(db)
        self.health_scorer = HealthScorerService()
        self.sli_indicator = SLIIndicatorService()

        # Real pipeline components
        self.llm_enrichment = LLMEnrichmentService()
        self.rule_engine = RuleEngineService()
        self.parser_registry = get_parser_registry()

        # Mock component
        self.mock_analyzer = MockLLMAnalyzer()

    async def generate(
        self, request: ReviewGenerationRequest
    ) -> ReviewGenerationResult:
        """Generate a health review."""
        start_time = datetime.now(timezone.utc)

        review = await self.db.get(ServiceReview, request.review_id)
        if not review:
            raise ValueError(f"Review {request.review_id} not found")

        service = await self.db.get(Service, request.service_id)
        if not service:
            raise ValueError(f"Service {request.service_id} not found")

        previous_review = await self._get_previous_review(
            request.service_id, request.review_id
        )

        try:
            review.status = ReviewStatus.GENERATING
            await self.db.commit()

            # ================================================================
            # PHASE 1: Data Gathering (always runs)
            # ================================================================
            logger.info(f"Phase 1: Data gathering for review {review.id}")

            codebase_result = await self.codebase_sync.sync(
                workspace_id=request.workspace_id,
                service=service,
                previous_review=previous_review,
            )

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

            if settings.USE_MOCK_LLM_ANALYZER:
                await self._run_mock_pipeline(
                    review=review,
                    service=service,
                    codebase_result=codebase_result,
                    collected_data=collected_data,
                    previous_review=previous_review,
                    start_time=start_time,
                )
            else:
                await self._run_real_pipeline(
                    review=review,
                    service=service,
                    codebase_result=codebase_result,
                    collected_data=collected_data,
                    previous_review=previous_review,
                    start_time=start_time,
                    request=request,
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

            review.status = ReviewStatus.FAILED
            review.error_message = str(e)
            review.generated_at = datetime.now(timezone.utc)
            await self.db.commit()

            return ReviewGenerationResult(
                success=False,
                review_id=review.id,
                error_message=str(e),
            )

    # ------------------------------------------------------------------
    # Mock pipeline (USE_MOCK_LLM_ANALYZER=True)
    # ------------------------------------------------------------------

    async def _run_mock_pipeline(
        self, review, service, codebase_result, collected_data, previous_review, start_time
    ):
        """Demo mode: MockLLMAnalyzer → Scoring → Save."""
        logger.info(f"Running MOCK pipeline for review {review.id}")

        analysis_result = await self.mock_analyzer.analyze(
            codebase=codebase_result.parsed_codebase,
            collected_data=collected_data,
            service=service,
        )

        gaps_count = len(analysis_result.logging_gaps) + len(analysis_result.metrics_gaps)

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

        health_scores, sli_result = await asyncio.gather(
            run_health_scorer(),
            run_sli_indicator(),
        )

        await self._save_mock_results(
            review=review,
            codebase_result=codebase_result,
            collected_data=collected_data,
            analysis_result=analysis_result,
            health_scores=health_scores,
            sli_result=sli_result,
            start_time=start_time,
        )

    # ------------------------------------------------------------------
    # Real pipeline (USE_MOCK_LLM_ANALYZER=False)
    # ------------------------------------------------------------------

    async def _run_real_pipeline(
        self, review, service, codebase_result, collected_data, previous_review,
        start_time, request,
    ):
        """Real mode: Fact Extraction → Rule Engine → Verification → LLM Enrichment + Scoring → Save."""
        if settings.HEALTH_REVIEW_USE_LANGGRAPH:
            return await self._run_langgraph_pipeline(
                review=review,
                service=service,
                codebase_result=codebase_result,
                collected_data=collected_data,
                previous_review=previous_review,
                start_time=start_time,
                request=request,
            )

        logger.info(f"Running REAL pipeline for review {review.id}")

        # Create global LLM budget tracker
        llm_budget = LLMBudgetCallback(
            max_iterations=settings.HEALTH_REVIEW_LLM_MAX_ITERATIONS,
            max_tokens=settings.HEALTH_REVIEW_LLM_MAX_TOKEN_BUDGET,
        )
        budget_callbacks = [llm_budget]

        # Phase 2: Fact Extraction (Tree-sitter)
        logger.info(f"Phase 2: Fact extraction for review {review.id}")

        all_facts, repository_id, file_contents = await self._extract_facts(
            workspace_id=request.workspace_id,
            repo_full_name=service.repository_name,
        )

        logger.info(f"Phase 2 complete: extracted facts from {len(all_facts)} files")

        # Phase 3: Rule Engine (deterministic gap detection)
        logger.info(f"Phase 3: Rule engine for review {review.id}")

        rule_result = self.rule_engine.evaluate(all_facts, file_contents=file_contents)

        logger.info(
            f"Phase 3 complete: {len(rule_result.logging_gaps)} logging gaps, "
            f"{len(rule_result.metrics_gaps)} metrics gaps, "
            f"{len(rule_result.red_gaps)} RED gaps"
        )

        # Phase 3.5: Verification (LLM agent checks for global instrumentation)
        logger.info(f"Phase 3.5: Verification for review {review.id}")

        verification_results = {}
        codebase_context = None
        verified_rule_result = rule_result

        if repository_id:
            # Check if we can skip verification using previous context
            previous_context = await self._load_codebase_context(
                workspace_id=request.workspace_id,
                repo_full_name=service.repository_name,
            )

            skip_verification = False
            if previous_context and codebase_result.changed_files:
                infra_files = previous_context.infrastructure_files or []
                infra_changed = any(
                    f in codebase_result.changed_files for f in infra_files
                )
                if not infra_changed and infra_files:
                    logger.info(
                        f"Infrastructure files unchanged, reusing previous context "
                        f"({len(infra_files)} infra files, "
                        f"{len(codebase_result.changed_files)} files changed)"
                    )
                    skip_verification = True
                    # Use previous context to filter gaps
                    verified_rule_result = self._filter_gaps_with_context(
                        rule_result, previous_context.context_json
                    )

            if not skip_verification:
                verified_rule_result, verification_results, codebase_context = (
                    await self._run_verification(
                        rule_result=rule_result,
                        all_facts=all_facts,
                        repository_id=repository_id,
                        workspace_id=request.workspace_id,
                        repo_full_name=service.repository_name,
                        commit_sha=codebase_result.commit_sha,
                        callbacks=budget_callbacks,
                    )
                )

        # Phase 4: Parallel - LLM Enrichment + HealthScorer + SLIIndicator
        logger.info(f"Phase 4: Enrichment + scoring for review {review.id}")

        gaps_count = len(verified_rule_result.logging_gaps) + len(verified_rule_result.metrics_gaps)

        async def run_enrichment():
            return await self.llm_enrichment.enrich(
                rule_result=verified_rule_result,
                collected_data=collected_data,
                service=service,
                callbacks=budget_callbacks,
            )

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

        enrichment_result, health_scores, sli_result = await asyncio.gather(
            run_enrichment(),
            run_health_scorer(),
            run_sli_indicator(),
        )

        logger.info(
            f"Phase 4 complete: overall_score={health_scores.overall}, "
            f"slis={len(sli_result.slis)}"
        )

        # Phase 5: Save results
        logger.info(f"Phase 5: Saving results for review {review.id}")

        await self._save_real_results(
            review=review,
            codebase_result=codebase_result,
            collected_data=collected_data,
            rule_result=verified_rule_result,
            enrichment_result=enrichment_result,
            health_scores=health_scores,
            sli_result=sli_result,
            start_time=start_time,
            service=service,
            verification_results=verification_results,
        )

    # ------------------------------------------------------------------
    # LangGraph pipeline
    # ------------------------------------------------------------------

    async def _run_langgraph_pipeline(
        self, review, service, codebase_result, collected_data, previous_review,
        start_time, request,
    ):
        """Run the LangGraph-based health review pipeline."""
        from app.health_review_system.graph import create_health_review_graph
        from app.services.rca.langfuse_handler import get_langfuse_callback

        logger.info(f"Running LangGraph pipeline for review {review.id}")

        graph = create_health_review_graph()

        # Create global LLM budget tracker
        llm_budget = LLMBudgetCallback(
            max_iterations=settings.HEALTH_REVIEW_LLM_MAX_ITERATIONS,
            max_tokens=settings.HEALTH_REVIEW_LLM_MAX_TOKEN_BUDGET,
        )

        initial_state = {
            "workspace_id": request.workspace_id,
            "repo_full_name": service.repository_name,
            "repository_id": "",
            "commit_sha": codebase_result.commit_sha,
            "codebase_changed": codebase_result.changed,
            "changed_files": codebase_result.changed_files,
            "service": service,
            "collected_data": collected_data,
            "previous_review": previous_review,
            "db": self.db,
            "llm_budget": llm_budget,
        }

        # Create Langfuse callback for full pipeline tracing
        langfuse_cb = get_langfuse_callback(
            session_id=str(service.id),
            metadata={
                "review_id": str(review.id),
                "service_name": service.name,
                "repository_name": service.repository_name,
                "commit_sha": codebase_result.commit_sha,
                "agent_version": "health-review-langgraph",
            },
            tags=["health-review", "langgraph"],
        )
        config = {
            "recursion_limit": settings.HEALTH_REVIEW_LANGGRAPH_RECURSION_LIMIT,
        }
        if langfuse_cb:
            config["callbacks"] = [langfuse_cb]

        result = await graph.ainvoke(initial_state, config=config)

        # Extract results from graph state
        verified_rule_result = result.get("verified_rule_result") or result.get("rule_result")
        enrichment_result = result["enrichment_result"]
        health_scores = result["health_scores"]
        sli_result = result["sli_result"]
        verification_results = result.get("verification_results", {})

        logger.info(
            f"LangGraph pipeline complete: score={health_scores.overall}, "
            f"slis={len(sli_result.slis)}"
        )

        # Save results using existing save method
        await self._save_real_results(
            review=review,
            codebase_result=codebase_result,
            collected_data=collected_data,
            rule_result=verified_rule_result,
            enrichment_result=enrichment_result,
            health_scores=health_scores,
            sli_result=sli_result,
            start_time=start_time,
            service=service,
            verification_results=verification_results,
        )

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    async def _run_verification(
        self,
        rule_result: RuleEngineResult,
        all_facts: List[ExtractedFacts],
        repository_id: str,
        workspace_id: str,
        repo_full_name: str,
        commit_sha: str,
        callbacks: list = None,
    ) -> tuple:
        """Run 2-phase LLM verification: discover infrastructure, then verify gaps.

        Returns:
            Tuple of (filtered_rule_result, verification_results, codebase_context).
        """
        from app.health_review_system.llm_analyzer.providers import get_default_provider

        all_gaps = rule_result.logging_gaps + rule_result.metrics_gaps
        if not all_gaps:
            logger.info("No gaps to verify, skipping verification phase")
            return rule_result, {}, None

        provider = get_default_provider()
        llm = provider.get_llm()
        verification_service = VerificationService(
            llm=llm, db=self.db, repository_id=repository_id
        )

        # Phase A: Fetch repo tree
        from app.code_parser.repository import ParsedFileRepository
        file_crud = ParsedFileRepository(self.db)
        repo_tree = await file_crud.get_file_tree(repository_id)

        # Phase B: Discover infrastructure
        gap_rule_ids = list({g.rule_id for g in all_gaps})
        codebase_context = await verification_service.discover_infrastructure(
            repo_tree=repo_tree,
            gap_rule_ids=gap_rule_ids,
            callbacks=callbacks,
        )

        # Save codebase context to DB
        await self._save_codebase_context(
            workspace_id=workspace_id,
            repo_full_name=repo_full_name,
            commit_sha=commit_sha,
            context=codebase_context,
        )

        # Phase C: Verify gaps against discovered infrastructure
        verification_results = await verification_service.verify_gaps(
            raw_gaps=all_gaps,
            codebase_context=codebase_context,
            callbacks=callbacks,
        )

        # Filter out false alarm gaps
        false_alarm_titles = set()
        for result in verification_results.values():
            for v in result.verdicts:
                if v.verdict == GapVerdict.FALSE_ALARM:
                    false_alarm_titles.add(v.gap_title)

        filtered_logging = [
            g for g in rule_result.logging_gaps
            if g.title not in false_alarm_titles
        ]
        filtered_metrics = [
            g for g in rule_result.metrics_gaps
            if g.title not in false_alarm_titles
        ]

        logger.info(
            f"Verification complete: {len(false_alarm_titles)} false alarms removed, "
            f"{len(filtered_logging)} logging + {len(filtered_metrics)} metrics gaps remain"
        )

        filtered_result = RuleEngineResult(
            logging_gaps=filtered_logging,
            metrics_gaps=filtered_metrics,
            facts_summary=rule_result.facts_summary,
        )

        return filtered_result, verification_results, codebase_context

    def _filter_gaps_with_context(
        self,
        rule_result: RuleEngineResult,
        context_json: dict,
    ) -> RuleEngineResult:
        """Filter gaps using a previously saved codebase context (no LLM call).

        Uses the context's global coverage info to suppress false alarms:
        - If global HTTP metrics cover all routes → suppress MET_001
        - If global DB instrumentation exists → suppress MET_002 for DB I/O
        - If global error handling exists → suppress MET_004
        """
        try:
            context = CodebaseContextSchema(**context_json)
        except Exception:
            logger.warning("Failed to parse previous codebase context, skipping filter")
            return rule_result

        suppressed_rules = set()
        if context.has_global_http_coverage():
            suppressed_rules.add("MET_001")
        if context.has_global_db_coverage():
            suppressed_rules.add("MET_002")
        if context.has_global_error_coverage():
            suppressed_rules.add("MET_004")

        if not suppressed_rules:
            return rule_result

        filtered_logging = [
            g for g in rule_result.logging_gaps
            if g.rule_id not in suppressed_rules
        ]
        filtered_metrics = [
            g for g in rule_result.metrics_gaps
            if g.rule_id not in suppressed_rules
        ]

        suppressed_count = (
            len(rule_result.logging_gaps) - len(filtered_logging)
            + len(rule_result.metrics_gaps) - len(filtered_metrics)
        )
        logger.info(
            f"Context-based filtering suppressed {suppressed_count} gaps "
            f"(rules: {suppressed_rules})"
        )

        return RuleEngineResult(
            logging_gaps=filtered_logging,
            metrics_gaps=filtered_metrics,
            facts_summary=rule_result.facts_summary,
        )

    async def _save_codebase_context(
        self,
        workspace_id: str,
        repo_full_name: str,
        commit_sha: str,
        context: CodebaseContextSchema,
    ) -> None:
        """Persist codebase context to the database."""
        db_context = CodebaseContextModel(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            repo_full_name=repo_full_name,
            commit_sha=commit_sha,
            context_json=context.model_dump(),
            infrastructure_files=context.infrastructure_files,
            summary_text=context.summary,
        )
        self.db.add(db_context)
        await self.db.flush()
        logger.info(
            f"Saved codebase context for {repo_full_name}@{commit_sha[:8]}: "
            f"{len(context.infrastructure_files)} infrastructure files"
        )

    async def _load_codebase_context(
        self, workspace_id: str, repo_full_name: str
    ) -> Optional[CodebaseContextModel]:
        """Load the most recent codebase context for a repository."""
        stmt = (
            select(CodebaseContextModel)
            .where(CodebaseContextModel.workspace_id == workspace_id)
            .where(CodebaseContextModel.repo_full_name == repo_full_name)
            .order_by(CodebaseContextModel.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Save: Mock path
    # ------------------------------------------------------------------

    async def _save_mock_results(
        self, review, codebase_result, collected_data, analysis_result,
        health_scores, sli_result, start_time,
    ) -> None:
        """Save mock AnalysisResult to DB (original mapping)."""
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

        # Errors from mock AnalysisResult
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

        # Logging gaps from mock AnalysisResult
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

        # Metrics gaps from mock AnalysisResult
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

        # SLIs
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

    # ------------------------------------------------------------------
    # Save: Real path
    # ------------------------------------------------------------------

    async def _save_real_results(
        self, review, codebase_result, collected_data, rule_result,
        enrichment_result, health_scores, sli_result, start_time, service,
        verification_results=None,
    ) -> None:
        """Save real pipeline results (rule engine + enrichment) to DB."""
        review.status = ReviewStatus.COMPLETED
        review.overall_health_score = health_scores.overall
        review.summary = enrichment_result.summary
        review.recommendations = enrichment_result.recommendations
        review.analyzed_commit_sha = codebase_result.commit_sha
        review.codebase_changed = codebase_result.changed
        review.generated_at = datetime.now(timezone.utc)
        review.generation_duration_seconds = int(
            (datetime.now(timezone.utc) - start_time).total_seconds()
        )
        review.error_count_analyzed = len(collected_data.errors)
        review.log_volume_analyzed = collected_data.log_count
        review.metric_count_analyzed = collected_data.metric_count

        # Errors from collected data
        for error in collected_data.errors:
            self.db.add(
                ReviewError(
                    id=str(uuid.uuid4()),
                    review_id=review.id,
                    error_type=error.error_type,
                    error_message_sample=error.message_sample,
                    error_fingerprint=error.fingerprint,
                    occurrence_count=error.count,
                    stack_trace_sample=error.stack_trace,
                )
            )

        # Build verdict lookup from verification results
        verdict_lookup: dict[str, dict] = {}
        if verification_results:
            for result in verification_results.values():
                for v in result.verdicts:
                    verdict_lookup[v.gap_title] = {
                        "verdict": v.verdict.value,
                        "reason": v.reason,
                        "evidence_file": v.evidence_file,
                    }

        # Logging gaps from rule engine + enrichment
        for gap in rule_result.logging_gaps:
            enrichment = enrichment_result.get_enrichment(gap.rule_id)
            fingerprint = compute_gap_fingerprint(gap)
            verdict_info = verdict_lookup.get(gap.title)
            verdict_enum = None
            if verdict_info:
                verdict_str = verdict_info["verdict"].upper()
                verdict_enum = VerificationVerdict[verdict_str] if verdict_str in VerificationVerdict.__members__ else None

            self.db.add(
                ReviewLoggingGap(
                    id=str(uuid.uuid4()),
                    review_id=review.id,
                    gap_description=gap.title,
                    gap_category=gap.category,
                    priority=GapPriority[gap.severity],
                    affected_files=gap.affected_files,
                    affected_functions=gap.affected_functions,
                    suggested_log_statement=(
                        enrichment.suggested_log_statement if enrichment else None
                    ),
                    rationale=(
                        enrichment.rationale if enrichment else None
                    ),
                    pr_status=PRStatus.NOT_CREATED,
                    acknowledged=False,
                    gap_fingerprint=fingerprint,
                    verification_verdict=verdict_enum,
                    verification_evidence=verdict_info if verdict_info else None,
                )
            )

        # Metrics gaps from rule engine + enrichment
        for gap in rule_result.metrics_gaps:
            enrichment = enrichment_result.get_enrichment(gap.rule_id)
            fingerprint = compute_gap_fingerprint(gap)
            verdict_info = verdict_lookup.get(gap.title)
            verdict_enum = None
            if verdict_info:
                verdict_str = verdict_info["verdict"].upper()
                verdict_enum = VerificationVerdict[verdict_str] if verdict_str in VerificationVerdict.__members__ else None

            self.db.add(
                ReviewMetricsGap(
                    id=str(uuid.uuid4()),
                    review_id=review.id,
                    gap_description=gap.title,
                    gap_category=gap.category,
                    metric_type=gap.metric_type,
                    priority=GapPriority[gap.severity],
                    affected_components=gap.affected_files,
                    suggested_metric_names=gap.suggested_metric_names,
                    implementation_guide=(
                        enrichment.implementation_guide if enrichment else None
                    ),
                    example_code=(
                        enrichment.example_code if enrichment else None
                    ),
                    integration_provider=getattr(service, "metrics_provider", None),
                    pr_status=PRStatus.NOT_CREATED,
                    acknowledged=False,
                    gap_fingerprint=fingerprint,
                    verification_verdict=verdict_enum,
                    verification_evidence=verdict_info if verdict_info else None,
                )
            )

        # SLIs
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _extract_facts(
        self, workspace_id: str, repo_full_name: str
    ) -> tuple[List[ExtractedFacts], str, dict[str, str]]:
        """Extract code facts from all stored parsed files using Tree-sitter.

        Returns:
            Tuple of (all_facts, repository_id, file_contents).
            file_contents maps file paths to their content (used by RED rules).
        """
        repo_crud = ParsedRepositoryRepository(self.db)
        file_crud = ParsedFileRepository(self.db)

        parsed_repo = await repo_crud.get_latest(workspace_id, repo_full_name)
        if not parsed_repo:
            logger.warning(f"No parsed repository found for {repo_full_name}")
            return [], "", {}

        db_files = await file_crud.get_by_repository(parsed_repo.id, limit=5000)

        all_facts: List[ExtractedFacts] = []
        file_contents: dict[str, str] = {}
        for db_file in db_files:
            if not db_file.content or not db_file.language:
                continue

            # Store file contents for RED rules (content-based analysis)
            file_contents[db_file.file_path] = db_file.content

            parser = self.parser_registry.get_parser(db_file.language)
            if not parser:
                continue

            facts = parser.extract_facts(db_file.content, db_file.file_path)
            all_facts.append(facts)

        return all_facts, parsed_repo.id, file_contents

    async def _get_previous_review(
        self, service_id: str, current_review_id: str
    ) -> Optional[ServiceReview]:
        """Get the most recent completed review before current."""
        stmt = (
            select(ServiceReview)
            .where(ServiceReview.service_id == service_id)
            .where(ServiceReview.id != current_review_id)
            .where(ServiceReview.status == ReviewStatus.COMPLETED)
            .options(selectinload(ServiceReview.slis))
            .order_by(ServiceReview.review_week_start.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

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
