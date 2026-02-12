import logging
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_groq import ChatGroq

from .graph import create_rca_graph
from .state import RCAState
from app.core.config import settings

logger = logging.getLogger(__name__)


class RCAAgentService:
    def __init__(self):
        self._groq_llm = None

    @property
    def provider_name(self) -> str:
        """
        Name of the LLM provider used by the RCA agent.

        This is used for metrics and observability. If the underlying
        provider implementation changes (e.g., to OpenAI or Gemini),
        this should be updated in one place.
        """
        return "groq"

    @property
    def groq_llm(self):
        if self._groq_llm is None:
            if not settings.GROQ_API_KEY:
                raise ValueError("GROQ_API_KEY not configured")
            self._groq_llm = ChatGroq(
                model=settings.GROQ_LLM_MODEL or "llama-3.3-70b-versatile",
                temperature=settings.RCA_AGENT_TEMPERATURE,
                max_tokens=settings.RCA_AGENT_MAX_TOKENS,
            )
        return self._groq_llm

    async def analyze(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
        callbacks: Optional[list] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        try:
            workspace_id = context.get("workspace_id") if context else None
            if not workspace_id:
                raise ValueError("workspace_id is required in context")

            graph = create_rca_graph(self.groq_llm, db, workspace_id, callbacks=callbacks)
            initial_state: RCAState = {
                "task": user_query,
                "workspace_id": workspace_id,
                "context": context or {},
                "failing_service": (context or {}).get("failing_service"),
                "timeframe": (context or {}).get("timeframe"),
                "severity": (context or {}).get("severity"),
                "environment_name": None,
                "hypotheses": [],
                "root_cause": None,
                "report": None,
                "trace": [],
                "history": [],
                "error": None,
                "iteration": 0,
                "max_loops": (context or {}).get("max_loops") or 2,
            }
            final_state = await graph.ainvoke(initial_state, config={"callbacks": callbacks or []})

            return {
                "output": final_state.get("report"),
                "intermediate_steps": final_state.get("trace"),
                "success": final_state.get("error") is None,
                "error": final_state.get("error"),
            }

        except Exception as e:
            return {
                "output": f"Investigation failed: {str(e)}",
                "intermediate_steps": [],
                "success": False,
                "error": str(e),
            }

    async def analyze_with_retry(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
        callbacks: Optional[list] = None,
        db: Optional[AsyncSession] = None,
        max_retries: int = 1,
    ) -> Dict[str, Any]:
        """
        Perform RCA with retry logic.

        Args:
            user_query: User's incident description
            context: Workspace context
            callbacks: Optional callbacks
            db: Database session
            max_retries: Max retry attempts

        Returns:
            Dict with investigation results
        """
        attempt = 0
        last_error = None

        while attempt <= max_retries:
            try:
                result = await self.analyze(
                    user_query=user_query,
                    context=context,
                    callbacks=callbacks,
                    db=db,
                )

                if result["success"]:
                    return result

                last_error = result.get("error")
                logger.warning(f"Attempt {attempt + 1} failed: {last_error}")

            except Exception as e:
                last_error = str(e)
                logger.error(f"Attempt {attempt + 1} error: {e}")

            attempt += 1

        logger.error(f"All {max_retries + 1} attempts failed. Last error: {last_error}")

        return {
            "output": f"❌ Investigation failed after {max_retries + 1} attempts\n\nLast error: {last_error}",
            "intermediate_steps": [],
            "success": False,
            "error": last_error,
        }


rca_agent_service = RCAAgentService()
