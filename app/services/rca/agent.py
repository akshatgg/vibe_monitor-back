"""
RCA Agent Service using LangChain with Groq LLM
"""

import logging
import re
from functools import partial
from typing import Dict, Any, Optional
from pydantic import BaseModel, create_model
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.tools import StructuredTool
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from .prompts import RCA_SYSTEM_PROMPT
from .tools.grafana.tools import (
    fetch_logs_tool,
    fetch_error_logs_tool,
    fetch_cpu_metrics_tool,
    fetch_memory_metrics_tool,
    fetch_http_latency_tool,
    fetch_metrics_tool,
    get_datasources_tool,
    get_labels_tool,
    get_label_values_tool,
)

from .tools.github.tools import (
    get_repository_commits_tool,
    list_pull_requests_tool,
    search_code_tool,
    download_file_tool,
    read_repository_file_tool,
    get_repository_tree_tool,
    get_branch_recent_commits_tool,
    get_repository_metadata_tool,
)

logger = logging.getLogger(__name__)

# Define all available RCA tools in one place (single source of truth)
ALL_RCA_TOOLS = [
    # Grafana/Observability tools
    fetch_error_logs_tool,
    fetch_logs_tool,
    fetch_cpu_metrics_tool,
    fetch_memory_metrics_tool,
    fetch_http_latency_tool,
    fetch_metrics_tool,
    get_datasources_tool,
    get_labels_tool,
    get_label_values_tool,
    # GitHub tools
    read_repository_file_tool,
    search_code_tool,
    get_repository_commits_tool,
    list_pull_requests_tool,
    download_file_tool,
    get_repository_tree_tool,
    get_branch_recent_commits_tool,
    get_repository_metadata_tool,
]


