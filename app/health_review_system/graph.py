"""
LangGraph-based health review pipeline.

Progressive verification with per-file extraction loop:
- Full review: extract → rules → identify_config_files → [extract_single_file loop] → build_context → sample_verify → filter → enrich → score
- Incremental (infra unchanged): extract → rules → context_filter → enrich → score
- No gaps: extract → rules → enrich → score
"""

import logging
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.code_parser.parsers import get_parser_registry
from app.code_parser.repository import ParsedFileRepository, ParsedRepositoryRepository
from app.code_parser.schemas import CodeFact, ExtractedFacts
from app.core.config import settings
from app.health_review_system.llm_analyzer.service import LLMEnrichmentService
from app.health_review_system.rule_engine import RuleEngineService
from app.health_review_system.rule_engine.schemas import RuleEngineResult
from app.health_review_system.verification import (
    GapVerdict,
    VerificationService,
)
from app.health_review_system.llm_budget import LLMBudgetCallback, LLMBudgetExceeded
from app.health_review_system.verification.schemas import (
    CodebaseContext as CodebaseContextSchema,
    VerificationResult,
)
from app.models import CodebaseContext as CodebaseContextModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _budget_callbacks(budget: Optional[LLMBudgetCallback]) -> list:
    """Return a callbacks list containing the budget tracker (if present).

    LangGraph automatically propagates config-level callbacks (e.g. Langfuse)
    to every LLM call, so we only need to explicitly pass our budget callback.
    """
    return [budget] if budget else []


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class HealthReviewState(TypedDict, total=False):
    """State flowing through the health review graph."""

    # Inputs (set before graph invocation)
    workspace_id: str
    repo_full_name: str
    repository_id: str
    commit_sha: str
    codebase_changed: bool
    changed_files: List[str]
    service: Any  # Service model
    collected_data: Any  # CollectedData
    previous_review: Any  # Optional[ServiceReview]
    db: Any  # AsyncSession

    # Phase 2: Fact Extraction
    all_facts: List[ExtractedFacts]
    facts_by_type: Dict[str, List[CodeFact]]

    # Phase 3: Rule Engine
    rule_result: RuleEngineResult

    # Node 1: Repo Tree + Config File Identification
    repo_tree: List[dict]  # [{"file_path", "language", "line_count"}]
    candidate_config_files: List[str]  # File paths identified by LLM

    # Node 2: Per-file extraction loop
    current_file_index: int  # Tracks which file we're processing
    file_extractions: List[dict]  # Accumulated extractions from all processed files

    # Node 3: Verification
    codebase_context: Optional[CodebaseContextSchema]
    verification_results: Dict[str, VerificationResult]
    previous_context_json: Optional[dict]

    # Phase 4: Filtered gaps
    verified_rule_result: RuleEngineResult
    verification_verdicts: Dict[str, dict]

    # Phase 5: Enrichment + Scoring
    enrichment_result: Any
    health_scores: Any
    sli_result: Any

    # LLM budget tracking
    llm_budget: Optional[LLMBudgetCallback]

    # Error tracking
    error: Optional[str]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def extract_facts_node(state: HealthReviewState) -> dict:
    """Phase 2: Extract code facts from parsed files using Tree-sitter."""
    db: AsyncSession = state["db"]
    workspace_id = state["workspace_id"]
    repo_full_name = state["repo_full_name"]

    repo_crud = ParsedRepositoryRepository(db)
    file_crud = ParsedFileRepository(db)
    parser_registry = get_parser_registry()

    parsed_repo = await repo_crud.get_latest(workspace_id, repo_full_name)
    if not parsed_repo:
        logger.warning(f"No parsed repository found for {repo_full_name}")
        return {"all_facts": [], "facts_by_type": {}, "repository_id": ""}

    db_files = await file_crud.get_by_repository(
        parsed_repo.id, limit=settings.HEALTH_REVIEW_MAX_FACTS_PER_FILE
    )

    all_facts: List[ExtractedFacts] = []
    facts_by_type: dict[str, list] = defaultdict(list)

    for db_file in db_files:
        if not db_file.content or not db_file.language:
            continue
        parser = parser_registry.get_parser(db_file.language)
        if not parser:
            continue
        facts = parser.extract_facts(db_file.content, db_file.file_path)
        all_facts.append(facts)
        for fact in facts.facts:
            facts_by_type[fact.fact_type].append(fact)

    logger.info(f"Extracted facts from {len(all_facts)} files")
    return {
        "all_facts": all_facts,
        "facts_by_type": dict(facts_by_type),
        "repository_id": parsed_repo.id,
    }


