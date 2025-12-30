"""
Chat API routes including SSE streaming.
"""

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google.service import AuthService
from app.chat.schemas import (
    ChatSearchResponse,
    ChatSearchResult,
    ChatSessionResponse,
    ChatSessionSummary,
    ChatTurnResponse,
    FeedbackResponse,
    SendMessageRequest,
    SendMessageResponse,
    SubmitFeedbackRequest,
    UpdateSessionRequest,
)
from app.chat.service import ChatService
from app.core.config import settings
from app.core.database import get_db
from app.core.redis import subscribe_to_channel
from app.models import JobStatus, TurnStatus, User
from app.utils.rate_limiter import ResourceType, check_rate_limit_with_byollm_bypass

logger = logging.getLogger(__name__)
auth_service = AuthService()

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["chat"])


@router.post("/chat", response_model=SendMessageResponse)
async def send_message(
    workspace_id: str,
    request: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Send a chat message and start RCA processing.

    Creates a new session if session_id not provided.
    Returns turn_id for SSE streaming.

    Connect to GET /turns/{turn_id}/stream to receive real-time updates.

    **Rate Limiting:**
    - VibeMonitor AI users are subject to workspace daily limits
    - BYOLLM users (OpenAI, Azure, Gemini) have NO rate limits
    """
    # Check rate limit before processing (BYOLLM users bypass rate limiting)
    try:
        allowed, current_count, limit = await check_rate_limit_with_byollm_bypass(
            session=db,
            workspace_id=workspace_id,
            resource_type=ResourceType.RCA_REQUEST,
        )

        if not allowed:
            logger.warning(
                f"RCA rate limit exceeded for workspace {workspace_id}: "
                f"{current_count}/{limit}"
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Daily RCA request limit reached",
                    "current_count": current_count,
                    "limit": limit,
                    "tip": "Configure your own LLM (OpenAI, Azure, or Gemini) to remove limits",
                },
            )

        # Log BYOLLM status (limit=-1 indicates unlimited)
        if limit == -1:
            logger.info(f"BYOLLM workspace {workspace_id} - unlimited RCA requests")
        else:
            logger.debug(
                f"RCA rate limit check passed for workspace {workspace_id}: "
                f"{current_count}/{limit}"
            )

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Rate limit check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rate limit check failed: {str(e)}",
        )
    except Exception as e:
        # Fail open: allow the request but log the error
        logger.exception(f"Unexpected error in rate limit check: {e}")
        logger.warning(
            f"Rate limit check failed for workspace {workspace_id}, "
            f"allowing request to proceed"
        )

    service = ChatService(db)

    try:
        # Get or create session
        session = await service.get_or_create_session(
            workspace_id=workspace_id,
            user_id=current_user.id,
            session_id=request.session_id,
            first_message=request.message,
        )

        # Create turn
        turn = await service.create_turn(session, request.message)

        # Create and enqueue job
        job = await service.create_job_for_turn(turn, workspace_id)

        # IMPORTANT: Commit BEFORE enqueueing to prevent race condition
        # The SQS worker may process the message before this transaction commits
        await db.commit()

        # Now safe to enqueue - job exists in database
        await service.enqueue_job(job)

        return SendMessageResponse(
            turn_id=turn.id,
            session_id=session.id,
        )

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to send message: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process message",
        )


@router.get("/turns/{turn_id}/stream")
async def stream_turn(
    workspace_id: str,
    turn_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Stream turn processing updates via Server-Sent Events (SSE).

    Events:
    - status: General status updates
    - tool_start: Tool execution started
    - tool_end: Tool execution completed
    - complete: Processing finished with final response
    - error: An error occurred
    """
    service = ChatService(db)

    # Verify turn exists and user has access
    turn = await service.get_turn(
        turn_id=turn_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
        include_steps=True,
    )

    if not turn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Turn not found",
        )

    # If already completed, return final response immediately
    if turn.status == TurnStatus.COMPLETED:

        async def completed_stream() -> AsyncIterator[str]:
            # First send any existing steps
            for step in sorted(turn.steps, key=lambda s: s.sequence):
                event = {
                    "event": "tool_end" if step.tool_name else "status",
                    "tool_name": step.tool_name,
                    "content": step.content,
                    "status": step.status.value,
                }
                yield f"data: {json.dumps(event)}\n\n"

            # Then send completion
            yield f"data: {json.dumps({'event': 'complete', 'final_response': turn.final_response})}\n\n"

        return StreamingResponse(
            completed_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    # If failed, return error
    if turn.status == TurnStatus.FAILED:

        async def error_stream() -> AsyncIterator[str]:
            yield f"data: {json.dumps({'event': 'error', 'message': 'Processing failed'})}\n\n"

        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # Turn is PROCESSING or PENDING - check for staleness before subscribing to Redis
    is_stale, stale_reason, job = await service.check_turn_staleness(turn)

    if is_stale:
        # Mark turn and job as failed
        await service.mark_turn_failed_with_cleanup(
            turn, stale_reason or "Processing failed", job
        )
        await db.commit()
        logger.warning(f"Turn {turn_id} marked as stale: {stale_reason}")

        async def stale_error_stream() -> AsyncIterator[str]:
            yield f"data: {json.dumps({'event': 'error', 'message': stale_reason or 'Processing failed'})}\n\n"

        return StreamingResponse(
            stale_error_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # Check if job completed but turn wasn't updated (data inconsistency recovery)
    if job and job.status == JobStatus.COMPLETED:
        await service.sync_turn_with_completed_job(turn, job)
        await db.commit()
        logger.info(f"Synced turn {turn_id} with completed job {job.id}")

        # Return completed stream with final response from job or turn
        async def synced_completed_stream() -> AsyncIterator[str]:
            for step in sorted(turn.steps, key=lambda s: s.sequence):
                event = {
                    "event": "tool_end" if step.tool_name else "status",
                    "tool_name": step.tool_name,
                    "content": step.content,
                    "status": step.status.value,
                }
                yield f"data: {json.dumps(event)}\n\n"
            yield f"data: {json.dumps({'event': 'complete', 'final_response': turn.final_response or 'Analysis completed.'})}\n\n"

        return StreamingResponse(
            synced_completed_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Genuinely still processing - subscribe to Redis with configurable timeout
    async def event_stream() -> AsyncIterator[str]:
        channel = f"turn:{turn_id}"

        try:
            # First, send any existing steps (in case we connected late)
            for step in sorted(turn.steps, key=lambda s: s.sequence):
                event = {
                    "event": "tool_end" if step.tool_name else "status",
                    "tool_name": step.tool_name,
                    "content": step.content,
                    "status": step.status.value,
                }
                yield f"data: {json.dumps(event)}\n\n"

            # Then subscribe to Redis for new events with configurable timeout
            async for event in subscribe_to_channel(
                channel, timeout_seconds=settings.SSE_REDIS_TIMEOUT_SECONDS
            ):
                yield f"data: {json.dumps(event)}\n\n"

                # Stop on completion or error
                if event.get("event") in ("complete", "error"):
                    break

        except Exception as e:
            logger.error(f"SSE stream error for turn {turn_id}: {e}", exc_info=True)
            yield f"data: {json.dumps({'event': 'error', 'message': 'Stream interrupted'})}\n\n"
            return  # Explicit termination to ensure stream closes
        finally:
            logger.debug(f"SSE stream closed for turn {turn_id}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions", response_model=list[ChatSessionSummary])
async def list_sessions(
    workspace_id: str,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    List chat sessions for the current user in a workspace.
    """
    service = ChatService(db)
    sessions = await service.list_sessions(
        workspace_id=workspace_id,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    # Build summaries
    summaries = []
    for session in sessions:
        # Get turn count and last message
        turn_count = len(session.turns) if session.turns else 0
        last_message = None
        if session.turns:
            # Get most recent turn's user message
            sorted_turns = sorted(
                session.turns, key=lambda t: t.created_at, reverse=True
            )
            if sorted_turns:
                last_message = sorted_turns[0].user_message[:100]
                if len(sorted_turns[0].user_message) > 100:
                    last_message += "..."

        summaries.append(
            ChatSessionSummary(
                id=session.id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
                turn_count=turn_count,
                last_message_preview=last_message,
            )
        )

    return summaries


@router.get("/sessions/search", response_model=ChatSearchResponse)
async def search_sessions(
    workspace_id: str,
    q: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Search chat sessions by title and message content.

    Args:
        q: Search query string (min 2 characters)
        limit: Maximum number of results (default 20)

    Returns:
        List of matching sessions with snippets
    """
    service = ChatService(db)
    results = await service.search_sessions(
        workspace_id=workspace_id,
        user_id=current_user.id,
        query=q,
        limit=limit,
    )

    return ChatSearchResponse(results=[ChatSearchResult(**r) for r in results])


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    workspace_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Get a chat session with all its turns.
    """
    service = ChatService(db)
    session = await service.get_session(
        session_id=session_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
        include_turns=True,
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    return session


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(
    workspace_id: str,
    session_id: str,
    request: UpdateSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Update a session (e.g., rename).
    """
    service = ChatService(db)
    session = await service.update_session_title(
        session_id=session_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
        title=request.title,
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    await db.commit()
    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    workspace_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Delete a chat session and all its turns.
    """
    service = ChatService(db)
    deleted = await service.delete_session(
        session_id=session_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    await db.commit()


@router.get("/turns/{turn_id}", response_model=ChatTurnResponse)
async def get_turn(
    workspace_id: str,
    turn_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Get a specific turn with all its steps.
    """
    service = ChatService(db)
    turn = await service.get_turn(
        turn_id=turn_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
        include_steps=True,
    )

    if not turn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Turn not found",
        )

    return turn


@router.post("/turns/{turn_id}/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    workspace_id: str,
    turn_id: str,
    request: SubmitFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Submit feedback for a turn (thumbs up/down).
    """
    # Convert boolean to score: True (thumbs up) = 1, False (thumbs down) = -1
    score = 1 if request.is_positive else -1

    service = ChatService(db)
    turn = await service.submit_feedback(
        turn_id=turn_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
        score=score,
        comment=request.comment,
    )

    if not turn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Turn not found",
        )

    await db.commit()

    return FeedbackResponse(
        turn_id=turn.id,
        is_positive=turn.feedback_score == 1,
        comment=turn.feedback_comment,
    )
