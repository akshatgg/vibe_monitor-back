"""
Simple universal rate limiter.
Check if request is allowed, increment if yes.

BYOLLM Support:
- Workspaces with custom LLM configuration bypass rate limiting
- Only VibeMonitor AI (default Groq) users are rate limited
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Tuple

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LLMProvider, LLMProviderConfig, RateLimitTracking, Workspace

logger = logging.getLogger(__name__)


class ResourceType(str, Enum):
    """Types of rate-limited resources."""

    AIU_USAGE = "aiu_usage"  # Weekly AIU (AI Unit) consumption - tracks token usage
    API_CALL = "api_call"
    EXPORT = "export"
    SLACK_MESSAGE = "slack_message"
    FILE_UPLOAD_BYTES = "file_upload_bytes"  # Total bytes uploaded per day


def get_weekly_window_key() -> str:
    """
    Get the current ISO week window key for weekly rate limiting.

    Returns:
        str: ISO week key in format 'YYYY-WNN' (e.g., '2026-W06' for week 6 of 2026)

    Example:
        >>> get_weekly_window_key()
        '2026-W06'  # Week 6 of 2026 (starts on Monday)
    """
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


async def check_rate_limit(
    session: AsyncSession,
    workspace_id: str,
    resource_type: ResourceType,
    limit: int = None,
    increment: int = 1,
) -> Tuple[bool, int, int]:
    """
    Check if request is allowed and increment counter if yes.

    Args:
        session: Database session
        workspace_id: Workspace ID
        resource_type: Type of resource (RCA_REQUEST, API_CALL, etc.)
        limit: Custom limit (if None, uses workspace.daily_request_limit for RCA)
        increment: Amount to increment by (default 1, use bytes for FILE_UPLOAD_BYTES)

    Returns:
        (allowed: bool, current_count: int, limit: int)
        - allowed: True if request should proceed, False if limit exceeded
        - current_count: Current usage count (after increment if allowed)
        - limit: The rate limit

    Example:
        # For request counting
        allowed, count, limit = await check_rate_limit(
            session=db,
            workspace_id="workspace-123",
            resource_type=ResourceType.RCA_REQUEST
        )

        # For byte counting
        allowed, bytes_used, bytes_limit = await check_rate_limit(
            session=db,
            workspace_id="workspace-123",
            resource_type=ResourceType.FILE_UPLOAD_BYTES,
            limit=100_000_000,  # 100MB
            increment=file_size_bytes
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
                    RateLimitTracking.window_key
                    == today,  # window key changs everyday so this returns false the next day, no windowkey matched, new tracking record created.
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
                    count=increment,  # Use increment value (1 for requests, bytes for uploads)
                )
                session.add(tracking)
                await session.commit()

                logger.info(
                    f"🔢 RATE LIMIT TRACKING - First {resource_type.value} for workspace {workspace_id} today. "
                    f"Count: {increment}/{limit} - RateLimitTracking table INCREMENTED"
                )
                return (True, increment, limit)

            except IntegrityError:
                # Race condition - another request created the record
                await session.rollback()
                tracking_result = await session.execute(tracking_stmt)
                tracking = tracking_result.scalar_one()

        # Check if limit would be exceeded after increment
        if tracking.count + increment > limit:
            logger.warning(
                f"Rate limit: Workspace {workspace_id} would exceed {resource_type.value} limit. "
                f"Current: {tracking.count}/{limit}, requested: +{increment}"
            )

            from app.core.otel_metrics import SECURITY_METRICS

            SECURITY_METRICS["rate_limit_exceeded_total"].add(
                1,
                {
                    "resource_type": resource_type.value,
                },
            )

            return (False, tracking.count, limit)

        # Increment and allow
        tracking.count += increment
        await session.commit()

        logger.info(
            f"🔢 RATE LIMIT TRACKING - {resource_type.value} request allowed for workspace {workspace_id}. "
            f"Count: {tracking.count}/{limit} (+{increment}) - RateLimitTracking table INCREMENTED"
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


async def is_byollm_workspace(workspace_id: str, session: AsyncSession) -> bool:
    """
    Check if workspace has configured their own LLM (not using VibeMonitor AI).

    BYOLLM users are NOT rate limited - they use their own API keys and quotas.

    Args:
        workspace_id: The workspace ID to check
        session: Database session

    Returns:
        bool: True if workspace uses custom LLM (OpenAI, Azure, Gemini),
              False if using VibeMonitor default (Groq)
    """
    try:
        result = await session.execute(
            select(LLMProviderConfig.provider).where(
                LLMProviderConfig.workspace_id == workspace_id
            )
        )
        provider = result.scalar_one_or_none()

        # If no config exists or provider is vibemonitor, not BYOLLM
        if provider is None:
            logger.debug(f"No LLM config found for workspace {workspace_id} - using VibeMonitor (rate limits apply)")
            return False

        is_byollm = provider != LLMProvider.VIBEMONITOR
        logger.info(
            f"Workspace {workspace_id} LLM check: provider={provider.value}, "
            f"is_byollm={is_byollm}, rate_limits={'BYPASSED' if is_byollm else 'APPLY'}"
        )
        return is_byollm

    except Exception as e:
        logger.error(f"Error checking BYOLLM status for workspace {workspace_id}: {e}")
        # Default to not BYOLLM on error (apply rate limits)
        return False


async def check_rate_limit_with_byollm_bypass(
    session: AsyncSession,
    workspace_id: str,
    resource_type: ResourceType,
    limit: int = None,
    increment: int = 1,
) -> Tuple[bool, int, int]:
    """
    Check rate limit with BYOLLM bypass.

    BYOLLM workspaces (OpenAI, Azure OpenAI, Gemini) are NOT rate limited.
    Only VibeMonitor AI (Groq) users are subject to rate limits.

    Args:
        session: Database session
        workspace_id: Workspace ID
        resource_type: Type of resource (RCA_REQUEST, API_CALL, etc.)
        limit: Custom limit (if None, uses workspace.daily_request_limit for RCA)
        increment: Amount to increment by (default 1, use bytes for FILE_UPLOAD_BYTES)

    Returns:
        (allowed: bool, current_count: int, limit: int)
        - For BYOLLM: Always (True, 0, -1) indicating unlimited
        - For VibeMonitor AI: Normal rate limit check

    Example:
        allowed, count, limit = await check_rate_limit_with_byollm_bypass(
            session=db,
            workspace_id="workspace-123",
            resource_type=ResourceType.RCA_REQUEST
        )

        if not allowed:
            return f"Rate limit exceeded: {count}/{limit}"
    """
    # Check feature flag for rate limiting
    RATE_LIMITING_ENABLED = os.getenv("RATE_LIMITING_ENABLED", "true").lower() == "true"

    if not RATE_LIMITING_ENABLED:
        logger.info(
            f"Rate limiting disabled globally via RATE_LIMITING_ENABLED=false "
            f"for workspace {workspace_id} and resource {resource_type.value}"
        )
        return (True, 0, -1)

    # Check if workspace uses BYOLLM (bring your own LLM)
    if await is_byollm_workspace(workspace_id, session):
        logger.info(
            f"⚡ BYOLLM DETECTED - Workspace {workspace_id} using custom LLM - "
            f"BYPASSING rate limit for {resource_type.value} - "
            f"RateLimitTracking table will NOT be incremented"
        )
        # Return unlimited indicator: allowed=True, count=0, limit=-1 (unlimited)
        return (True, 0, -1)

    # Apply normal rate limiting for regular workspaces
    return await check_rate_limit(
        session=session,
        workspace_id=workspace_id,
        resource_type=resource_type,
        limit=limit,
        increment=increment,
    )


async def track_aiu_usage(
    workspace_id: str,
    token_count: int,
    session: AsyncSession,
) -> None:
    """
    Track AIU (AI Unit / token) usage for a workspace.

    This function records actual token consumption in the rate_limit_tracking table
    with weekly aggregation for billing/usage display.

    IMPORTANT: This function should be called AFTER every AI response to track
    token usage. The token_count should be extracted from the LLM response metadata
    (e.g., response.usage.total_tokens from LangGraph/Groq).

    Args:
        workspace_id: The workspace ID
        token_count: Number of tokens consumed (input + output tokens)
        session: Database session

    Example:
        # After AI response completes:
        total_tokens = response.usage.total_tokens  # ← AI team extracts this
        await track_aiu_usage(
            workspace_id=workspace_id,
            token_count=total_tokens,
            session=db
        )

    Storage:
        - Table: rate_limit_tracking
        - resource_type: 'aiu_usage'
        - window_key: '2026-W06' (weekly, resets every Monday)
        - count: Cumulative tokens used this week
    """
    try:
        # Check if workspace uses BYOLLM - if so, don't track AIU
        if await is_byollm_workspace(workspace_id, session):
            logger.debug(
                f"BYOLLM workspace {workspace_id} - skipping AIU tracking (unlimited)"
            )
            return

        # Get weekly window key (e.g., '2026-W06')
        week_key = get_weekly_window_key()

        # Try to get existing tracking record with lock
        tracking_stmt = (
            select(RateLimitTracking)
            .where(
                and_(
                    RateLimitTracking.workspace_id == workspace_id,
                    RateLimitTracking.resource_type == ResourceType.AIU_USAGE.value,
                    RateLimitTracking.window_key == week_key,
                )
            )
            .with_for_update()  # Lock row to prevent race conditions
        )

        tracking_result = await session.execute(tracking_stmt)
        tracking = tracking_result.scalar_one_or_none()

        # First AIU usage this week - create record
        if not tracking:
            try:
                tracking = RateLimitTracking(
                    id=str(uuid.uuid4()),
                    workspace_id=workspace_id,
                    resource_type=ResourceType.AIU_USAGE.value,
                    window_key=week_key,
                    count=token_count,
                )
                session.add(tracking)
                await session.commit()

                logger.info(
                    f"📊 AIU TRACKING - First usage this week for workspace {workspace_id}. "
                    f"Tokens: {token_count:,} - Week: {week_key}"
                )
                return

            except IntegrityError:
                # Race condition - another request created the record
                await session.rollback()
                tracking_result = await session.execute(tracking_stmt)
                tracking = tracking_result.scalar_one()

        # Increment existing record
        old_count = tracking.count
        tracking.count += token_count
        await session.commit()

        logger.info(
            f"📊 AIU TRACKING - Workspace {workspace_id} used {token_count:,} tokens. "
            f"Total this week: {tracking.count:,} (was {old_count:,}) - Week: {week_key}"
        )

    except Exception as e:
        logger.error(
            f"Failed to track AIU usage for workspace {workspace_id}: {e}",
            exc_info=True
        )
        await session.rollback()
        # Don't raise - tracking failure shouldn't break the main flow


