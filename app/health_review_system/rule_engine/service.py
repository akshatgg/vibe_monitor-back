"""
Rule engine service — runs all rules against extracted facts.
"""

import logging
from collections import defaultdict
from typing import List

from app.code_parser.schemas import CodeFact, ExtractedFacts

from .rules import (
    rule_error_no_counter,
    rule_error_path_no_error_log,
    rule_external_io_no_latency,
    rule_external_io_no_logging,
    rule_http_handler_no_logging,
    rule_http_handler_no_metrics,
    rule_large_function_no_logging,
    rule_no_business_metrics,
    rule_silent_exception,
)
from .schemas import DetectedProblem, RuleEngineResult

logger = logging.getLogger(__name__)


class RuleEngineService:
    """Deterministic gap detection via structural rules over code facts."""

    def evaluate(self, all_facts: List[ExtractedFacts]) -> RuleEngineResult:
        """Run all rules against extracted facts from all files."""
        # Flatten all facts across files
        flat_facts: List[CodeFact] = []
        for ef in all_facts:
            flat_facts.extend(ef.facts)

        # Build lookup indexes
        facts_by_file: dict[str, List[CodeFact]] = defaultdict(list)
        facts_by_type: dict[str, List[CodeFact]] = defaultdict(list)
        for fact in flat_facts:
            facts_by_file[fact.file_path].append(fact)
            facts_by_type[fact.fact_type].append(fact)

        # Run logging gap rules
        logging_gaps: List[DetectedProblem] = []
        logging_gaps.extend(rule_silent_exception(facts_by_file, facts_by_type))
        logging_gaps.extend(rule_http_handler_no_logging(facts_by_file, facts_by_type))
        logging_gaps.extend(rule_external_io_no_logging(facts_by_file, facts_by_type))
        logging_gaps.extend(rule_error_path_no_error_log(facts_by_file, facts_by_type))
        logging_gaps.extend(rule_large_function_no_logging(facts_by_file, facts_by_type))

        # Run metrics gap rules
        metrics_gaps: List[DetectedProblem] = []
        metrics_gaps.extend(rule_http_handler_no_metrics(facts_by_file, facts_by_type))
        metrics_gaps.extend(rule_external_io_no_latency(facts_by_file, facts_by_type))
        metrics_gaps.extend(rule_no_business_metrics(facts_by_file, facts_by_type))
        metrics_gaps.extend(rule_error_no_counter(facts_by_file, facts_by_type))

        # Deduplicate
        logging_gaps = self._deduplicate(logging_gaps)
        metrics_gaps = self._deduplicate(metrics_gaps)

        facts_summary = {
            "total_functions": len(facts_by_type.get("function", [])),
            "total_classes": len(facts_by_type.get("class", [])),
            "total_try_blocks": len(facts_by_type.get("try_except", [])),
            "total_logging_calls": len(facts_by_type.get("logging_call", [])),
            "total_metrics_calls": len(facts_by_type.get("metrics_call", [])),
            "total_http_handlers": len(facts_by_type.get("http_handler", [])),
            "total_external_io": len(facts_by_type.get("external_io", [])),
            "total_imports": len(facts_by_type.get("import", [])),
            "total_files": len(facts_by_file),
        }

        logger.info(
            "Rule engine evaluated %d facts across %d files: %d logging gaps, %d metrics gaps",
            len(flat_facts),
            len(facts_by_file),
            len(logging_gaps),
            len(metrics_gaps),
        )

        return RuleEngineResult(
            logging_gaps=logging_gaps,
            metrics_gaps=metrics_gaps,
            facts_summary=facts_summary,
        )

    def _deduplicate(
        self, problems: List[DetectedProblem]
    ) -> List[DetectedProblem]:
        """Remove duplicate problems based on rule_id + affected scope."""
        seen = set()
        unique = []
        for p in problems:
            key = (
                p.rule_id,
                tuple(sorted(p.affected_files)),
                tuple(sorted(p.affected_functions)),
            )
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique
