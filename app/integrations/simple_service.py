"""
Simplified integration service - for when you only need basic info.
Use this instead of the full health check service when you don't need credentials.
"""

import logging
from typing import Any, Dict, List

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Integration

logger = logging.getLogger(__name__)


async def get_workspace_integration_summary(
    workspace_id: str, db: AsyncSession
) -> List[Dict[str, Any]]:
    """
    Get all integrations for a workspace in ONE query.
    Perfect for dashboards, lists, status pages.

    Args:
        workspace_id: Workspace ID
        db: Database session

    Returns:
        List of integration summaries
    """
    logger.debug(f"Fetching integration summary: workspace_id={workspace_id}")

    result = await db.execute(
        select(
            Integration.id,
            Integration.provider,
            Integration.status,
            Integration.health_status,
            Integration.last_verified_at,
            Integration.last_error,
            Integration.created_at,
        )
        .where(Integration.workspace_id == workspace_id)
        .order_by(Integration.created_at.desc())
    )

    integrations = []
    for row in result:
        integrations.append(
            {
                "id": row[0],
                "provider": row[1],
                "type": row[1],  # provider serves as type
                "status": row[2],
                "health_status": row[3],
                "last_verified_at": row[4],
                "last_error": row[5],
                "created_at": row[6],
            }
        )

    # Log with useful aggregates for Grafana queries
    types = list(set(i["type"] for i in integrations))
    status_counts = {}
    for i in integrations:
        status_counts[i["status"]] = status_counts.get(i["status"], 0) + 1

    logger.info(
        f"Fetched integration summary: workspace_id={workspace_id}, "
        f"count={len(integrations)}, types={types}, status_distribution={status_counts}"
    )
    return integrations


async def get_integration_types(workspace_id: str, db: AsyncSession) -> List[str]:
    """
    Get list of integration types for a workspace in ONE query.

    Example:
        types = await get_integration_types(workspace_id, db)
        # Returns: ['github', 'grafana', 'slack']

    Args:
        workspace_id: Workspace ID
        db: Database session

    Returns:
        List of integration types
    """
    logger.debug(f"Fetching integration types: workspace_id={workspace_id}")

    result = await db.execute(
        select(Integration.provider)
        .where(Integration.workspace_id == workspace_id)
        .distinct()
    )

    types = [row[0] for row in result]
    logger.debug(
        f"Found integration types: workspace_id={workspace_id}, "
        f"count={len(types)}, types={types}"
    )
    return types


async def get_integration_stats(workspace_id: str, db: AsyncSession) -> Dict[str, Any]:
    """
    Get integration statistics in ONE query.

    Returns:
        {
            'total': 5,
            'by_type': {'github': 1, 'aws': 2, ...},
            'by_status': {'active': 3, 'error': 2},
            'by_health': {'healthy': 3, 'failed': 2}
        }
    """
    logger.debug(f"Fetching integration stats: workspace_id={workspace_id}")

    # Single query to get all stats (provider serves as type)
    result = await db.execute(
        text(
            """
            SELECT
                COUNT(*) as total,
                json_object_agg(provider, provider_count) as by_type,
                json_object_agg(status, status_count) as by_status,
                json_object_agg(health_status, health_count) as by_health
            FROM (
                SELECT
                    provider,
                    status,
                    health_status,
                    COUNT(*) OVER (PARTITION BY provider) as provider_count,
                    COUNT(*) OVER (PARTITION BY status) as status_count,
                    COUNT(*) OVER (PARTITION BY health_status) as health_count
                FROM integrations
                WHERE workspace_id = :workspace_id
            ) subquery
            LIMIT 1
        """
        ),
        {"workspace_id": workspace_id},
    )

    row = result.first()
    if not row:
        logger.debug(f"No integrations found for stats: workspace_id={workspace_id}")
        return {"total": 0, "by_type": {}, "by_status": {}, "by_health": {}}

    stats = {
        "total": row[0],
        "by_type": row[1] or {},
        "by_status": row[2] or {},
        "by_health": row[3] or {},
    }

    logger.info(
        f"Fetched integration stats: workspace_id={workspace_id}, "
        f"total={stats['total']}, by_type={stats['by_type']}, "
        f"by_status={stats['by_status']}, by_health={stats['by_health']}"
    )
    return stats


async def has_integration_type(
    workspace_id: str, integration_type: str, db: AsyncSession
) -> bool:
    """
    Check if workspace has a specific integration type in ONE query.

    Example:
        has_github = await has_integration_type(workspace_id, 'github', db)
    """
    logger.debug(
        f"Checking integration type exists: workspace_id={workspace_id}, "
        f"type={integration_type}"
    )

    result = await db.execute(
        select(func.count(Integration.id)).where(
            Integration.workspace_id == workspace_id,
            Integration.provider == integration_type,
        )
    )

    count = result.scalar()
    has_type = count > 0

    logger.debug(
        f"Integration type check result: workspace_id={workspace_id}, "
        f"type={integration_type}, exists={has_type}, count={count}"
    )
    return has_type
