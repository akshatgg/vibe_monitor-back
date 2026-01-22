"""
RCA Agent Service using LangGraph.
Production-ready agent with comprehensive multi-repo investigation.
"""

import logging
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI

from .graph import create_rca_graph
from .state import RCAStateV2
from .builder import ToolRegistry
from .capabilities import IntegrationCapabilityResolver
from .langfuse_handler import get_langfuse_callback
from app.core.config import settings

logger = logging.getLogger(__name__)


class RCAAgentService:
    """
    LangGraph-based RCA Agent.

    Improvements over previous LangChain agent:
    - Plan-Execute-Analyze pattern (vs pure ReAct)
    - Checks ALL repos in workspace for comprehensive investigation
    - No hardcoded service names - fully dynamic
    - Progressive summarization (70% token reduction)
    - Structured investigation flow
    - Better dependency discovery from code
    - Detects performance issues (delays, loops, etc.)
    """

    def __init__(self):
        """Initialize the agent service."""
        logger.info("Initializing LangGraph RCA Agent")

        # Initialize LLMs lazily (only when needed)
        self._groq_llm = None
        self._gemini_llm = None

        # Initialize tool registry and capability resolver
        self.tool_registry = ToolRegistry()
        self.capability_resolver = IntegrationCapabilityResolver(only_healthy=True)

        logger.info("LangGraph RCA Agent initialized (lazy LLM loading)")

    @property
    def groq_llm(self):
        """Lazy initialization of Groq LLM."""
        if self._groq_llm is None:
            if not settings.GROQ_API_KEY:
                raise ValueError(
                    "GROQ_API_KEY not configured. Please set it in environment variables."
                )
            self._groq_llm = ChatGroq(
                model=settings.GROQ_LLM_MODEL or "llama-3.3-70b-versatile",
                temperature=settings.RCA_AGENT_TEMPERATURE,
                max_tokens=settings.RCA_AGENT_MAX_TOKENS,
            )
            logger.info(f"Groq LLM initialized: {settings.GROQ_LLM_MODEL}")
        return self._groq_llm

    @property
    def gemini_llm(self):
        """Lazy initialization of Gemini LLM."""
        if self._gemini_llm is None and settings.GEMINI_API_KEY:
            self._gemini_llm = ChatGoogleGenerativeAI(
                model=settings.GEMINI_LLM_MODEL,
                google_api_key=settings.GEMINI_API_KEY,
                temperature=settings.RCA_AGENT_TEMPERATURE,
                max_output_tokens=settings.RCA_AGENT_MAX_TOKENS,
            )
            logger.info(
                f"Gemini LLM initialized for multimodal support: {settings.GEMINI_LLM_MODEL}"
            )
        return self._gemini_llm

    async def analyze(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
        callbacks: Optional[list] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Perform RCA using LangGraph.

        Args:
            user_query: User's incident description
            context: Workspace context (workspace_id, service_repo_mapping, etc)
            callbacks: Optional callbacks for monitoring
            db: Database session

        Returns:
            Dict with:
                - output: Final report (str)
                - intermediate_steps: List of investigation steps
                - success: Boolean
                - error: Optional error message
        """
        logger.info(f"Starting RCA investigation: {user_query[:100]}...")

        try:
            # Extract workspace context
            workspace_id = context.get("workspace_id") if context else None
            if not workspace_id:
                raise ValueError("workspace_id is required in context")

            # ================================================================
            # Resolve capabilities and tools
            # ================================================================

            logger.info(f"Resolving capabilities for workspace: {workspace_id}")

            execution_context = await self.capability_resolver.resolve(
                workspace_id=workspace_id,
                db=db,
                service_mapping=context.get("service_repo_mapping", {})
                if context
                else {},
                thread_history=context.get("thread_history") if context else None,
            )

            capabilities = execution_context.capabilities

            logger.info(
                f"Available capabilities for workspace {workspace_id}: "
                f"{[c.value for c in capabilities]}"
            )

            # Get tools for capabilities
            tools = self.tool_registry.get_tools_for_capabilities(capabilities)
            tools_dict = {tool.name: tool for tool in tools}

            logger.info(f"Loaded {len(tools_dict)} tools: {list(tools_dict.keys())}")

            # ================================================================
            # Choose LLM based on multimodal inputs
            # ================================================================

            files = context.get("files", []) if context else []
            has_multimodal = bool(files)

            if has_multimodal and self.gemini_llm:
                logger.info(
                    f"Using Gemini LLM for multimodal analysis ({len(files)} files)"
                )
                selected_llm = self.gemini_llm
            else:
                if has_multimodal and not self.gemini_llm:
                    logger.warning(
                        "Multimodal input detected but Gemini LLM not available - using Groq"
                    )
                selected_llm = self.groq_llm

            # ================================================================
            # Create graph
            # ================================================================

            graph = create_rca_graph(selected_llm, tools_dict)

            # ================================================================
            # Initialize state
            # ================================================================

            initial_state: RCAStateV2 = {
                "user_query": user_query,
                "workspace_id": workspace_id,
                "context": context or {},
                "files": files,
                "query_type": None,
                "primary_service": None,
                "symptoms": [],
                "incident_type": None,
                "services_to_check": [],
                "tools_to_use": [],
                "logs_summary": {},
                "metrics_summary": {},
                "code_findings": {},
                "commit_findings": {},
                # NEW: Iterative investigation fields
                "investigation_chain": None,
                "final_decision": None,
                # Root cause analysis
                "root_cause": None,
                "root_service": None,
                "root_commit": None,
                "confidence": None,
                # NEW: Multi-level RCA fields
                "victim_service": None,
                "intermediate_services": None,
                # Output
                "final_report": None,
                "iteration": 0,
                "max_iterations": 3,
                "error": None,
                "intermediate_steps": [],
            }

            logger.info("Initial state prepared, running graph...")

            # ================================================================
            # Run graph
            # ================================================================

            # Build callbacks list with Langfuse handler for observability
            all_callbacks = list(callbacks) if callbacks else []

            # Add Langfuse callback for agent tracing
            langfuse_callback = get_langfuse_callback(
                session_id=(context or {}).get("thread_ts"),  # Group by Slack thread
                user_id=(context or {}).get("user_id"),
                metadata={
                    "workspace_id": workspace_id,
                    "channel_id": (context or {}).get("channel_id"),
                    "source": (context or {}).get("source", "unknown"),
                    "model": settings.GROQ_LLM_MODEL
                    if selected_llm == self.groq_llm
                    else settings.GEMINI_LLM_MODEL,
                    "agent_version": "langgraph",
                },
                tags=["rca", "langgraph"],
            )
            if langfuse_callback:
                all_callbacks.append(langfuse_callback)
                logger.info("Langfuse callback added for tracing")

            # Prepare config with callbacks
            config = {}
            if all_callbacks:
                config["callbacks"] = all_callbacks

            final_state = await graph.ainvoke(
                initial_state, config=config if config else None
            )

            logger.info("Graph execution completed")

            # ================================================================
            # Format response
            # ================================================================

            output = final_state.get("final_report", "Investigation completed")
            intermediate_steps = final_state.get("intermediate_steps", [])
            error = final_state.get("error")

            result = {
                "output": output,
                "intermediate_steps": intermediate_steps,
                "success": error is None,
                "error": error,
            }

            if error:
                logger.error(f"Investigation completed with error: {error}")
            else:
                logger.info("Investigation completed successfully")
                logger.info(f"Report length: {len(output)} chars")
                logger.info(f"Steps taken: {len(intermediate_steps)}")

            return result

        except Exception as e:
            logger.error(f"Error in LangGraph RCA: {e}", exc_info=True)

            return {
                "output": f"❌ Investigation failed\n\nError: {str(e)}\n\nPlease try again or contact support.",
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

        # All retries failed
        logger.error(f"All {max_retries + 1} attempts failed. Last error: {last_error}")

        return {
            "output": f"❌ Investigation failed after {max_retries + 1} attempts\n\nLast error: {last_error}",
            "intermediate_steps": [],
            "success": False,
            "error": last_error,
        }


# Singleton instance
rca_agent_service = RCAAgentService()
