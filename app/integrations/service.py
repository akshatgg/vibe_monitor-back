"""
Integration health check service.
Orchestrates health checks for all integrations and updates the database.
"""

import logging
from typing import List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import (
    Integration,
    GitHubIntegration,
    AWSIntegration,
    GrafanaIntegration,
    DatadogIntegration,
    NewRelicIntegration,
    SlackInstallation,
)
from app.integrations.health_checks import (
    check_github_health,
    check_aws_health,
    check_grafana_health,
    check_datadog_health,
    check_newrelic_health,
    check_slack_health,
)

logger = logging.getLogger(__name__)


async def check_integration_health(
    integration_id: str,
    db: AsyncSession
) -> Integration:
    """
    Check health of a single integration and update database.

    Args:
        integration_id: ID of the integration to check
        db: Database session

    Returns:
        Updated Integration model

    Raises:
        ValueError: If integration not found
    """
    logger.debug(
        f"Starting health check for integration_id={integration_id}"
    )

    # Fetch integration with provider config
    result = await db.execute(
        select(Integration).where(Integration.id == integration_id)
    )
    integration = result.scalar_one_or_none()

    if not integration:
        logger.warning(
            f"Integration not found: integration_id={integration_id}"
        )
        raise ValueError(f"Integration {integration_id} not found")

    health_status = 'unknown'
    error_message = None

    logger.debug(
        f"Fetched integration: integration_id={integration_id}, "
        f"provider={integration.provider}, workspace_id={integration.workspace_id}, "
        f"current_status={integration.status}"
    )

    try:
        # Route to appropriate health check based on integration type
        if integration.provider == 'github':
            logger.debug(f"Checking GitHub config for integration_id={integration_id}")
            result = await db.execute(
                select(GitHubIntegration).where(
                    GitHubIntegration.integration_id == integration_id
                )
            )
            config = result.scalar_one_or_none()
            if config:
                logger.debug(f"Found GitHub config, running health check: integration_id={integration_id}")
                health_status, error_message = await check_github_health(config)
            else:
                logger.warning(f"GitHub config not found for integration_id={integration_id}")
                health_status = 'unknown'
                error_message = 'GitHub configuration not found'

        elif integration.provider == 'aws':
            logger.debug(f"Checking AWS config for integration_id={integration_id}")
            result = await db.execute(
                select(AWSIntegration).where(
                    AWSIntegration.integration_id == integration_id
                )
            )
            config = result.scalar_one_or_none()
            if config:
                logger.debug(f"Found AWS config, running health check: integration_id={integration_id}")
                health_status, error_message = await check_aws_health(config)
            else:
                logger.warning(f"AWS config not found for integration_id={integration_id}")
                health_status = 'unknown'
                error_message = 'AWS configuration not found'

        elif integration.provider == 'grafana':
            logger.debug(f"Checking Grafana config for integration_id={integration_id}")
            result = await db.execute(
                select(GrafanaIntegration).where(
                    GrafanaIntegration.integration_id == integration_id
                )
            )
            config = result.scalar_one_or_none()
            if config:
                logger.debug(f"Found Grafana config, running health check: integration_id={integration_id}")
                health_status, error_message = await check_grafana_health(config)
            else:
                logger.warning(f"Grafana config not found for integration_id={integration_id}")
                health_status = 'unknown'
                error_message = 'Grafana configuration not found'

        elif integration.provider == 'datadog':
            logger.debug(f"Checking Datadog config for integration_id={integration_id}")
            result = await db.execute(
                select(DatadogIntegration).where(
                    DatadogIntegration.integration_id == integration_id
                )
            )
            config = result.scalar_one_or_none()
            if config:
                logger.debug(f"Found Datadog config, running health check: integration_id={integration_id}")
                health_status, error_message = await check_datadog_health(config)
            else:
                logger.warning(f"Datadog config not found for integration_id={integration_id}")
                health_status = 'unknown'
                error_message = 'Datadog configuration not found'

        elif integration.provider == 'newrelic':
            logger.debug(f"Checking NewRelic config for integration_id={integration_id}")
            result = await db.execute(
                select(NewRelicIntegration).where(
                    NewRelicIntegration.integration_id == integration_id
                )
            )
            config = result.scalar_one_or_none()
            if config:
                logger.debug(f"Found NewRelic config, running health check: integration_id={integration_id}")
                health_status, error_message = await check_newrelic_health(config)
            else:
                logger.warning(f"NewRelic config not found for integration_id={integration_id}")
                health_status = 'unknown'
                error_message = 'NewRelic configuration not found'

        elif integration.provider == 'slack':
            logger.debug(f"Checking Slack config for integration_id={integration_id}")
            result = await db.execute(
                select(SlackInstallation).where(
                    SlackInstallation.integration_id == integration_id
                )
            )
            config = result.scalar_one_or_none()
            if config:
                logger.debug(f"Found Slack config, running health check: integration_id={integration_id}")
                health_status, error_message = await check_slack_health(config)
            else:
                logger.warning(f"Slack config not found for integration_id={integration_id}")
                health_status = 'unknown'
                error_message = 'Slack configuration not found'

        else:
            logger.warning(
                f"Unknown integration provider: provider={integration.provider}, "
                f"integration_id={integration_id}"
            )
            health_status = 'unknown'
            error_message = f'Unknown integration provider: {integration.provider}'

    except Exception as e:
        logger.exception(
            f"Unexpected error during health check: integration_id={integration_id}, "
            f"provider={integration.provider}, workspace_id={integration.workspace_id}"
        )
        health_status = 'unknown'
        error_message = f'Health check error: {str(e)}'

    # Sync integration status based on health_status
    # - healthy → active (integration is working)
    # - failed/degraded → error (integration has issues)
    # - unknown → keep previous status (health check inconclusive)
    previous_status = integration.status
    if health_status == 'healthy':
        integration.status = 'active'
    elif health_status in ['failed', 'degraded']:
        integration.status = 'error'
    # 'unknown' preserves current status - health check was inconclusive

    # Log status transition if changed
    if previous_status != integration.status:
        logger.info(
            f"Integration status changed: integration_id={integration_id}, "
            f"provider={integration.provider}, workspace_id={integration.workspace_id}, "
            f"previous_status={previous_status}, new_status={integration.status}"
        )

    # Update health fields
    integration.health_status = health_status
    integration.last_verified_at = datetime.now(timezone.utc)
    integration.last_error = error_message
    integration.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(integration)

    logger.info(
        f"Health check completed: integration_id={integration_id}, provider={integration.provider}, "
        f"workspace_id={integration.workspace_id}, health_status={health_status}, "
        f"status={integration.status}, error={error_message}"
    )

    return integration


