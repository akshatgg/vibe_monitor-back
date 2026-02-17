"""
Verification module for health review system.

Provides LLM-based verification of rule engine findings against
actual codebase architecture (middleware, global instrumentation, etc.).
"""

from .schemas import CodebaseContext, VerificationResult, GapVerdict
from .service import VerificationService

__all__ = [
    "CodebaseContext",
    "VerificationResult",
    "GapVerdict",
    "VerificationService",
]