class RCAAgentService:
    """
    Service for Root Cause Analysis using AI agent with ReAct pattern
    """

    def __init__(self):
        """Initialize the RCA agent with Groq LLM (shared across all requests)"""
        self.llm = None
        self.prompt = None
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
            self.prompt = ChatPromptTemplate.from_messages([
                ("system", RCA_SYSTEM_PROMPT + "\n\n## 📋 SERVICE→REPOSITORY MAPPING\n\n{service_mapping_text}\n\n{thread_history_text}"),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ])

            logger.info("RCA Agent LLM initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize RCA agent LLM: {e}")
            raise

    def _create_schema_without_workspace_id(
        self, original_schema: type[BaseModel]
    ) -> type[BaseModel]:
        """
        Create a new Pydantic schema excluding the workspace_id field.

        Args:
            original_schema: The original tool schema that includes workspace_id

        Returns:
            A new schema with workspace_id field removed
        """
        # Get all fields except workspace_id
        fields = {
            name: (field.annotation, field)
            for name, field in original_schema.model_fields.items()
            if name != "workspace_id"
        }

        # Create new model without workspace_id
        new_schema = create_model(
            f"{original_schema.__name__}WithoutWorkspace", **fields
        )

        return new_schema

    def _create_agent_executor_for_workspace(self, workspace_id: str) -> AgentExecutor:
        """
        Create a workspace-specific agent executor with tools bound to the given workspace_id.

        This method creates a new executor for each request to ensure thread-safety and
        prevent workspace_id conflicts between concurrent requests.

        Args:
            workspace_id: The workspace ID to bind to all tools

        Returns:
            AgentExecutor configured for the specific workspace
        """
        # Dynamically bind workspace_id to all tools with modified schemas
        tools_with_workspace = []

        for tool in ALL_RCA_TOOLS:
            # Create schema without workspace_id (since it's pre-bound)
            modified_schema = self._create_schema_without_workspace_id(tool.args_schema)

            # Create wrapped tool with partial application and modified schema
            wrapped_tool = StructuredTool.from_function(
                coroutine=partial(tool.coroutine, workspace_id=workspace_id),
                name=tool.name,
                description=tool.description,
                args_schema=modified_schema,
            )

            tools_with_workspace.append(wrapped_tool)

        # Create the tool-calling agent with workspace-specific tools
        agent = create_tool_calling_agent(
            llm=self.llm,
            tools=tools_with_workspace,
            prompt=self.prompt,
        )

        # Create and return executor for this workspace
        executor = AgentExecutor(
            agent=agent,
            tools=tools_with_workspace,
            verbose=True,
            max_iterations=settings.RCA_AGENT_MAX_ITERATIONS,
            max_execution_time=settings.RCA_AGENT_MAX_EXECUTION_TIME,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
        )

        logger.info(f"Created agent executor for workspace: {workspace_id}")
        return executor

    async def analyze(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
        callbacks: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Perform root cause analysis for the given user query

        Args:
            user_query: User's question or issue description (e.g., "Why is my xyz service slow?")
            context: Optional context from Slack (user_id, channel_id, workspace_id, etc.)
            callbacks: Optional list of callback handlers (e.g., for Slack progress updates)

        Returns:
            Dictionary containing:
                - output: The RCA analysis text
                - intermediate_steps: List of reasoning steps taken
                - success: Whether analysis completed successfully
                - error: Error message if failed
        """
        try:
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

            logger.info(
                f"Starting RCA analysis for query: '{user_query}' (workspace: {workspace_id})"
            )

            # Create workspace-specific agent executor
            agent_executor = self._create_agent_executor_for_workspace(workspace_id)

            # Extract service→repo mapping from context
            service_repo_mapping = (context or {}).get("service_repo_mapping", {})

            # Format the mapping for the prompt
            if service_repo_mapping:
                mapping_lines = [f"- Service `{service}` → Repository `{repo}`"
                                for service, repo in service_repo_mapping.items()]
                service_mapping_text = "\n".join(mapping_lines)
                logger.info(f"Injecting service→repo mapping with {len(service_repo_mapping)} entries")
            else:
                service_mapping_text = "(No services discovered - workspace may have no repositories)"
                logger.warning("No service→repo mapping provided in context")

            # Extract and format thread history from context
            thread_history = (context or {}).get("thread_history", [])

            if thread_history:
                logger.info(f"Formatting thread history with {len(thread_history)} messages")

                # Format thread messages as conversation history
                history_lines = ["## 🧵 CONVERSATION HISTORY", ""]
                history_lines.append("This is a follow-up question in an existing thread. Here's the previous conversation:")
                history_lines.append("")

                for msg in thread_history:
                    user_id = msg.get("user", "unknown")
                    text = msg.get("text", "")
                    bot_id = msg.get("bot_id")

                    # Strip bot mentions from message text (e.g., <@U12345678>)
                    clean_text = re.sub(settings.SLACK_USER_MENTION_PATTERN, "", text).strip()

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

            # Prepare input for the agent
            agent_input = {
                "input": user_query,
                "service_mapping_text": service_mapping_text,
                "thread_history_text": thread_history_text,
            }

            # Execute the agent asynchronously with callbacks
            if callbacks:
                result = await agent_executor.ainvoke(agent_input, config={"callbacks": callbacks})
            else:
                result = await agent_executor.ainvoke(agent_input)

            logger.info(
                f"RCA analysis completed successfully for workspace: {workspace_id}"
            )

            return {
                "output": result.get(
                    "output", "Analysis completed but no output generated."
                ),
                "intermediate_steps": result.get("intermediate_steps", []),
                "success": True,
                "error": None,
            }

        except Exception as e:
            logger.error(f"Error during RCA analysis: {e}", exc_info=True)
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
    ) -> Dict[str, Any]:
        """
        Perform RCA analysis with automatic retry on failure

        Args:
            user_query: User's question
            context: Optional context
            max_retries: Maximum number of retry attempts
            callbacks: Optional callback handlers

        Returns:
            Analysis result dictionary
        """
        for attempt in range(max_retries + 1):
            try:
                result = await self.analyze(user_query, context, callbacks=callbacks)

                if result["success"]:
                    return result

                # If analysis didn't succeed but didn't error, retry
                logger.warning(
                    f"Analysis attempt {attempt + 1} did not succeed, retrying..."
                )

            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {e}")

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
