"""
Context formatting utilities for RCA agents.

This module provides reusable helper functions for formatting context information
(environments, services, repositories) for LLM prompts across different LangGraph branches.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from app.models import Integration

from app.services.rca.capabilities import (
    ExecutionContext,
    IntegrationCapabilityResolver,
)
from app.services.rca.state import RCAState


def format_environments_display(env_context: dict) -> str:
    """
    Format environments for LLM display with default marker.

    Args:
        env_context: Environment context dict containing:
            - 'environments': List of dicts with 'name' and 'is_default'
            - 'default_environment': Name of default environment (optional)

    Returns:
        Formatted string like "test, test2 (default)" or empty string if no environments

    Examples:
        >>> env_ctx = {
        ...     "environments": [
        ...         {"name": "test", "is_default": False},
        ...         {"name": "test2", "is_default": True}
        ...     ],
        ...     "default_environment": "test2"
        ... }
        >>> format_environments_display(env_ctx)
        'test, test2 (default)'
    """
    if not env_context or not env_context.get("environments"):
        return ""

    default_env = env_context.get("default_environment")
    envs = []

    for e in env_context["environments"]:
        if isinstance(e, dict):
            name = e.get("name")
            if name:
                # Add "(default)" marker if this is the default environment
                if name == default_env:
                    envs.append(f"{name} (default)")
                else:
                    envs.append(name)

    return ", ".join(envs) if envs else ""


def format_service_mapping_display(service_mapping: dict) -> str:
    """
    Format service→repo mapping for LLM display.

    Args:
        service_mapping: Dict of service_name → repo_name

    Returns:
        Formatted string like "marketplace-service (repo: marketplace), auth-service (repo: auth)"
        or empty string if no services

    Examples:
        >>> mapping = {"marketplace-service": "marketplace", "auth-service": "auth"}
        >>> format_service_mapping_display(mapping)
        'marketplace-service (repo: marketplace), auth-service (repo: auth)'
    """
    if not service_mapping:
        return ""

    formatted_services = [
        f"{service} (repo: {repo})" for service, repo in service_mapping.items()
    ]
    return ", ".join(formatted_services)


def format_integrations_display(
    integrations: Dict[str, "Integration"],
    all_integration_types: Set[str],
) -> str:
    """
    Format integration status for LLM display.

    Shows which integrations are configured (with status/health) and which are not configured.

    Args:
        integrations: Dict of provider -> Integration objects
        all_integration_types: Set of all possible integration types (from capability map)

    Returns:
        Formatted string like "Configured integrations: github (active, healthy); Not configured: aws, datadog"
        or empty string if no integration types provided

    Examples:
        >>> # With mock Integration objects
        >>> integrations = {"github": MockIntegration(status="active", health_status="healthy")}
        >>> all_types = {"github", "aws", "datadog"}
        >>> format_integrations_display(integrations, all_types)
        'Configured integrations: github (active, healthy); Not configured: aws, datadog'
    """
    if not all_integration_types:
        return ""

    parts = []
    configured = []

    for provider in sorted(all_integration_types):
        if provider in integrations:
            integration = integrations[provider]
            status = integration.status or "active"
            health = integration.health_status or "unchecked"
            configured.append(f"{provider} ({status}, {health})")

    if configured:
        parts.append(f"Configured integrations: {', '.join(configured)}")

    not_configured = sorted([p for p in all_integration_types if p not in integrations])

    if not_configured:
        parts.append(f"Not configured: {', '.join(not_configured)}")

    return "; ".join(parts)


def build_context_string(
    execution_context: ExecutionContext,
    state: RCAState,
    include_services: bool = True,
    include_environments: bool = True,
    include_deployed_commits: bool = True,
    include_integrations: bool = True,
) -> str:
    """
    Build complete context string for LLM prompts.

    Combines integrations, services, environments, deployed commits, and other context
    information into a single formatted string that can be appended to queries.

    Args:
        execution_context: Execution context with service mappings and capabilities
        state: RCA state containing environment context
        include_services: Whether to include service mapping in output
        include_environments: Whether to include environments in output
        include_deployed_commits: Whether to include deployed commits for default environment
        include_integrations: Whether to include integration status in output

    Returns:
        Complete context string like:
        "Configured integrations: github (active, healthy); Not configured: aws, datadog;
         Available services: marketplace-service (repo: marketplace);
         Available environments: test, test2 (default);
         Deployed commits: test: marketplace@abc123"
        or empty string if no context available

    Examples:
        >>> # Mock execution context and state
        >>> context = ExecutionContext(
        ...     workspace_id="123",
        ...     capabilities=set(),
        ...     integrations={},
        ...     service_mapping={"marketplace-service": "marketplace"}
        ... )
        >>> state = {
        ...     "context": {
        ...         "environment_context": {
        ...             "environments": [{"name": "prod", "is_default": True}],
        ...             "default_environment": "prod",
        ...             "deployed_commits_by_environment": {
        ...                 "prod": {"marketplace": "abc123"}
        ...             }
        ...         }
        ...     }
        ... }
        >>> build_context_string(context, state)
        'Available services: marketplace-service (repo: marketplace); Available environments: prod (default); Deployed commits: prod: marketplace@abc123'
    """
    context_parts = []

    # Add integration status first
    if include_integrations:
        all_types = set(IntegrationCapabilityResolver.INTEGRATION_CAPABILITY_MAP.keys())
        integrations_str = format_integrations_display(
            execution_context.integrations,
            all_types,
        )
        if integrations_str:
            context_parts.append(integrations_str)

    # Add service mapping
    if include_services:
        service_mapping = execution_context.service_mapping or {}
        if service_mapping:
            services_str = format_service_mapping_display(service_mapping)
            if services_str:
                context_parts.append(f"Available services: {services_str}")

    # Add environments
    if include_environments:
        env_context = state.get("context", {}).get("environment_context", {})
        if env_context:
            envs_str = format_environments_display(env_context)
            if envs_str:
                context_parts.append(f"Available environments: {envs_str}")

    # Add deployed commits for default environment
    if include_deployed_commits:
        deployed_str = format_deployed_commits_display(state)
        if deployed_str:
            context_parts.append(f"Deployed commits: {deployed_str}")

    return "; ".join(context_parts)


def get_default_environment(state: RCAState) -> Optional[str]:
    """
    Extract the default environment name from state.

    Args:
        state: RCA state containing environment context

    Returns:
        Name of default environment or None if not set

    Examples:
        >>> state = {
        ...     "context": {
        ...         "environment_context": {
        ...             "default_environment": "production"
        ...         }
        ...     }
        ... }
        >>> get_default_environment(state)
        'production'
    """
    env_context = state.get("context", {}).get("environment_context", {})
    return env_context.get("default_environment")


def get_environment_list(state: RCAState) -> List[str]:
    """
    Extract list of environment names from state.

    Args:
        state: RCA state containing environment context

    Returns:
        List of environment names

    Examples:
        >>> state = {
        ...     "context": {
        ...         "environment_context": {
        ...             "environments": [
        ...                 {"name": "dev", "is_default": False},
        ...                 {"name": "prod", "is_default": True}
        ...             ]
        ...         }
        ...     }
        ... }
        >>> get_environment_list(state)
        ['dev', 'prod']
    """
    env_context = state.get("context", {}).get("environment_context", {})
    environments = env_context.get("environments", [])

    return [
        e.get("name") for e in environments if isinstance(e, dict) and e.get("name")
    ]


def get_deployed_commits(
    state: RCAState, environment_name: Optional[str] = None
) -> Dict[str, str]:
    """
    Get deployed commits for a specific environment or default environment.

    Args:
        state: RCA state containing environment context
        environment_name: Environment name, or None to use default environment

    Returns:
        Dict of repo_name → commit_sha for the environment

    Examples:
        >>> state = {
        ...     "context": {
        ...         "environment_context": {
        ...             "default_environment": "prod",
        ...             "deployed_commits_by_environment": {
        ...                 "prod": {"marketplace": "abc123def"}
        ...             }
        ...         }
        ...     }
        ... }
        >>> get_deployed_commits(state)
        {'marketplace': 'abc123def'}
    """
    env_context = state.get("context", {}).get("environment_context", {})
    deployed_commits_by_env = env_context.get("deployed_commits_by_environment", {})

    # Determine which environment to use
    env_name = environment_name
    if not env_name:
        env_name = env_context.get("default_environment")

    if not env_name:
        return {}

    return deployed_commits_by_env.get(env_name, {})


def get_thread_history(state: RCAState) -> Optional[str]:
    """
    Extract thread history from state.

    Thread history contains previous messages in the conversation,
    useful for understanding context in multi-turn conversations.

    Args:
        state: RCA state containing thread history

    Returns:
        Thread history string or None if not available

    Examples:
        >>> state = {
        ...     "context": {
        ...         "thread_history": "User: what environments do I have?\\nBot: You have prod and dev."
        ...     }
        ... }
        >>> get_thread_history(state)
        'User: what environments do I have?\\nBot: You have prod and dev.'
    """
    return state.get("context", {}).get("thread_history")


def format_thread_history_for_prompt(state: RCAState, max_length: int = 2000) -> str:
    """
    Format thread history for inclusion in LLM prompts.

    Args:
        state: RCA state containing thread history
        max_length: Maximum length of history to include (default: 2000 chars)

    Returns:
        Formatted thread history string, or empty string if no history

    Examples:
        >>> state = {
        ...     "context": {
        ...         "thread_history": "User: hi\\nBot: Hello! How can I help?"
        ...     }
        ... }
        >>> format_thread_history_for_prompt(state)
        'Previous conversation:\\nUser: hi\\nBot: Hello! How can I help?'
    """
    thread_history = get_thread_history(state)
    if not thread_history:
        return ""

    # Truncate if too long (keep most recent messages)
    if len(thread_history) > max_length:
        thread_history = "..." + thread_history[-(max_length - 3) :]

    return f"Previous conversation:\n{thread_history}"


def format_deployed_commits_display(
    state: RCAState, environment_name: Optional[str] = None
) -> str:
    """
    Format deployed commits for LLM display.

    Shows which commits are currently deployed in an environment.
    Uses actual deployment data from the database, not GitHub API.

    Args:
        state: RCA state containing environment context with deployed commits
        environment_name: Specific environment name, or None to use default environment

    Returns:
        Formatted string like "test: marketplace@abc123, auth@def456"
        or "test: No deployments configured" if no commits are deployed

    Examples:
        >>> state = {
        ...     "context": {
        ...         "environment_context": {
        ...             "default_environment": "prod",
        ...             "deployed_commits_by_environment": {
        ...                 "prod": {"marketplace": "abc123", "auth": "def456"}
        ...             }
        ...         }
        ...     }
        ... }
        >>> format_deployed_commits_display(state)
        'prod: marketplace@abc123, auth@def456'

        >>> # With specific environment
        >>> format_deployed_commits_display(state, environment_name="prod")
        'prod: marketplace@abc123, auth@def456'

        >>> # No deployments
        >>> state_empty = {
        ...     "context": {
        ...         "environment_context": {
        ...             "default_environment": "test",
        ...             "deployed_commits_by_environment": {"test": {}}
        ...         }
        ...     }
        ... }
        >>> format_deployed_commits_display(state_empty)
        'test: No deployments configured'
    """
    deployed_commits = get_deployed_commits(state, environment_name)

    # Determine which environment we're showing
    env_name = environment_name or get_default_environment(state)

    if not env_name:
        return ""

    if not deployed_commits:
        return f"{env_name}: No deployments configured"

    # Format as "repo@commit_sha" (shortened to 7 chars)
    # Handle both string format and dict format from worker
    commit_list = []
    for repo, commit_data in deployed_commits.items():
        commit_sha = None

        # Handle dict format: {"commit_sha": "...", "deployed_at": "..."}
        if isinstance(commit_data, dict):
            commit_sha = commit_data.get("commit_sha")
        # Handle string format: "abc123..."
        elif isinstance(commit_data, str):
            commit_sha = commit_data

        # Only include if we have a valid commit SHA
        if commit_sha and isinstance(commit_sha, str):
            commit_list.append(f"{repo}@{commit_sha[:7]}")

    if not commit_list:
        return f"{env_name}: No deployments configured"

    return f"{env_name}: {', '.join(commit_list)}"


def get_context_summary(
    execution_context: ExecutionContext, state: RCAState
) -> Dict[str, Any]:
    """
    Get a structured summary of all available context.

    Useful for debugging or providing structured context to agents.

    Args:
        execution_context: Execution context with service mappings and capabilities
        state: RCA state containing environment context

    Returns:
        Dict containing:
            - services: List of service names
            - service_count: Number of services
            - service_mapping: Full service→repo mapping
            - environments: List of environment names
            - default_environment: Default environment name or None
            - env_count: Number of environments
            - deployed_commits: Deployed commits for default environment
            - configured_integrations: List of configured integration providers
            - not_configured_integrations: List of not configured integration providers

    Examples:
        >>> summary = get_context_summary(execution_context, state)
        >>> summary['service_count']
        2
        >>> summary['default_environment']
        'production'
    """
    service_mapping = execution_context.service_mapping or {}

    environments = get_environment_list(state)
    default_env = get_default_environment(state)
    deployed_commits = get_deployed_commits(state)
    thread_history = get_thread_history(state)

    # Get integration info
    all_integration_types = set(
        IntegrationCapabilityResolver.INTEGRATION_CAPABILITY_MAP.keys()
    )
    configured_integrations = sorted(
        [p for p in all_integration_types if p in execution_context.integrations]
    )
    not_configured_integrations = sorted(
        [p for p in all_integration_types if p not in execution_context.integrations]
    )

    return {
        "services": list(service_mapping.keys()),
        "service_count": len(service_mapping),
        "service_mapping": service_mapping,
        "environments": environments,
        "default_environment": default_env,
        "env_count": len(environments),
        "deployed_commits": deployed_commits,
        "thread_history": thread_history,
        "configured_integrations": configured_integrations,
        "not_configured_integrations": not_configured_integrations,
    }
