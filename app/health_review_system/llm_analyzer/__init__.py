"""
LLM Analyzer Service - Detects logging/metrics gaps using AI.

Supports both mock and real LLM implementations:
- Mock: Returns hardcoded results for testing
- Real: Uses LangGraph with Groq/Gemini for actual analysis

Configuration:
- USE_MOCK_LLM_ANALYZER=true: Use mock (default)
- USE_MOCK_LLM_ANALYZER=false: Use real LLM
"""

from app.health_review_system.llm_analyzer.service import (
    BaseLLMAnalyzer,
    LLMAnalyzerService,
    MockLLMAnalyzer,
)

__all__ = [
    "LLMAnalyzerService",
    "BaseLLMAnalyzer",
    "MockLLMAnalyzer",
]
