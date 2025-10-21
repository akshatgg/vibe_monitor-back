"""
Simple universal rate limiter.
Check if request is allowed, increment if yes.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Tuple
from enum import Enum

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.models import Workspace, RateLimitTracking

logger = logging.getLogger(__name__)


class ResourceType(str, Enum):
    """Types of rate-limited resources."""
    RCA_REQUEST = "rca_request"
    API_CALL = "api_call"
    EXPORT = "export"
    SLACK_MESSAGE = "slack_message"


async def check_rate_limit(
    session: AsyncSession,
    workspace_id: str,
    resource_type: ResourceType,
    limit: int = None
) -> Tuple[bool, int, int]:
    """
    Check if request is allowed and increment counter if yes.

    Args:
        session: Database session
        workspace_id: Workspace ID
        resource_type: Type of resource (RCA_REQUEST, API_CALL, etc.)
        limit: Custom limit (if None, uses workspace.daily_request_limit for RCA)

    Returns:
        (allowed: bool, current_count: int, limit: int)
        - allowed: True if request should proceed, False if limit exceeded
        - current_count: Current usage count
        - limit: The rate limit

    Example:
        allowed, count, limit = await check_rate_limit(
            session=db,
            workspace_id="workspace-123",
            resource_type=ResourceType.RCA_REQUEST
        )

        if not allowed:
            return f"Rate limit exceeded: {count}/{limit}"
    """
    try:
        # Get workspace and limit
        stmt = select(Workspace).where(Workspace.id == workspace_id)
        result = await session.execute(stmt)
        workspace = result.scalar_one_or_none()

        if not workspace:
            raise ValueError(f"Workspace {workspace_id} not found")

        # Use custom limit or workspace limit
        if limit is None:
            limit = workspace.daily_request_limit  # Default for RCA

        # Get today's date (UTC)
        today = datetime.now(timezone.utc).date().isoformat()  # e.g., '2025-10-15'

        # Try to get existing tracking record with lock
        tracking_stmt = (
            select(RateLimitTracking)
            .where(
                and_(
                    RateLimitTracking.workspace_id == workspace_id,
                    RateLimitTracking.resource_type == resource_type.value,
                    RateLimitTracking.window_key == today #window key changs everyday so this returns false the next day, no windowkey matched, new tracking record created.
                )
            )
            .with_for_update()  # Lock row to prevent race conditions
        )

        tracking_result = await session.execute(tracking_stmt)
        tracking = tracking_result.scalar_one_or_none()

        # First request of the day - create record
        if not tracking:
            try:
                tracking = RateLimitTracking(
                    id=str(uuid.uuid4()),
                    workspace_id=workspace_id,
                    resource_type=resource_type.value,
                    window_key=today,
                    count=1  # First request
                )
                session.add(tracking)
                await session.commit()

                logger.info(
                    f"Rate limit: First {resource_type.value} request for workspace {workspace_id} today. "
                    f"Count: 1/{limit}"
                )
                return (True, 1, limit)

            except IntegrityError:
                # Race condition - another request created the record
                await session.rollback()
                tracking_result = await session.execute(tracking_stmt)
                tracking = tracking_result.scalar_one()

        # Check if limit exceeded
        if tracking.count >= limit:
            logger.warning(
                f"Rate limit: Workspace {workspace_id} exceeded {resource_type.value} limit. "
                f"Count: {tracking.count}/{limit}"
            )
            return (False, tracking.count, limit)

        # Increment and allow
        tracking.count += 1
        await session.commit()

        logger.info(
            f"Rate limit: {resource_type.value} request allowed for workspace {workspace_id}. "
            f"Count: {tracking.count}/{limit}"
        )

        return (True, tracking.count, limit)

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Rate limit error for workspace {workspace_id}: {e}")
        await session.rollback()
        raise

# api limit usage details, in case we need this in future


# async def get_usage(
#     session: AsyncSession,
#     workspace_id: str,
#     resource_type: ResourceType
# ) -> Tuple[int, int]:
#     """
#     Get current usage without incrementing.

#     Returns:
#         (current_count: int, limit: int)
#     """
#     # Get workspace limit
#     stmt = select(Workspace).where(Workspace.id == workspace_id)
#     result = await session.execute(stmt)
#     workspace = result.scalar_one_or_none()

#     if not workspace:
#         raise ValueError(f"Workspace {workspace_id} not found")

#     limit = workspace.daily_request_limit
#     today = datetime.now(timezone.utc).date().isoformat()

#     # Get today's count
#     tracking_stmt = select(RateLimitTracking).where(
#         and_(
#             RateLimitTracking.workspace_id == workspace_id,
#             RateLimitTracking.resource_type == resource_type.value,
#             RateLimitTracking.window_key == today
#         )
#     )
#     tracking_result = await session.execute(tracking_stmt)
#     tracking = tracking_result.scalar_one_or_none()

#     current_count = tracking.count if tracking else 0
#     return (current_count, limit)


# # Backward compatibility
# async def check_and_increment_rca_limit(
#     session: AsyncSession,
#     workspace_id: str
# ) -> Tuple[bool, int, int]:
#     """
#     Legacy function for RCA rate limiting.
#     Use check_rate_limit() for new code.
#     """
#     return await check_rate_limit(
#         session=session,
#         workspace_id=workspace_id,
#         resource_type=ResourceType.RCA_REQUEST
#     )
