"""
RCA Agent Service using LangChain with Groq LLM

Updated to use capability-based tool filtering:
- Tools are selected based on workspace integrations
- Only healthy integrations contribute tools
- Uses IntegrationCapabilityResolver and AgentExecutorBuilder
"""

import logging
import re
from typing import Dict, Any, Optional
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from .prompts import RCA_SYSTEM_PROMPT
from .capabilities import IntegrationCapabilityResolver
from .builder import AgentExecutorBuilder

logger = logging.getLogger(__name__)


class NoHealthyIntegrationsError(Exception):
    """Raised when no healthy integrations are available for RCA analysis."""
    pass


class RCAAgentService:
    """
    Service for Root Cause Analysis using AI agent with ReAct pattern.

    Updated to use capability-based tool filtering:
    - Resolves workspace integrations to capabilities
    - Only loads tools for available, healthy integrations
    - Uses AgentExecutorBuilder for clean construction
    """

    def __init__(self):
        """Initialize the RCA agent with Groq LLM (shared across all requests)"""
        self.llm = None
        self.prompt = None
        self.capability_resolver = IntegrationCapabilityResolver(only_healthy=True)
        self._initialize_llm()

    def _initialize_llm(self):
        """Initialize the shared LLM and prompt template"""
        try:
            # Initialize Groq LLM (stateless, can be shared)
            if not settings.GROQ_API_KEY:
                raise ValueError("GROQ_API_KEY not configured in environment")

            self.llm = ChatGroq(
                api_key=settings.GROQ_API_KEY,
                model=settings.GROQ_LLM_MODEL,  # Groq's best model for reasoning
                temperature=settings.RCA_AGENT_TEMPERATURE,
                max_tokens=settings.RCA_AGENT_MAX_TOKENS,
            )

            # Create chat prompt template with system message, service mapping, and thread history
            self.prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        RCA_SYSTEM_PROMPT
                        + "\n\n## 📋 SERVICE→REPOSITORY MAPPING\n\n{service_mapping_text}\n\n{thread_history_text}",
                    ),
                    ("human", "{input}"),
                    ("placeholder", "{agent_scratchpad}"),
                ]
            )

            logger.info(f"RCA Agent for text analysis initialised successfully with Groq model: {settings.GROQ_LLM_MODEL}")

        except Exception as e:
            logger.error(f"Failed to initialize RCA agent LLM: {e}")
            raise

    async def _create_agent_executor_for_workspace(
        self,
        workspace_id: str,
        db: AsyncSession,
        service_mapping: Optional[Dict[str, str]] = None,
        thread_history: Optional[str] = None,
    ):
        """
        Create a workspace-specific agent executor with capability-filtered tools.

        This method:
        1. Resolves workspace integrations to capabilities
        2. Filters tools based on available capabilities
        3. Binds workspace_id to selected tools
        4. Creates the agent executor

        Args:
            workspace_id: The workspace ID
            db: Database session for querying integrations
            service_mapping: Optional service→repo mapping
            thread_history: Optional thread history

        Returns:
            AgentExecutor configured with capability-filtered tools
        """
        # Resolve capabilities from workspace integrations
        execution_context = await self.capability_resolver.resolve(
            workspace_id=workspace_id,
            db=db,
            service_mapping=service_mapping or {},
            thread_history=thread_history,
        )

        logger.info(
            f"Resolved capabilities for workspace {workspace_id}: "
            f"{[c.value for c in execution_context.capabilities]}"
        )
        logger.info(
            f"Active integrations: {list(execution_context.integrations.keys())}"
        )

        # Check if there are any healthy integrations with capabilities
        # Slack is excluded as it doesn't provide RCA tools
        rca_integrations = {
            k: v for k, v in execution_context.integrations.items()
            if k != 'slack'
        }
        if not rca_integrations or not execution_context.capabilities:
            logger.warning(
                f"No healthy integrations with RCA capabilities for workspace {workspace_id}. "
                f"Available integrations: {list(execution_context.integrations.keys())}"
            )
            raise NoHealthyIntegrationsError(
                "No healthy integrations available for RCA analysis"
            )

        # Build agent executor with filtered tools
        builder = AgentExecutorBuilder(self.llm, self.prompt)
        executor = builder.with_context(execution_context).build()

        logger.info(
            f"Created agent executor for workspace {workspace_id} "
            f"with {len(executor.tools)} tools (capability-filtered)"
        )

        return executor

    async def analyze(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
        callbacks: Optional[list] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Perform root cause analysis for the given user query

        Args:
            user_query: User's question or issue description (e.g., "Why is my xyz service slow?")
            context: Optional context from Slack (user_id, channel_id, workspace_id, etc.)
            callbacks: Optional list of callback handlers (e.g., for Slack progress updates)
            db: Database session for querying integrations (required for capability resolution)

        Returns:
            Dictionary containing:
                - output: The RCA analysis text
                - intermediate_steps: List of reasoning steps taken
                - success: Whether analysis completed successfully
                - error: Error message if failed
        """
        try:
            # NOTE: Security validation is now performed at the worker level
            # using LLM-based guard before RCA agent is invoked

            # Extract workspace_id from context (REQUIRED - no default)
            workspace_id = (context or {}).get("workspace_id")

            if not workspace_id:
                error_msg = "workspace_id is required in context for RCA analysis"
                logger.error(error_msg)
                return {
                    "output": None,
                    "intermediate_steps": [],
                    "success": False,
                    "error": error_msg,
                }

            if not db:
                error_msg = "db session is required for capability-based tool resolution"
                logger.error(error_msg)
                return {
                    "output": None,
                    "intermediate_steps": [],
                    "success": False,
                    "error": error_msg,
                }

            logger.info(
                f"Starting RCA analysis for query: '{user_query}' (workspace: {workspace_id})"
            )

            # Extract service→repo mapping from context
            service_repo_mapping = (context or {}).get("service_repo_mapping", {})

            # Format the mapping for the prompt
            if service_repo_mapping:
                mapping_lines = [
                    f"- Service `{service}` → Repository `{repo}`"
                    for service, repo in service_repo_mapping.items()
                ]
                service_mapping_text = "\n".join(mapping_lines)
                logger.info(
                    f"Injecting service→repo mapping with {len(service_repo_mapping)} entries"
                )
            else:
                service_mapping_text = (
                    "(No services discovered - workspace may have no repositories)"
                )
                logger.warning("No service→repo mapping provided in context")

            # Extract and format thread history from context
            thread_history = (context or {}).get("thread_history", [])

            if thread_history:
                logger.info(
                    f"Formatting thread history with {len(thread_history)} messages"
                )

                # Format thread messages as conversation history
                history_lines = ["## 🧵 CONVERSATION HISTORY", ""]
                history_lines.append(
                    "This is a follow-up question in an existing thread. Here's the previous conversation:"
                )
                history_lines.append("")

                for msg in thread_history:
                    user_id = msg.get("user", "unknown")
                    text = msg.get("text", "")
                    bot_id = msg.get("bot_id")

                    # Strip bot mentions from message text (e.g., <@U12345678>)
                    clean_text = re.sub(
                        settings.SLACK_USER_MENTION_PATTERN, "", text
                    ).strip()
                    # Identify if message is from bot or user
                    if bot_id:
                        history_lines.append(f"**Assistant**: {clean_text}")
                    else:
                        history_lines.append(f"**User ({user_id})**: {clean_text}")
                    history_lines.append("")

                thread_history_text = "\n".join(history_lines)
                logger.info("Thread history formatted and ready for injection")
            else:
                thread_history_text = ""
                logger.info("No thread history to format")

            # Create workspace-specific agent executor with capability-filtered tools
            agent_executor = await self._create_agent_executor_for_workspace(
                workspace_id=workspace_id,
                db=db,
                service_mapping=service_repo_mapping,
                thread_history=thread_history_text,
            )

            # Prepare input for the agent
            agent_input = {
                "input": user_query,
                "service_mapping_text": service_mapping_text,
                "thread_history_text": thread_history_text,
            }

            # Execute the agent asynchronously with callbacks
            if callbacks:
                result = await agent_executor.ainvoke(
                    agent_input, config={"callbacks": callbacks}
                )
            else:
                result = await agent_executor.ainvoke(agent_input)

            logger.info(
                f"RCA analysis completed successfully for workspace: {workspace_id}"
            )

            # Handle case where result might be None
            if result is None:
                logger.warning("Agent executor returned None result")
                return {
                    "output": "Analysis completed but no output generated.",
                    "intermediate_steps": [],
                    "success": True,
                    "error": None,
                }

            return {
                "output": result.get("output", "Analysis completed but no output generated."),
                "intermediate_steps": result.get("intermediate_steps", []),
                "success": True,
                "error": None,
            }

        except NoHealthyIntegrationsError as e:
            # No healthy integrations available - return specific error for worker to handle
            logger.warning(f"No healthy integrations for workspace {workspace_id}: {e}")
            return {
                "output": None,
                "intermediate_steps": [],
                "success": False,
                "error": str(e),
                "error_type": "no_healthy_integrations",
            }

        except Exception as e:
            # Enhanced error logging for Groq API errors
            error_details = {"error_type": type(e).__name__, "error_message": str(e)}

            # Extract failed_generation from Groq API errors if available
            if hasattr(e, "body") and isinstance(e.body, dict):
                error_body = e.body
                if "error" in error_body and isinstance(error_body["error"], dict):
                    error_info = error_body["error"]
                    error_details["error_code"] = error_info.get("code")
                    error_details["error_type_api"] = error_info.get("type")

                    # Capture failed_generation for debugging
                    if "failed_generation" in error_info:
                        error_details["failed_generation"] = error_info[
                            "failed_generation"
                        ]
                        logger.error(
                            f"Groq API tool_use_failed - failed_generation: {error_info['failed_generation']}"
                        )

            logger.error(f"Error during RCA analysis: {error_details}", exc_info=True)
            return {
                "output": None,
                "intermediate_steps": [],
                "success": False,
                "error": f"RCA analysis failed: {str(e)}",
            }

    async def analyze_with_retry(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
        max_retries: int = 2,
        callbacks: Optional[list] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Perform RCA analysis with automatic retry on failure

        Args:
            user_query: User's question
            context: Optional context
            max_retries: Maximum number of retry attempts
            callbacks: Optional callback handlers
            db: Database session for querying integrations (required)

        Returns:
            Analysis result dictionary
        """
        for attempt in range(max_retries + 1):
            try:
                result = await self.analyze(
                    user_query, context, callbacks=callbacks, db=db
                )

                if result["success"]:
                    return result

                # Check if this is a non-retryable error (e.g., no healthy integrations)
                error_type = result.get("error_type")
                if error_type == "no_healthy_integrations":
                    logger.info(
                        "No healthy integrations - skipping retries as this won't resolve itself"
                    )
                    return result

                # If analysis didn't succeed but didn't error, retry
                logger.warning(
                    f"Analysis attempt {attempt + 1} did not succeed, retrying..."
                )

            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {e}", exc_info=True)

                if attempt == max_retries:
                    return {
                        "output": None,
                        "intermediate_steps": [],
                        "success": False,
                        "error": f"RCA failed after {max_retries + 1} attempts: {str(e)}",
                    }

        # Should not reach here, but handle edge case
        return {
            "output": None,
            "intermediate_steps": [],
            "success": False,
            "error": "RCA analysis failed for unknown reasons",
        }


# Singleton instance
rca_agent_service = RCAAgentService()
