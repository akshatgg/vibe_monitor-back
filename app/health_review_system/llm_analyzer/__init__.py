"""
LLM Analyzer Service.

Two modes controlled by USE_MOCK_LLM_ANALYZER in config:
- True:  MockLLMAnalyzer returns hardcoded demo data
- False: LLMEnrichmentService enriches rule engine results via single LLM call
"""

from app.health_review_system.llm_analyzer.schemas import (
    AnalysisResult,
    EnrichmentResult,
    GapEnrichment,
)
from app.health_review_system.llm_analyzer.service import (
    LLMEnrichmentService,
    MockLLMAnalyzer,
)

__all__ = [
    "MockLLMAnalyzer",
    "LLMEnrichmentService",
    "AnalysisResult",
    "EnrichmentResult",
    "GapEnrichment",
]