async def run_rules_node(state: HealthReviewState) -> dict:
    """Phase 3: Run deterministic rule engine over extracted facts."""
    all_facts = state.get("all_facts", [])
    rule_engine = RuleEngineService()
    rule_result = rule_engine.evaluate(all_facts)

    logger.info(
        f"Rule engine: {len(rule_result.logging_gaps)} logging gaps, "
        f"{len(rule_result.metrics_gaps)} metrics gaps"
    )
    return {"rule_result": rule_result}


async def load_previous_context_node(state: HealthReviewState) -> dict:
    """Load previous codebase context from DB (if exists)."""
    db: AsyncSession = state["db"]
    workspace_id = state["workspace_id"]
    repo_full_name = state["repo_full_name"]

    stmt = (
        select(CodebaseContextModel)
        .where(CodebaseContextModel.workspace_id == workspace_id)
        .where(CodebaseContextModel.repo_full_name == repo_full_name)
        .order_by(CodebaseContextModel.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    prev = result.scalar_one_or_none()

    if prev:
        logger.info(f"Loaded previous context from {prev.commit_sha[:8]}")
        return {"previous_context_json": prev.context_json}
    return {"previous_context_json": None}


# ---------------------------------------------------------------------------
# Node 1: Identify Config/Middleware Files (fetch tree + LLM identifies files)
# ---------------------------------------------------------------------------


async def identify_config_files_node(state: HealthReviewState, config: RunnableConfig = None) -> dict:
    """Node 1: Fetch repo tree and use LLM to identify config/middleware files.

    Combines the old fetch_repo_tree + a focused LLM call that sees only
    file names (no content) and returns candidate config/middleware paths.
    """
    from app.health_review_system.llm_analyzer.providers import get_default_provider

    db: AsyncSession = state["db"]
    repository_id = state.get("repository_id", "")
    rule_result: RuleEngineResult = state["rule_result"]

    if not repository_id:
        logger.warning("No repository_id, cannot identify config files")
        return {"repo_tree": [], "candidate_config_files": []}

    # Fetch repo tree (file names only)
    file_crud = ParsedFileRepository(db)
    tree = await file_crud.get_file_tree(repository_id)
    logger.info(f"Fetched repo tree: {len(tree)} files")

    gap_rule_ids = list({
        g.rule_id
        for g in rule_result.logging_gaps + rule_result.metrics_gaps
    })

    budget = state.get("llm_budget")
    callbacks = _budget_callbacks(budget)

    provider = get_default_provider()
    llm = provider.get_llm()
    service = VerificationService(llm=llm, db=db, repository_id=repository_id)

    candidate_files = await service.identify_config_files(
        repo_tree=tree,
        gap_rule_ids=gap_rule_ids,
        callbacks=callbacks,
    )

    logger.info(f"Identified {len(candidate_files)} candidate config files")
    return {
        "repo_tree": tree,
        "candidate_config_files": candidate_files,
        "current_file_index": 0,
        "file_extractions": [],
    }


# ---------------------------------------------------------------------------
# Node 2a: Extract From Single File (processes one file per invocation)
# ---------------------------------------------------------------------------


async def extract_single_file_node(state: HealthReviewState, config: RunnableConfig = None) -> dict:
    """Node 2a: Read and extract instrumentation from ONE file.

    Called in a loop by the graph. Reads the file at current_file_index,
    extracts instrumentation patterns via LLM, appends results to
    file_extractions, and increments the index.
    """
    from app.health_review_system.llm_analyzer.providers import get_default_provider

    db: AsyncSession = state["db"]
    repository_id = state["repository_id"]
    rule_result: RuleEngineResult = state["rule_result"]
    candidate_files = state.get("candidate_config_files", [])
    current_index = state.get("current_file_index", 0)
    existing_extractions = state.get("file_extractions", [])

    if current_index >= len(candidate_files):
        logger.warning("[extract_single_file] Index out of bounds, skipping")
        return {"current_file_index": current_index}

    file_path = candidate_files[current_index]

    gap_rule_ids = list({
        g.rule_id
        for g in rule_result.logging_gaps + rule_result.metrics_gaps
    })

    budget = state.get("llm_budget")
    callbacks = _budget_callbacks(budget)

    provider = get_default_provider()
    llm = provider.get_llm()
    service = VerificationService(llm=llm, db=db, repository_id=repository_id)

    logger.info(
        f"[extract_single_file] Processing file {current_index + 1}/{len(candidate_files)}: {file_path}"
    )

    extractions = await service.extract_from_single_file(
        file_path=file_path,
        gap_rule_ids=gap_rule_ids,
        callbacks=callbacks,
    )

    # Accumulate and advance index
    updated_extractions = existing_extractions + extractions
    return {
        "current_file_index": current_index + 1,
        "file_extractions": updated_extractions,
    }


def route_after_file_extraction(state: HealthReviewState) -> str:
    """Check if more files remain to process. Raises if LLM budget exhausted."""
    budget = state.get("llm_budget")
    if budget and budget.is_exhausted:
        raise LLMBudgetExceeded(
            f"LLM budget exhausted during file extraction: "
            f"{budget.iteration_count}/{budget.max_iterations} iterations, "
            f"{budget.total_tokens_used}/{budget.max_tokens} tokens"
        )

    candidate_files = state.get("candidate_config_files", [])
    current_index = state.get("current_file_index", 0)

    if current_index < len(candidate_files):
        return "extract_next"
    return "build_context"


# ---------------------------------------------------------------------------
# Node 2b: Build CodebaseContext from accumulated extractions
# ---------------------------------------------------------------------------


async def build_codebase_context_node(state: HealthReviewState) -> dict:
    """Node 2b: Combine all per-file extractions into a CodebaseContext.

    Called once after the file extraction loop completes. Builds the final
    CodebaseContext and saves it to DB for future incremental reviews.
    """
    file_extractions = state.get("file_extractions", [])
    db: AsyncSession = state["db"]

    codebase_context = VerificationService.build_codebase_context(file_extractions)

    # Save context to DB for future incremental reviews
    db.add(CodebaseContextModel(
        id=str(uuid.uuid4()),
        workspace_id=state["workspace_id"],
        repo_full_name=state["repo_full_name"],
        commit_sha=state["commit_sha"],
        context_json=codebase_context.model_dump(),
        infrastructure_files=codebase_context.infrastructure_files,
        summary_text=codebase_context.summary,
    ))
    await db.flush()

    logger.info(
        f"Codebase context built from {len(file_extractions)} extractions: "
        f"{len(codebase_context.global_http_metrics)} HTTP, "
        f"{len(codebase_context.global_db_instrumentation)} DB, "
        f"{len(codebase_context.global_tracing)} tracing, "
        f"{len(codebase_context.global_error_handling)} error handling, "
        f"infra_files={codebase_context.infrastructure_files}"
    )
    return {"codebase_context": codebase_context}


# ---------------------------------------------------------------------------
# Node 3: Sample-Based Gap Verification (agent backtracks per rule group)
# ---------------------------------------------------------------------------


async def sample_verify_gaps_node(state: HealthReviewState, config: RunnableConfig = None) -> dict:
    """Node 3: Verify gaps by sampling 20 per rule group and backtracking.

    For each rule group, samples up to 20 gaps and uses an LLM agent with
    tools to trace each gap back through the codebase. If >=70% of samples
    are covered by middleware, the entire group is marked FALSE_ALARM.
    """
    from app.health_review_system.llm_analyzer.providers import get_default_provider

    rule_result: RuleEngineResult = state["rule_result"]
    codebase_context: CodebaseContextSchema = state["codebase_context"]
    all_gaps = rule_result.logging_gaps + rule_result.metrics_gaps

    if not all_gaps:
        return {"verification_results": {}}

    budget = state.get("llm_budget")
    callbacks = _budget_callbacks(budget)
    db: AsyncSession = state["db"]
    repository_id = state["repository_id"]

    provider = get_default_provider()
    llm = provider.get_llm()
    service = VerificationService(llm=llm, db=db, repository_id=repository_id)

    verification_results = await service.verify_gaps(
        raw_gaps=all_gaps,
        codebase_context=codebase_context,
        callbacks=callbacks,
    )

    logger.info(
        f"Sample verification complete: {len(verification_results)} rule types verified"
    )
    return {"verification_results": verification_results}


# ---------------------------------------------------------------------------
# Filter + Context Filter (unchanged)
# ---------------------------------------------------------------------------


async def filter_gaps_node(state: HealthReviewState) -> dict:
    """Filter false alarm gaps based on verification results."""
    rule_result: RuleEngineResult = state["rule_result"]
    verification_results = state.get("verification_results", {})

    false_alarm_titles = set()
    covered_globally_titles = set()
    genuine_titles = set()
    verdict_lookup: Dict[str, dict] = {}

    for rule_id, result in verification_results.items():
        for v in result.verdicts:
            verdict_lookup[v.gap_title] = {
                "verdict": v.verdict.value,
                "reason": v.reason,
                "evidence_file": v.evidence_file,
            }
            if v.verdict == GapVerdict.FALSE_ALARM:
                false_alarm_titles.add(v.gap_title)
            elif v.verdict == GapVerdict.COVERED_GLOBALLY:
                covered_globally_titles.add(v.gap_title)
            else:
                genuine_titles.add(v.gap_title)

        logger.info(
            f"[filter_gaps] {rule_id}: "
            f"{sum(1 for v in result.verdicts if v.verdict == GapVerdict.GENUINE)} genuine, "
            f"{sum(1 for v in result.verdicts if v.verdict == GapVerdict.FALSE_ALARM)} false_alarm, "
            f"{sum(1 for v in result.verdicts if v.verdict == GapVerdict.COVERED_GLOBALLY)} covered_globally"
        )

    # Filter out false alarms AND covered_globally
    remove_titles = false_alarm_titles | covered_globally_titles

    filtered_logging = [
        g for g in rule_result.logging_gaps if g.title not in remove_titles
    ]
    filtered_metrics = [
        g for g in rule_result.metrics_gaps if g.title not in remove_titles
    ]

    removed_count = len(remove_titles)
    logger.info(
        f"[filter_gaps] Decision summary: "
        f"{len(genuine_titles)} genuine, "
        f"{len(false_alarm_titles)} false_alarm, "
        f"{len(covered_globally_titles)} covered_globally → "
        f"removed {removed_count}, "
        f"remaining {len(filtered_logging)} logging + {len(filtered_metrics)} metrics gaps"
    )

    return {
        "verified_rule_result": RuleEngineResult(
            logging_gaps=filtered_logging,
            metrics_gaps=filtered_metrics,
            facts_summary=rule_result.facts_summary,
        ),
        "verification_verdicts": verdict_lookup,
    }


async def context_filter_gaps_node(state: HealthReviewState) -> dict:
    """Filter gaps using previous context (no LLM call). Used when infra unchanged."""
    rule_result: RuleEngineResult = state["rule_result"]
    previous_context_json = state.get("previous_context_json")

    if not previous_context_json:
        logger.info("[context_filter] No previous context found, passing all gaps through")
        return {
            "verified_rule_result": rule_result,
            "verification_verdicts": {},
        }

    try:
        context = CodebaseContextSchema(**previous_context_json)
    except Exception:
        logger.warning("[context_filter] Failed to parse previous context, passing all gaps through")
        return {
            "verified_rule_result": rule_result,
            "verification_verdicts": {},
        }

    suppressed_rules = set()
    if context.has_global_http_coverage():
        suppressed_rules.add("MET_001")
        logger.info("[context_filter] Suppressing MET_001: global HTTP coverage detected in previous context")
    if context.has_global_db_coverage():
        suppressed_rules.add("MET_002")
        logger.info("[context_filter] Suppressing MET_002: global DB coverage detected in previous context")
    if context.has_global_error_coverage():
        suppressed_rules.add("MET_004")
        logger.info("[context_filter] Suppressing MET_004: global error coverage detected in previous context")

    original_logging = len(rule_result.logging_gaps)
    original_metrics = len(rule_result.metrics_gaps)

    filtered_logging = [
        g for g in rule_result.logging_gaps if g.rule_id not in suppressed_rules
    ]
    filtered_metrics = [
        g for g in rule_result.metrics_gaps if g.rule_id not in suppressed_rules
    ]

    suppressed = (original_logging - len(filtered_logging)) + (original_metrics - len(filtered_metrics))
    logger.info(
        f"[context_filter] Decision: suppressed_rules={suppressed_rules}, "
        f"removed {suppressed} gaps "
        f"(logging: {original_logging}→{len(filtered_logging)}, "
        f"metrics: {original_metrics}→{len(filtered_metrics)})"
    )

    return {
        "verified_rule_result": RuleEngineResult(
            logging_gaps=filtered_logging,
            metrics_gaps=filtered_metrics,
            facts_summary=rule_result.facts_summary,
        ),
        "verification_verdicts": {},
    }


# ---------------------------------------------------------------------------
# Enrich + Score (unchanged)
# ---------------------------------------------------------------------------


async def enrich_node(state: HealthReviewState, config: RunnableConfig = None) -> dict:
    """Phase 4: LLM enrichment of verified gaps."""
    verified = state.get("verified_rule_result", state.get("rule_result"))
    collected_data = state["collected_data"]
    service = state["service"]

    budget = state.get("llm_budget")
    callbacks = _budget_callbacks(budget)

    enrichment_service = LLMEnrichmentService()
    enrichment_result = await enrichment_service.enrich(
        rule_result=verified,
        collected_data=collected_data,
        service=service,
        callbacks=callbacks,
    )

    logger.info("LLM enrichment complete")
    return {"enrichment_result": enrichment_result}


async def score_node(state: HealthReviewState) -> dict:
    """Phase 5: Calculate health scores and SLIs."""
    from app.health_review_system.health_scorer import HealthScorerService
    from app.health_review_system.sli_indicator import SLIIndicatorService

    collected_data = state["collected_data"]
    service = state["service"]
    previous_review = state.get("previous_review")
    verified = state.get("verified_rule_result", state.get("rule_result"))

    gaps_count = len(verified.logging_gaps) + len(verified.metrics_gaps)

    scorer = HealthScorerService()
    sli_service = SLIIndicatorService()

    health_scores = scorer.calculate(
        metrics=collected_data.metrics,
        gaps_count=gaps_count,
    )
    sli_result = sli_service.calculate(
        metrics=collected_data.metrics,
        service=service,
        previous_review=previous_review,
    )

    logger.info(
        f"Scoring complete: overall={health_scores.overall}, slis={len(sli_result.slis)}"
    )
    return {"health_scores": health_scores, "sli_result": sli_result}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_rules(state: HealthReviewState) -> str:
    """Decide verification strategy after rule engine."""
    rule_result = state.get("rule_result")
    if not rule_result:
        return "enrich"

    all_gaps = rule_result.logging_gaps + rule_result.metrics_gaps
    if not all_gaps:
        logger.info("No gaps detected, skipping verification")
        return "enrich"

    repository_id = state.get("repository_id", "")
    if not repository_id:
        logger.info("No repository_id, skipping verification")
        return "enrich"

    # Check if we can use previous context instead of re-verifying
    previous_context_json = state.get("previous_context_json")
    changed_files = state.get("changed_files", [])

    if previous_context_json and changed_files:
        infra_files = previous_context_json.get("infrastructure_files", [])
        infra_changed = any(f in changed_files for f in infra_files)
        if not infra_changed and infra_files:
            logger.info("Infrastructure unchanged, using context-based filtering")
            return "context_filter"

    return "identify_config"


# ---------------------------------------------------------------------------
# Graph Builder
# ---------------------------------------------------------------------------


def create_health_review_graph():
    """Build and compile the health review LangGraph."""
    graph = StateGraph(HealthReviewState)

    # Add nodes
    graph.add_node("extract_facts", extract_facts_node)
    graph.add_node("run_rules", run_rules_node)
    graph.add_node("load_previous_context", load_previous_context_node)
    graph.add_node("identify_config_files", identify_config_files_node)
    graph.add_node("extract_single_file", extract_single_file_node)
    graph.add_node("build_codebase_context", build_codebase_context_node)
    graph.add_node("sample_verify_gaps", sample_verify_gaps_node)
    graph.add_node("filter_gaps", filter_gaps_node)
    graph.add_node("context_filter", context_filter_gaps_node)
    graph.add_node("enrich", enrich_node)
    graph.add_node("score", score_node)

    # Flow: extract → rules → load_context → (route)
    graph.set_entry_point("extract_facts")
    graph.add_edge("extract_facts", "run_rules")
    graph.add_edge("run_rules", "load_previous_context")

    # Route after loading context
    graph.add_conditional_edges(
        "load_previous_context",
        route_after_rules,
        {
            "identify_config": "identify_config_files",
            "context_filter": "context_filter",
            "enrich": "enrich",
        },
    )

    # Full verification path: identify → [loop: extract one file at a time] → build context → verify → filter → enrich
    graph.add_edge("identify_config_files", "extract_single_file")

    # File extraction loop: process one file, check if more remain
    graph.add_conditional_edges(
        "extract_single_file",
        route_after_file_extraction,
        {
            "extract_next": "extract_single_file",   # loop back for next file
            "build_context": "build_codebase_context",  # done, build context
        },
    )

    graph.add_edge("build_codebase_context", "sample_verify_gaps")
    graph.add_edge("sample_verify_gaps", "filter_gaps")
    graph.add_edge("filter_gaps", "enrich")

    # Context filter path (unchanged)
    graph.add_edge("context_filter", "enrich")

    # Enrichment → Score → END
    graph.add_edge("enrich", "score")
    graph.add_edge("score", END)

    return graph.compile()
