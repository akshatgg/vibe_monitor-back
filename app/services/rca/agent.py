"""
RCA Agent Service using LangChain with configurable LLM

Updated to use capability-based tool filtering:
- Tools are selected based on workspace integrations
- Only healthy integrations contribute tools
- Uses IntegrationCapabilityResolver and AgentExecutorBuilder

BYOLLM (Bring Your Own LLM) Support:
- Workspace-specific LLM selection based on llm_provider_configs table
- Supports OpenAI, Azure OpenAI, Google Gemini, and default Groq
- Falls back to VibeMonitor default (Groq) if no custom config
"""

import logging
import re
from typing import Any, Dict, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.llm.providers import get_llm_for_workspace

from .builder import AgentExecutorBuilder
from .capabilities import IntegrationCapabilityResolver
from .gemini_agent import gemini_rca_agent_service
from .prompts import RCA_SYSTEM_PROMPT

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

    BYOLLM Support:
    - Uses workspace-specific LLM based on llm_provider_configs table
    - Falls back to VibeMonitor default (Groq) if no custom config
    - Supports OpenAI, Azure OpenAI, Google Gemini providers
    """

    def __init__(self):
        """Initialize the RCA agent with default Groq LLM as fallback"""
        self.default_llm = None
        self.prompt = None
        self.capability_resolver = IntegrationCapabilityResolver(only_healthy=True)
        self._initialize_prompt()
        self._initialize_default_llm()

    def _initialize_prompt(self):
        """Initialize the shared prompt template"""
        # Create chat prompt template with system message, environment context, service mapping, and thread history
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    RCA_SYSTEM_PROMPT
                    + "\n\n{environment_context_text}"
                    + "\n\n## 📋 SERVICE→REPOSITORY MAPPING\n\n{service_mapping_text}\n\n{thread_history_text}",
                ),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ]
        )

    def _format_environment_context(self, environment_context: Dict[str, Any]) -> str:
        """
        Format environment context for injection into the prompt.

        Args:
            environment_context: Dictionary containing:
                - environments: List of {name, is_default} dicts
                - default_environment: Name of the default environment
                - deployed_commits_by_environment: Dict of env_name -> {repo_full_name -> {commit_sha, deployed_at}}

        Returns:
            Formatted string for the prompt
        """
        if not environment_context:
            return "## 🌍 AVAILABLE ENVIRONMENTS\n\n(No environments configured - code will be read from HEAD)"

        environments = environment_context.get("environments", [])
        default_env = environment_context.get("default_environment")
        deployed_commits_by_env = environment_context.get(
            "deployed_commits_by_environment", {}
        )

        lines = ["## 🌍 AVAILABLE ENVIRONMENTS", ""]

        if environments:
            for env in environments:
                name = env.get("name", "unknown")
                is_default = env.get("is_default", False)
                suffix = " (default)" if is_default else ""
                lines.append(f"- `{name}`{suffix}")
        else:
            lines.append("(No environments configured)")

        if default_env:
            lines.append(
                f"\n**Default environment for investigation:** `{default_env}`"
            )

        if deployed_commits_by_env:
            lines.append("\n## 📦 DEPLOYED COMMITS BY ENVIRONMENT")
            lines.append("")
            lines.append(
                "Use these commit SHAs when reading repository code (pass as `ref` parameter to `download_file_tool`):"
            )

            total_commits = 0
            for env_name, commits in deployed_commits_by_env.items():
                # Find if this environment is the default
                is_default = any(
                    e.get("name") == env_name and e.get("is_default")
                    for e in environments
                )
                suffix = " (default)" if is_default else ""
                lines.append(f"\n**{env_name}**{suffix}:")

                if commits:
                    for repo, commit_info in commits.items():
                        if isinstance(commit_info, dict):
                            sha = commit_info.get("commit_sha", "HEAD")
                            deployed_at = commit_info.get("deployed_at", "unknown")
                            lines.append(
                                f"- `{repo}` → `{sha}` (deployed: {deployed_at})"
                            )
                        else:
                            # Handle legacy format where commit_info is just the sha string
                            lines.append(f"- `{repo}` → `{commit_info}`")
                        total_commits += 1
                else:
                    lines.append("- (No deployments recorded)")
        else:
            lines.append("\n## 📦 DEPLOYED COMMITS")
            lines.append("")
            lines.append("(No deployment data available - code will be read from HEAD)")
            total_commits = 0

        logger.info(
            f"Formatted environment context: {len(environments)} environments, "
            f"default={default_env}, {total_commits} total deployed commits across all environments"
        )

        return "\n".join(lines)

    def _initialize_default_llm(self):
        """Initialize the default Groq LLM as fallback for workspaces without BYOLLM config"""
        try:
            if not settings.GROQ_API_KEY:
                logger.warning(
                    "GROQ_API_KEY not configured - default LLM not available. "
                    "Workspaces must configure BYOLLM."
                )
                return

            self.default_llm = ChatGroq(
                api_key=settings.GROQ_API_KEY,
                model=settings.GROQ_LLM_MODEL,  # Groq's best model for reasoning
                temperature=settings.RCA_AGENT_TEMPERATURE,
                max_tokens=settings.RCA_AGENT_MAX_TOKENS,
            )

            logger.info(
                f"RCA Agent default LLM initialized with Groq model: {settings.GROQ_LLM_MODEL}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize default RCA agent LLM: {e}")
            # Don't raise - workspaces with BYOLLM can still work

    async def _get_llm_for_workspace(
        self,
        workspace_id: str,
        db: AsyncSession,
    ) -> BaseChatModel:
        """
        Get the appropriate LLM for a workspace.

        Uses workspace-specific LLM config if available (BYOLLM),
        otherwise falls back to the default Groq LLM.

        Args:
            workspace_id: The workspace ID
            db: Database session

        Returns:
            BaseChatModel: The LLM instance to use
        """
        try:
            # Try to get workspace-specific LLM
            llm = await get_llm_for_workspace(
                workspace_id=workspace_id,
                db=db,
                temperature=settings.RCA_AGENT_TEMPERATURE,
                max_tokens=settings.RCA_AGENT_MAX_TOKENS,
            )
            return llm

        except Exception as e:
            logger.warning(
                f"Failed to get workspace-specific LLM for {workspace_id}: {e}. "
                f"Falling back to default LLM."
            )

            # Fall back to default LLM
            if self.default_llm:
                return self.default_llm

            # If no default LLM, raise error
            raise ValueError("No LLM available. Configure BYOLLM or set GROQ_API_KEY.")

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
        1. Gets workspace-specific LLM (BYOLLM or default Groq)
        2. Resolves workspace integrations to capabilities
        3. Filters tools based on available capabilities
        4. Binds workspace_id to selected tools
        5. Creates the agent executor

        Args:
            workspace_id: The workspace ID
            db: Database session for querying integrations
            service_mapping: Optional service→repo mapping
            thread_history: Optional thread history

        Returns:
            AgentExecutor configured with workspace-specific LLM and capability-filtered tools
        """
        # Get workspace-specific LLM (BYOLLM or fallback to default Groq)
        workspace_llm = await self._get_llm_for_workspace(workspace_id, db)

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
            k: v for k, v in execution_context.integrations.items() if k != "slack"
        }
        if not rca_integrations or not execution_context.capabilities:
            logger.warning(
                f"No healthy integrations with RCA capabilities for workspace {workspace_id}. "
                f"Available integrations: {list(execution_context.integrations.keys())}"
            )
            raise NoHealthyIntegrationsError(
                "No healthy integrations available for RCA analysis"
            )

        # Build agent executor with workspace-specific LLM and filtered tools
        builder = AgentExecutorBuilder(workspace_llm, self.prompt)
        executor = builder.with_context(execution_context).build()

        logger.info(
            f"Created agent executor for workspace {workspace_id} "
            f"with {len(executor.tools)} tools (capability-filtered), "
            f"LLM: {type(workspace_llm).__name__}"
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
                error_msg = (
                    "db session is required for capability-based tool resolution"
                )
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

            # Extract and format environment context
            environment_context = (context or {}).get("environment_context", {})
            environment_context_text = self._format_environment_context(
                environment_context
            )

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
                "environment_context_text": environment_context_text,
                "service_mapping_text": service_mapping_text,
                "thread_history_text": thread_history_text,
            }

            # Log context details before LLM API call for debugging context length issues
            # Model context windows: llama-3.3-70b-versatile = 128K tokens, gemini-2.0-flash-exp = 1M tokens
            system_prompt_len = len(RCA_SYSTEM_PROMPT)
            environment_context_len = len(environment_context_text)
            thread_history_len = len(thread_history_text)
            service_mapping_len = len(service_mapping_text)
            user_query_len = len(user_query)
            total_chars = (
                system_prompt_len
                + environment_context_len
                + thread_history_len
                + service_mapping_len
                + user_query_len
            )

            # Rough token estimate (1 token ≈ 4 characters for English text)
            estimated_tokens = total_chars // 4

            logger.info(
                f"📊 Context size before LLM call (model: {settings.GROQ_LLM_MODEL}):\n"
                f"  - System prompt: {system_prompt_len} chars\n"
                f"  - Environment context: {environment_context_len} chars\n"
                f"  - Thread history: {thread_history_len} chars ({len(thread_history)} messages)\n"
                f"  - Service mapping: {service_mapping_len} chars ({len(service_repo_mapping)} services)\n"
                f"  - User query: {user_query_len} chars\n"
                f"  - Total input: {total_chars} chars (~{estimated_tokens} tokens est.)\n"
                f"  - Max output tokens: {settings.RCA_AGENT_MAX_TOKENS}"
            )

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
                "output": result.get(
                    "output", "Analysis completed but no output generated."
                ),
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
            is_context_length_error = False

            # Extract failed_generation from Groq API errors if available
            if hasattr(e, "body") and isinstance(e.body, dict):
                error_body = e.body
                if "error" in error_body and isinstance(error_body["error"], dict):
                    error_info = error_body["error"]
                    error_details["error_code"] = error_info.get("code")
                    error_details["error_type_api"] = error_info.get("type")

                    # Check if this is a context_length_exceeded error
                    if error_info.get("code") == "context_length_exceeded":
                        is_context_length_error = True

                    # Capture failed_generation for debugging
                    if "failed_generation" in error_info:
                        error_details["failed_generation"] = error_info[
                            "failed_generation"
                        ]
                        logger.error(
                            f"Groq API tool_use_failed - failed_generation: {error_info['failed_generation']}"
                        )

            # Special logging for context_length_exceeded errors
            if is_context_length_error:
                # Log complete context details for debugging
                logger.error(
                    f"🚨 CONTEXT_LENGTH_EXCEEDED ERROR DETECTED 🚨\n"
                    f"Model: {settings.GROQ_LLM_MODEL}\n"
                    f"Max output tokens configured: {settings.RCA_AGENT_MAX_TOKENS}\n"
                    f"System prompt length: {len(RCA_SYSTEM_PROMPT)} chars\n"
                    f"Thread history length: {len(thread_history_text)} chars\n"
                    f"Service mapping length: {len(service_mapping_text)} chars\n"
                    f"User query length: {len(user_query)} chars\n"
                    f"Error details: {error_details}"
                )
                # Add context_length_exceeded flag to error response for fallback handling
                error_details["is_context_length_error"] = True

            logger.error(f"Error during RCA analysis: {error_details}", exc_info=True)
            return {
                "output": None,
                "intermediate_steps": [],
                "success": False,
                "error": f"RCA analysis failed: {str(e)}",
                "error_details": error_details,  # Include error details for fallback logic
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
        Perform RCA analysis with automatic retry on failure.

        If Groq fails with context_length_exceeded or any LLM API error,
        automatically falls back to Gemini agent.

        Args:
            user_query: User's question
            context: Optional context
            max_retries: Maximum number of retry attempts
            callbacks: Optional callback handlers
            db: Database session for querying integrations (required)

        Returns:
            Analysis result dictionary
        """
        gemini_fallback_attempted = False
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

                # Check if this is a context_length_exceeded error or any LLM API error
                error_details = result.get("error_details", {})
                is_llm_error = (
                    error_details.get("is_context_length_error", False)
                    or error_details.get("error_code") is not None
                )

                if is_llm_error and not gemini_fallback_attempted:
                    gemini_fallback_attempted = True
                    logger.warning(
                        f"⚠️ Groq LLM error detected on attempt {attempt + 1}. "
                        f"Attempting fallback to Gemini agent with larger context window..."
                    )

                    # Try Gemini as fallback
                    try:
                        logger.info(
                            f"🔄 Switching from Groq ({settings.GROQ_LLM_MODEL}) to Gemini ({settings.GEMINI_LLM_MODEL}) "
                            f"due to LLM error: {error_details.get('error_code', 'unknown')}"
                        )

                        gemini_result = await gemini_rca_agent_service.analyze(
                            user_query, context, callbacks=callbacks, db=db
                        )

                        if gemini_result["success"]:
                            logger.info("✅ Gemini fallback succeeded!")
                            return gemini_result
                        else:
                            logger.warning(
                                f"Gemini fallback also failed: {gemini_result.get('error')}"
                            )
                            # Continue with retry logic

                    except Exception as gemini_error:
                        logger.error(
                            f"Gemini fallback error: {gemini_error}", exc_info=True
                        )
                        # Continue with retry logic

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
