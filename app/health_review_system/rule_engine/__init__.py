"""
Rule engine for deterministic gap detection.

Evaluates extracted code facts against a set of rules to detect
logging gaps and metrics gaps without LLM involvement.
"""

from .schemas import DetectedProblem, RuleEngineResult
from .service import RuleEngineService

__all__ = ["RuleEngineService", "DetectedProblem", "RuleEngineResult"]