async def check_all_workspace_integrations_health(
    workspace_id: str,
    db: AsyncSession
) -> List[Integration]:
    """
    Check health of all integrations for a workspace.

    Args:
        workspace_id: ID of the workspace
        db: Database session

    Returns:
        List of updated Integration models
    """
    logger.debug(f"Starting bulk health check for workspace_id={workspace_id}")

    # Fetch all integrations for workspace
    result = await db.execute(
        select(Integration)
        .where(Integration.workspace_id == workspace_id)
        .order_by(Integration.created_at)
    )
    integrations = result.scalars().all()

    if not integrations:
        logger.info(f"No integrations found: workspace_id={workspace_id}")
        return []

    integration_providers = [i.provider for i in integrations]
    logger.info(
        f"Starting bulk health check: workspace_id={workspace_id}, "
        f"total_integrations={len(integrations)}, providers={integration_providers}"
    )

    updated_integrations = []
    failed_count = 0
    for integration in integrations:
        try:
            updated = await check_integration_health(integration.id, db)
            updated_integrations.append(updated)
        except Exception as e:
            failed_count += 1
            logger.error(
                f"Health check failed: integration_id={integration.id}, "
                f"provider={integration.provider}, workspace_id={workspace_id}, error={e}"
            )
            # Continue checking other integrations

    # Log summary with health distribution
    healthy_count = sum(1 for i in updated_integrations if i.health_status == 'healthy')
    degraded_count = sum(1 for i in updated_integrations if i.health_status == 'degraded')
    failed_health_count = sum(1 for i in updated_integrations if i.health_status == 'failed')

    logger.info(
        f"Bulk health check completed: workspace_id={workspace_id}, "
        f"total={len(integrations)}, checked={len(updated_integrations)}, "
        f"healthy={healthy_count}, degraded={degraded_count}, "
        f"failed={failed_health_count}, errors={failed_count}"
    )

    return updated_integrations


async def get_workspace_integrations(
    workspace_id: str,
    db: AsyncSession,
    integration_type: str | None = None,
    status: str | None = None
) -> List[Integration]:
    """
    Get all integrations for a workspace with optional filters.

    Args:
        workspace_id: ID of the workspace
        db: Database session
        integration_type: Optional filter by integration type
        status: Optional filter by status ('active', 'disabled', 'error')

    Returns:
        List of Integration models
    """
    logger.debug(
        f"Fetching integrations: workspace_id={workspace_id}, "
        f"type_filter={integration_type}, status_filter={status}"
    )

    query = select(Integration).where(Integration.workspace_id == workspace_id)

    if integration_type:
        query = query.where(Integration.provider == integration_type)

    if status:
        query = query.where(Integration.status == status)

    query = query.order_by(Integration.created_at.desc())

    result = await db.execute(query)
    integrations = result.scalars().all()

    logger.debug(
        f"Fetched integrations: workspace_id={workspace_id}, "
        f"count={len(integrations)}, type_filter={integration_type}, status_filter={status}"
    )

    return integrations


async def get_integration_by_id(
    integration_id: str,
    db: AsyncSession
) -> Integration | None:
    """
    Get an integration by ID.

    Args:
        integration_id: ID of the integration
        db: Database session

    Returns:
        Integration model or None if not found
    """
    logger.debug(f"Fetching integration by id: integration_id={integration_id}")

    result = await db.execute(
        select(Integration).where(Integration.id == integration_id)
    )
    integration = result.scalar_one_or_none()

    if integration:
        logger.debug(
            f"Found integration: integration_id={integration_id}, "
            f"provider={integration.provider}, workspace_id={integration.workspace_id}, "
            f"status={integration.status}"
        )
    else:
        logger.debug(f"Integration not found: integration_id={integration_id}")

    return integration
