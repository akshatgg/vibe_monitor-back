"""
Integration capability resolver for RCA agent.
Maps workspace integrations to available tools and capabilities.
"""

from enum import Enum
from typing import Set, Dict, List
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession

import logging

from app.integrations.service import (
    get_workspace_integrations,
    check_integration_health,
)
from app.models import Integration

logger = logging.getLogger(__name__)


class Capability(str, Enum):
    """
    Agent capabilities mapped to integration types.
    Each capability represents a group of tools.
    """

    # Observability capabilities (Grafana/Datadog/NewRelic)
    LOGS = "logs"  # Fetch and search logs
    METRICS = "metrics"  # Fetch system metrics (CPU, memory, etc.)
    DATASOURCES = "datasources"  # List available datasources

    # Code capabilities (GitHub)
    CODE_SEARCH = "code_search"  # Search code across repositories
    CODE_READ = "code_read"  # Read files from repositories
    REPOSITORY_INFO = "repository_info"  # Get repo metadata, commits, PRs

    # AWS capabilities (future)
    AWS_LOGS = "aws_logs"  # CloudWatch logs
    AWS_METRICS = "aws_metrics"  # CloudWatch metrics

    # Datadog capabilities (future)
    DATADOG_LOGS = "datadog_logs"
    DATADOG_METRICS = "datadog_metrics"

    # NewRelic capabilities (future)
    NEWRELIC_LOGS = "newrelic_logs"
    NEWRELIC_METRICS = "newrelic_metrics"


@dataclass
class ExecutionContext:
    """
    Complete execution context for the RCA agent.
    Contains workspace info, capabilities, and integrations.
    """

    workspace_id: str
    capabilities: Set[Capability]
    integrations: Dict[str, Integration]  # type -> Integration
    service_mapping: Dict[str, List[str]]  # service -> [repos]
    thread_history: str | None = None

    def has_capability(self, capability: Capability) -> bool:
        """Check if workspace has a specific capability."""
        return capability in self.capabilities

    def has_integration(self, integration_type: str) -> bool:
        """Check if workspace has a specific integration type."""
        return integration_type in self.integrations

    def get_integration(self, integration_type: str) -> Integration | None:
        """Get integration by type."""
        return self.integrations.get(integration_type)

    def get_healthy_integrations(self) -> Dict[str, Integration]:
        """Get only healthy integrations."""
        return {
            itype: integration
            for itype, integration in self.integrations.items()
            if integration.health_status == "healthy"
        }


class IntegrationCapabilityResolver:
    """
    Resolves workspace integrations to agent capabilities.

    Responsibilities:
    1. Fetch all active integrations for workspace
    2. Map integrations to capabilities
    3. Filter out unhealthy integrations (optional)
    4. Construct ExecutionContext
    """

    # Map integration types to capabilities they provide
    INTEGRATION_CAPABILITY_MAP = {
        "grafana": {
            Capability.LOGS,
            Capability.METRICS,
            Capability.DATASOURCES,
        },
        "github": {
            Capability.CODE_SEARCH,
            Capability.CODE_READ,
            Capability.REPOSITORY_INFO,
        },
        "aws": {
            Capability.AWS_LOGS,
            Capability.AWS_METRICS,
        },
        "datadog": {
            Capability.DATADOG_LOGS,
            Capability.DATADOG_METRICS,
        },
        "newrelic": {
            Capability.NEWRELIC_LOGS,
            Capability.NEWRELIC_METRICS,
        },
    }

    def __init__(self, only_healthy: bool = True):
        """
        Initialize capability resolver.

        Args:
            only_healthy: If True, only include healthy integrations in capabilities
        """
        self.only_healthy = only_healthy

    async def resolve(
        self,
        workspace_id: str,
        db: AsyncSession,
        service_mapping: Dict[str, List[str]] | None = None,
        thread_history: str | None = None,
    ) -> ExecutionContext:
        """
        Resolve workspace integrations to execution context.

        Args:
            workspace_id: Workspace ID
            db: Database session
            service_mapping: Pre-computed service→repos mapping
            thread_history: Slack thread history

        Returns:
            ExecutionContext with capabilities and integrations
        """
        # Fetch all integrations for workspace (single query!)
        integrations = await get_workspace_integrations(workspace_id, db)

        # Filter by health status if requested
        if self.only_healthy:
            healthy_integrations = []
            for integration in integrations:
                if integration.health_status == "healthy":
                    # Fast path: already healthy, use directly
                    healthy_integrations.append(integration)
                elif (
                    integration.health_status is None
                    or integration.health_status == "failed"
                ):
                    # Run health check for NULL (not yet checked) or failed (might have recovered)
                    logger.info(
                        f"Running health check for {integration.provider} integration "
                        f"(current status: {integration.health_status})"
                    )
                    try:
                        updated_integration = await check_integration_health(
                            integration.id, db
                        )
                        if updated_integration.health_status == "healthy":
                            logger.info(
                                f"{integration.provider} integration is now healthy, including in capabilities"
                            )
                            healthy_integrations.append(updated_integration)
                        else:
                            logger.warning(
                                f"{integration.provider} integration health check failed, skipping"
                            )
                    except Exception as e:
                        logger.error(
                            f"Error running health check for {integration.provider}: {e}"
                        )
            integrations = healthy_integrations

        # Map integrations by provider
        integrations_by_type = {
            integration.provider: integration for integration in integrations
        }

        # Resolve capabilities from integrations
        capabilities = self._resolve_capabilities(integrations)

        # Construct execution context
        context = ExecutionContext(
            workspace_id=workspace_id,
            capabilities=capabilities,
            integrations=integrations_by_type,
            service_mapping=service_mapping or {},
            thread_history=thread_history,
        )

        return context

    def _resolve_capabilities(self, integrations: List[Integration]) -> Set[Capability]:
        """
        Map integrations to capabilities.

        Args:
            integrations: List of workspace integrations

        Returns:
            Set of available capabilities
        """
        capabilities = set()

        for integration in integrations:
            provider = integration.provider

            # Get capabilities for this provider
            integration_capabilities = self.INTEGRATION_CAPABILITY_MAP.get(
                provider, set()
            )

            capabilities.update(integration_capabilities)

        return capabilities

    @classmethod
    def get_required_integrations(cls, capability: Capability) -> Set[str]:
        """
        Get integration types required for a capability.

        Args:
            capability: Capability to check

        Returns:
            Set of integration types that provide this capability
        """
        required = set()

        for integration_type, capabilities in cls.INTEGRATION_CAPABILITY_MAP.items():
            if capability in capabilities:
                required.add(integration_type)

        return required
