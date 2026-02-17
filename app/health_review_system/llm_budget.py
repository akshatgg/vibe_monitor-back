"""
Global LLM budget tracking for the health review pipeline.

Provides a LangChain callback handler that tracks both iteration count
and total token usage across all LLM calls in a single pipeline run.
If either limit is exceeded, raises LLMBudgetExceeded.
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)


class LLMBudgetExceeded(Exception):
    """Raised when either the token or iteration budget is exhausted."""

    pass


class LLMBudgetCallback(BaseCallbackHandler):
    """LangChain callback that enforces global iteration + token limits.

    One instance is created per pipeline run and injected into every LLM call.
    On each LLM completion it increments counters. Before each LLM start it
    checks whether the budget is already exhausted.
    """

    def __init__(self, max_iterations: int, max_tokens: int):
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.iteration_count = 0
        self.total_tokens_used = 0

    @property
    def is_exhausted(self) -> bool:
        return (
            self.iteration_count >= self.max_iterations
            or self.total_tokens_used >= self.max_tokens
        )

    @property
    def remaining_iterations(self) -> int:
        return max(0, self.max_iterations - self.iteration_count)

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.total_tokens_used)

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        if self.is_exhausted:
            reason = []
            if self.iteration_count >= self.max_iterations:
                reason.append(
                    f"iterations {self.iteration_count}/{self.max_iterations}"
                )
            if self.total_tokens_used >= self.max_tokens:
                reason.append(
                    f"tokens {self.total_tokens_used}/{self.max_tokens}"
                )
            raise LLMBudgetExceeded(
                f"LLM budget exhausted: {', '.join(reason)}"
            )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self.iteration_count += 1

        # Extract token usage from LLMResult
        token_usage = (response.llm_output or {}).get("token_usage", {})
        total = token_usage.get("total_tokens", 0)

        # Fallback: check generation_info on first generation
        if not total and response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    info = getattr(gen, "generation_info", {}) or {}
                    usage = info.get("usage_metadata", {})
                    total += (
                        usage.get("input_tokens", 0)
                        + usage.get("output_tokens", 0)
                    )

        self.total_tokens_used += total

        logger.info(
            f"[LLM Budget] {self.iteration_count}/{self.max_iterations} iterations, "
            f"{self.total_tokens_used}/{self.max_tokens} tokens"
        )
