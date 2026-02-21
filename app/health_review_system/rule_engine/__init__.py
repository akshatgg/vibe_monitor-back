"""
Rule engine for deterministic gap detection.

Evaluates extracted code facts against a set of rules to detect
logging gaps, metrics gaps, and RED method gaps without LLM involvement.
"""

from .schemas import DetectedProblem, REDDashboardReadiness, REDMetricStatus, RuleEngineResult
from .service import RuleEngineService

__all__ = [
    "RuleEngineService",
    "DetectedProblem",
    "RuleEngineResult",
    "REDDashboardReadiness",
    "REDMetricStatus",
]
