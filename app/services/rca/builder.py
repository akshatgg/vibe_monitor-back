"""
Agent Executor Builder with capability-based tool filtering.
Constructs RCA agent with only the tools matching workspace capabilities.
"""

import logging
from functools import partial
from typing import List, Optional

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import StructuredTool

from app.core.config import settings
from app.services.rca.capabilities import Capability, ExecutionContext

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Registry mapping capabilities to tools.
    Centralizes tool→capability relationships.
    """

    def __init__(self):
        """Initialize tool registry with lazy imports."""
        self._tools_cache = None

    def _load_tools(self):
        """Lazy load tools to avoid circular imports."""
        if self._tools_cache is not None:
            return self._tools_cache

        # Import tools (lazy to avoid circular imports at module load)
        from app.services.rca.tools.cloudwatch.tools import (
            execute_cloudwatch_insights_query_tool,
            filter_cloudwatch_log_events_tool,
            get_cloudwatch_metric_statistics_tool,
            list_cloudwatch_log_groups_tool,
            list_cloudwatch_metrics_tool,
            list_cloudwatch_namespaces_tool,
            search_cloudwatch_logs_tool,
        )
        from app.services.rca.tools.code_parser.tools import parse_code_tool
        from app.services.rca.tools.datadog.tools import (
            list_datadog_log_services_tool,
            list_datadog_logs_tool,
            list_datadog_tags_tool,
            query_datadog_metrics_tool,
            query_datadog_timeseries_tool,
            search_datadog_events_tool,
            search_datadog_logs_tool,
        )
        from app.services.rca.tools.github.tools import (
            download_file_tool,
            get_branch_recent_commits_tool,
            get_repository_commits_tool,
            get_repository_metadata_tool,
            get_repository_tree_tool,
            list_pull_requests_tool,
            read_repository_file_tool,
            search_code_tool,
        )
        from app.services.rca.tools.grafana.tools import (
            fetch_cpu_metrics_tool,
            fetch_error_logs_tool,
            fetch_http_latency_tool,
            fetch_logs_tool,
            fetch_memory_metrics_tool,
            fetch_metrics_tool,
            get_datasources_tool,
            get_label_values_tool,
            get_labels_tool,
        )
        from app.services.rca.tools.newrelic.tools import (
            get_newrelic_infra_metrics_tool,
            get_newrelic_time_series_tool,
            query_newrelic_logs_tool,
            query_newrelic_metrics_tool,
            search_newrelic_logs_tool,
        )

        # Map capabilities to tools
        self._tools_cache = {
            Capability.LOGS: [
                fetch_error_logs_tool,
                fetch_logs_tool,
            ],
            Capability.METRICS: [
                fetch_cpu_metrics_tool,
                fetch_memory_metrics_tool,
                fetch_http_latency_tool,
                fetch_metrics_tool,
            ],
            Capability.DATASOURCES: [
                get_datasources_tool,
                get_labels_tool,
                get_label_values_tool,
            ],
            Capability.CODE_SEARCH: [
                search_code_tool,
            ],
            Capability.CODE_READ: [
                read_repository_file_tool,
                download_file_tool,
                parse_code_tool,
            ],
            Capability.REPOSITORY_INFO: [
                get_repository_commits_tool,
                list_pull_requests_tool,
                get_repository_tree_tool,
                get_branch_recent_commits_tool,
                get_repository_metadata_tool,
            ],
            Capability.AWS_LOGS: [
                list_cloudwatch_log_groups_tool,
                filter_cloudwatch_log_events_tool,
                search_cloudwatch_logs_tool,
                execute_cloudwatch_insights_query_tool,
            ],
            Capability.AWS_METRICS: [
                list_cloudwatch_metrics_tool,
                get_cloudwatch_metric_statistics_tool,
                list_cloudwatch_namespaces_tool,
            ],
            Capability.DATADOG_LOGS: [
                search_datadog_logs_tool,
                list_datadog_logs_tool,
                list_datadog_log_services_tool,
                list_datadog_tags_tool,
                search_datadog_events_tool,
            ],
            Capability.DATADOG_METRICS: [
                query_datadog_metrics_tool,
                query_datadog_timeseries_tool,
            ],
            Capability.NEWRELIC_LOGS: [
                query_newrelic_logs_tool,
                search_newrelic_logs_tool,
            ],
            Capability.NEWRELIC_METRICS: [
                query_newrelic_metrics_tool,
                get_newrelic_time_series_tool,
                get_newrelic_infra_metrics_tool,
            ],
        }

        return self._tools_cache

    def get_tools_for_capabilities(self, capabilities: set[Capability]) -> List:
        """
        Get tools for given capabilities.

        Args:
            capabilities: Set of capabilities

        Returns:
            List of tools
        """
        tools_map = self._load_tools()
        tools = []

        for capability in capabilities:
            capability_tools = tools_map.get(capability, [])
            tools.extend(capability_tools)

        return tools


class AgentExecutorBuilder:
    """
    Builder for creating workspace-specific agent executors.

    Usage:
        builder = AgentExecutorBuilder(llm, prompt)
        executor = (
            builder
            .with_context(execution_context)
            .with_callbacks(callbacks)
            .build()
        )
    """

    def __init__(
        self,
        llm: BaseChatModel,
        prompt: ChatPromptTemplate,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        """
        Initialize agent executor builder.

        Args:
            llm: Language model
            prompt: Prompt template
            tool_registry: Tool registry (creates default if None)
        """
        self.llm = llm
        self.prompt = prompt
        self.tool_registry = tool_registry or ToolRegistry()

        # Builder state
        self._context: Optional[ExecutionContext] = None
        self._callbacks: Optional[List] = None
        self._max_iterations: int = settings.RCA_AGENT_MAX_ITERATIONS
        self._max_execution_time: int = settings.RCA_AGENT_MAX_EXECUTION_TIME

    def with_context(self, context: ExecutionContext) -> "AgentExecutorBuilder":
        """
        Set execution context.

        Args:
            context: Execution context with workspace and capabilities

        Returns:
            Self for chaining
        """
        self._context = context
        return self

    def with_capabilities(self, capabilities: set) -> "AgentExecutorBuilder":
        """
        Override capabilities on the execution context.

        Args:
            capabilities: Set of Capability enums to use

        Returns:
            Self for chaining

        Raises:
            ValueError: If context not set
        """
        if self._context is None:
            raise ValueError(
                "Execution context must be set before overriding capabilities"
            )
        self._context.capabilities = capabilities
        return self

    def with_callbacks(self, callbacks: List) -> "AgentExecutorBuilder":
        """
        Set callbacks for agent execution.

        Args:
            callbacks: List of callback handlers

        Returns:
            Self for chaining
        """
        self._callbacks = callbacks
        return self

    def with_limits(
        self,
        max_iterations: Optional[int] = None,
        max_execution_time: Optional[int] = None,
    ) -> "AgentExecutorBuilder":
        """
        Set execution limits.

        Args:
            max_iterations: Maximum iterations
            max_execution_time: Maximum execution time in seconds

        Returns:
            Self for chaining
        """
        if max_iterations is not None:
            self._max_iterations = max_iterations
        if max_execution_time is not None:
            self._max_execution_time = max_execution_time
        return self

    def build(self) -> AgentExecutor:
        """
        Build agent executor with capability-filtered tools.

        Returns:
            AgentExecutor configured for workspace

        Raises:
            ValueError: If context not set
        """
        if self._context is None:
            raise ValueError("Execution context must be set before building")

        workspace_id = self._context.workspace_id
        capabilities = self._context.capabilities

        logger.info(
            f"Building agent executor for workspace {workspace_id} "
            f"with capabilities: {[c.value for c in capabilities]}"
        )

        # Get tools for capabilities
        available_tools = self.tool_registry.get_tools_for_capabilities(capabilities)

        logger.info(f"Selected {len(available_tools)} tools based on capabilities")

        # Bind workspace_id to each tool
        tools_with_workspace = self._bind_workspace_to_tools(
            available_tools, workspace_id
        )
        # Create agent
        agent = create_tool_calling_agent(
            llm=self.llm,
            tools=tools_with_workspace,
            prompt=self.prompt,
        )

        # Create executor
        executor = AgentExecutor(
            agent=agent,
            tools=tools_with_workspace,
            verbose=True,
            max_iterations=self._max_iterations,
            max_execution_time=self._max_execution_time,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
            callbacks=self._callbacks,
        )

        return executor

    def _bind_workspace_to_tools(
        self, tools: List, workspace_id: str
    ) -> List[StructuredTool]:
        """
        Bind workspace_id to tools using functools.partial.

        Args:
            tools: List of tools
            workspace_id: Workspace ID

        Returns:
            List of workspace-bound tools
        """
        bound_tools = []

        for tool in tools:
            if tool.args_schema is None:
                bound_tools.append(tool)
                continue

            if "workspace_id" not in tool.args_schema.model_fields:
                bound_tools.append(tool)
                continue

            # Create schema without workspace_id (it's pre-bound)
            modified_schema = self._create_schema_without_workspace_id(tool.args_schema)

            # Wrap tool with pre-bound workspace_id
            wrapped_tool = StructuredTool.from_function(
                coroutine=partial(tool.coroutine, workspace_id=workspace_id),
                name=tool.name,
                description=tool.description,
                args_schema=modified_schema,
            )

            bound_tools.append(wrapped_tool)

        return bound_tools

    def _create_schema_without_workspace_id(self, schema_class):
        """
        Create modified schema excluding workspace_id field.

        Args:
            schema_class: Original Pydantic schema

        Returns:
            Modified schema class
        """
        if schema_class is None:
            return None

        # Get all fields except workspace_id
        fields = {
            name: (field.annotation, field)
            for name, field in schema_class.model_fields.items()
            if name != "workspace_id"
        }

        # Create new schema class
        from pydantic import create_model

        modified_schema = create_model(
            f"{schema_class.__name__}WithoutWorkspace", **fields
        )

        return modified_schema


class AgentExecutorFactory:
    """
    Factory for creating agent executors with different configurations.
    Provides convenience methods for common use cases.
    """

    @staticmethod
    def create_for_workspace(
        llm: BaseChatModel,
        prompt: ChatPromptTemplate,
        context: ExecutionContext,
        callbacks: Optional[List] = None,
    ) -> AgentExecutor:
        """
        Create agent executor for workspace with default settings.

        Args:
            llm: Language model
            prompt: Prompt template
            context: Execution context
            callbacks: Optional callbacks

        Returns:
            AgentExecutor
        """
        builder = AgentExecutorBuilder(llm, prompt)

        executor = builder.with_context(context).with_callbacks(callbacks or []).build()

        return executor

    @staticmethod
    def create_readonly_executor(
        llm: BaseChatModel,
        prompt: ChatPromptTemplate,
        context: ExecutionContext,
    ) -> AgentExecutor:
        """
        Create read-only executor (for PLG/free tier).

        Restrictions:
        - Limited iterations
        - Shorter execution time
        - Only read operations allowed

        Args:
            llm: Language model
            prompt: Prompt template
            context: Execution context

        Returns:
            AgentExecutor with read-only restrictions
        """
        builder = AgentExecutorBuilder(llm, prompt)

        # TODO: Filter context.capabilities to only read operations
        # readonly_capabilities = filter_readonly_capabilities(context.capabilities)

        executor = (
            builder.with_context(context)
            .with_limits(
                max_iterations=10,  # Reduced for free tier
                max_execution_time=120,  # 2 minutes max
            )
            .build()
        )

        return executor
