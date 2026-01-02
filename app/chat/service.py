"""
Chat service for managing sessions, turns, and message processing.
"""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import (
    ChatSession,
    ChatTurn,
    FeedbackSource,
    Job,
    JobSource,
    JobStatus,
    StepStatus,
    StepType,
    TurnComment,
    TurnFeedback,
    TurnStatus,
    TurnStep,
)
from app.services.sqs.client import sqs_client

logger = logging.getLogger(__name__)


class ChatService:
    """Service for chat operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_session(
        self,
        workspace_id: str,
        user_id: str,
        session_id: Optional[str] = None,
        first_message: Optional[str] = None,
    ) -> ChatSession:
        """
        Get existing session or create a new one.

        Args:
            workspace_id: Workspace ID
            user_id: User ID
            session_id: Optional existing session ID
            first_message: First message (used for auto-generating title)

        Returns:
            ChatSession instance
        """
        if session_id:
            # Try to get existing session
            result = await self.db.execute(
                select(ChatSession).where(
                    ChatSession.id == session_id,
                    ChatSession.workspace_id == workspace_id,
                    ChatSession.user_id == user_id,
                )
            )
            session = result.scalar_one_or_none()
            if session:
                return session
            # Session not found, create new one

        # Create new session
        session = ChatSession(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            user_id=user_id,
            title=self._generate_title(first_message) if first_message else None,
        )
        self.db.add(session)
        await self.db.flush()
        logger.info(f"Created new chat session: {session.id}")
        return session

    def _generate_title(self, message: str, max_length: int = 50) -> str:
        """
        Generate session title from first message.

        Sanitizes input to prevent XSS by removing dangerous characters.
        Frontend should still sanitize before rendering (defense in depth).
        """
        # Remove special characters that could cause XSS issues
        title = re.sub(r'[<>"\'&]', "", message.strip())
        # Truncate if needed
        if len(title) > max_length:
            title = title[: max_length - 3] + "..."
        return title or "Untitled Chat"  # Handle empty string after sanitization

    async def create_turn(
        self,
        session: ChatSession,
        user_message: str,
    ) -> ChatTurn:
        """
        Create a new turn in a session.

        Args:
            session: Chat session
            user_message: User's message

        Returns:
            ChatTurn instance
        """
        turn = ChatTurn(
            id=str(uuid.uuid4()),
            session_id=session.id,
            user_message=user_message,
            status=TurnStatus.PENDING,
        )
        self.db.add(turn)
        await self.db.flush()

        # Update session title if this is the first turn and no title
        if not session.title:
            session.title = self._generate_title(user_message)

        logger.info(f"Created chat turn: {turn.id} in session: {session.id}")
        return turn

    async def create_job_for_turn(
        self,
        turn: ChatTurn,
        workspace_id: str,
    ) -> Job:
        """
        Create a Job for processing this turn.

        Args:
            turn: Chat turn
            workspace_id: Workspace ID

        Returns:
            Job instance
        """
        job = Job(
            id=str(uuid.uuid4()),
            vm_workspace_id=workspace_id,
            source=JobSource.WEB,
            status=JobStatus.QUEUED,
            requested_context={"query": turn.user_message, "turn_id": turn.id},
        )
        self.db.add(job)
        await self.db.flush()

        # Link job to turn
        turn.job_id = job.id
        turn.status = TurnStatus.PROCESSING

        logger.info(f"Created job: {job.id} for turn: {turn.id}")
        return job

    async def enqueue_job(self, job: Job) -> bool:
        """
        Enqueue job to SQS for processing.

        Args:
            job: Job to enqueue

        Returns:
            True if successful
        """
        try:
            message_body = {
                "job_id": job.id,
                "source": job.source.value,
            }
            await sqs_client.send_message(message_body)
            logger.info(f"Enqueued job: {job.id} to SQS")
            return True
        except Exception as e:
            logger.error(f"Failed to enqueue job {job.id}: {e}")
            raise

    async def get_session(
        self,
        session_id: str,
        workspace_id: str,
        user_id: str,
        include_turns: bool = True,
    ) -> Optional[ChatSession]:
        """
        Get a session by ID.

        Args:
            session_id: Session ID
            workspace_id: Workspace ID
            user_id: User ID
            include_turns: Whether to include turns

        Returns:
            ChatSession or None
        """
        query = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.workspace_id == workspace_id,
            ChatSession.user_id == user_id,
        )

        if include_turns:
            query = query.options(selectinload(ChatSession.turns))

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_sessions(
        self,
        workspace_id: str,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ChatSession]:
        """
        List sessions for a user in a workspace.

        Args:
            workspace_id: Workspace ID
            user_id: User ID
            limit: Max sessions to return
            offset: Pagination offset

        Returns:
            List of ChatSession
        """
        result = await self.db.execute(
            select(ChatSession)
            .where(
                ChatSession.workspace_id == workspace_id,
                ChatSession.user_id == user_id,
            )
            .options(
                selectinload(ChatSession.turns)
            )  # Eagerly load turns to avoid MissingGreenlet error
            .order_by(desc(ChatSession.updated_at), desc(ChatSession.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def update_session_title(
        self,
        session_id: str,
        workspace_id: str,
        user_id: str,
        title: str,
    ) -> Optional[ChatSession]:
        """
        Update session title.

        Args:
            session_id: Session ID
            workspace_id: Workspace ID
            user_id: User ID
            title: New title

        Returns:
            Updated ChatSession or None
        """
        session = await self.get_session(
            session_id, workspace_id, user_id, include_turns=False
        )
        if not session:
            return None

        session.title = title
        session.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return session

    async def delete_session(
        self,
        session_id: str,
        workspace_id: str,
        user_id: str,
    ) -> bool:
        """
        Delete a session and all its turns.

        Args:
            session_id: Session ID
            workspace_id: Workspace ID
            user_id: User ID

        Returns:
            True if deleted, False if not found
        """
        session = await self.get_session(
            session_id, workspace_id, user_id, include_turns=False
        )
        if not session:
            return False

        await self.db.delete(session)
        await self.db.flush()
        logger.info(f"Deleted session: {session_id}")
        return True

    async def get_turn(
        self,
        turn_id: str,
        workspace_id: str,
        user_id: str,
        include_steps: bool = True,
    ) -> Optional[ChatTurn]:
        """
        Get a turn by ID with authorization check.

        Args:
            turn_id: Turn ID
            workspace_id: Workspace ID for auth
            user_id: User ID for auth
            include_steps: Whether to include steps

        Returns:
            ChatTurn or None
        """
        query = (
            select(ChatTurn)
            .join(ChatSession)
            .where(
                ChatTurn.id == turn_id,
                ChatSession.workspace_id == workspace_id,
                ChatSession.user_id == user_id,
            )
        )

        if include_steps:
            query = query.options(selectinload(ChatTurn.steps))

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def search_sessions(
        self,
        workspace_id: str,
        user_id: str,
        query: str,
        limit: int = 20,
    ) -> List[dict]:
        """
        Search sessions by title and message content.

        Args:
            workspace_id: Workspace ID
            user_id: User ID
            query: Search query string
            limit: Max results to return

        Returns:
            List of search results with matched content
        """
        if not query or len(query.strip()) < 2:
            return []

        search_pattern = f"%{query}%"

        # Search in session titles and turn messages
        # Using raw SQL for the complex UNION query
        from sqlalchemy import text

        sql = text(
            """
            WITH title_matches AS (
                SELECT
                    s.id as session_id,
                    s.title,
                    s.title as matched_content,
                    'title' as match_type,
                    s.created_at,
                    s.updated_at
                FROM chat_sessions s
                WHERE s.workspace_id = :workspace_id
                    AND s.user_id = :user_id
                    AND s.title ILIKE :pattern
            ),
            message_matches AS (
                SELECT DISTINCT ON (s.id)
                    s.id as session_id,
                    s.title,
                    COALESCE(
                        CASE WHEN t.user_message ILIKE :pattern THEN t.user_message ELSE NULL END,
                        t.final_response
                    ) as matched_content,
                    'message' as match_type,
                    s.created_at,
                    s.updated_at
                FROM chat_sessions s
                JOIN chat_turns t ON t.session_id = s.id
                WHERE s.workspace_id = :workspace_id
                    AND s.user_id = :user_id
                    AND (t.user_message ILIKE :pattern OR t.final_response ILIKE :pattern)
                    AND s.id NOT IN (SELECT session_id FROM title_matches)
                ORDER BY s.id, t.created_at DESC
            )
            SELECT * FROM title_matches
            UNION ALL
            SELECT * FROM message_matches
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
            LIMIT :limit
        """
        )

        result = await self.db.execute(
            sql,
            {
                "workspace_id": workspace_id,
                "user_id": user_id,
                "pattern": search_pattern,
                "limit": limit,
            },
        )

        rows = result.fetchall()
        results = []
        seen_sessions = set()

        for row in rows:
            session_id = row.session_id
            if session_id in seen_sessions:
                continue
            seen_sessions.add(session_id)

            # Truncate matched content to ~100 chars with context
            matched_content = row.matched_content or ""
            if len(matched_content) > 150:
                # Try to center around the match
                query_lower = query.lower()
                content_lower = matched_content.lower()
                idx = content_lower.find(query_lower)
                if idx >= 0:
                    start = max(0, idx - 50)
                    end = min(len(matched_content), idx + len(query) + 50)
                    matched_content = (
                        ("..." if start > 0 else "")
                        + matched_content[start:end]
                        + ("..." if end < len(matched_content) else "")
                    )
                else:
                    matched_content = matched_content[:147] + "..."

            results.append(
                {
                    "session_id": session_id,
                    "title": row.title,
                    "matched_content": matched_content,
                    "match_type": row.match_type,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
            )

        return results

    async def update_turn_status(
        self,
        turn_id: str,
        status: TurnStatus,
        final_response: Optional[str] = None,
    ) -> Optional[ChatTurn]:
        """
        Update turn status (called by worker).

        Args:
            turn_id: Turn ID
            status: New status
            final_response: Final response (for completed status)

        Returns:
            Updated ChatTurn or None
        """
        result = await self.db.execute(select(ChatTurn).where(ChatTurn.id == turn_id))
        turn = result.scalar_one_or_none()
        if not turn:
            return None

        turn.status = status
        if final_response:
            turn.final_response = final_response
        turn.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return turn

    async def add_turn_step(
        self,
        turn_id: str,
        step_type: StepType,
        tool_name: Optional[str] = None,
        content: Optional[str] = None,
        status: StepStatus = StepStatus.PENDING,
    ) -> TurnStep:
        """
        Add a processing step to a turn (called by worker).

        Args:
            turn_id: Turn ID
            step_type: Type of step
            tool_name: Tool name (for tool_call type)
            content: Step content
            status: Step status

        Returns:
            Created TurnStep
        """
        # Get current max sequence
        result = await self.db.execute(
            select(func.max(TurnStep.sequence)).where(TurnStep.turn_id == turn_id)
        )
        max_seq = result.scalar() or 0

        step = TurnStep(
            id=str(uuid.uuid4()),
            turn_id=turn_id,
            step_type=step_type,
            tool_name=tool_name,
            content=content,
            status=status,
            sequence=max_seq + 1,
        )
        self.db.add(step)
        await self.db.flush()
        return step

    async def update_step_status(
        self,
        step_id: str,
        status: StepStatus,
        content: Optional[str] = None,
    ) -> Optional[TurnStep]:
        """
        Update step status (called by worker).

        Args:
            step_id: Step ID
            status: New status
            content: Updated content

        Returns:
            Updated TurnStep or None
        """
        result = await self.db.execute(select(TurnStep).where(TurnStep.id == step_id))
        step = result.scalar_one_or_none()
        if not step:
            return None

        step.status = status
        if content is not None:
            step.content = content
        await self.db.flush()
        return step

    async def get_job_for_turn(self, turn: ChatTurn) -> Optional[Job]:
        """
        Get the job associated with a turn.

        Args:
            turn: ChatTurn instance

        Returns:
            Job or None if not found
        """
        if not turn.job_id:
            return None

        result = await self.db.execute(select(Job).where(Job.id == turn.job_id))
        return result.scalar_one_or_none()

    async def check_turn_staleness(
        self, turn: ChatTurn
    ) -> Tuple[bool, Optional[str], Optional[Job]]:
        """
        Check if a turn is stale (processing for too long or orphaned).

        Args:
            turn: ChatTurn instance to check

        Returns:
            Tuple of (is_stale, reason, job)
            - is_stale: True if turn should be marked as failed
            - reason: Human-readable reason for staleness
            - job: Associated job (if found)
        """
        # Get associated job
        job = await self.get_job_for_turn(turn)

        # Case 1: No job exists (orphaned turn)
        if not job:
            return True, "Associated job not found", None

        # Case 2: Job already completed but turn not updated
        if job.status == JobStatus.COMPLETED:
            return False, None, job  # Not stale, just needs sync

        # Case 3: Job already failed but turn not updated
        if job.status == JobStatus.FAILED:
            return True, job.error_message or "Job failed", job

        # Case 4: Job has been processing too long
        max_processing_time = timedelta(minutes=settings.MAX_JOB_PROCESSING_MINUTES)
        started_at = job.started_at or turn.created_at

        if (
            started_at
            and (datetime.now(timezone.utc) - started_at) > max_processing_time
        ):
            return (
                True,
                f"Processing timed out after {settings.MAX_JOB_PROCESSING_MINUTES} minutes",
                job,
            )

        # Not stale - genuinely still processing
        return False, None, job

    async def mark_turn_failed_with_cleanup(
        self,
        turn: ChatTurn,
        error_message: str,
        job: Optional[Job] = None,
    ) -> None:
        """
        Mark a turn as failed and optionally update associated job.

        Args:
            turn: ChatTurn to mark as failed
            error_message: Error message to record
            job: Optional associated job to also mark as failed
        """
        turn.status = TurnStatus.FAILED
        turn.updated_at = datetime.now(timezone.utc)

        if job and job.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
            job.status = JobStatus.FAILED
            job.finished_at = datetime.now(timezone.utc)
            job.error_message = error_message

        await self.db.flush()
        logger.info(f"Marked turn {turn.id} as failed: {error_message}")

    async def sync_turn_with_completed_job(self, turn: ChatTurn, job: Job) -> None:
        """
        Sync turn status with a completed job (data inconsistency recovery).

        Args:
            turn: ChatTurn to update
            job: Completed job to sync from
        """
        if job.status == JobStatus.COMPLETED:
            turn.status = TurnStatus.COMPLETED
            # Note: final_response should have been set by worker
            # If missing, we can't recover it here
        elif job.status == JobStatus.FAILED:
            turn.status = TurnStatus.FAILED

        turn.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        logger.info(f"Synced turn {turn.id} with job {job.id} status: {job.status}")

    # -------------------------------------------------------------------------
    # Slack-specific methods
    # -------------------------------------------------------------------------

    async def get_or_create_slack_session(
        self,
        workspace_id: str,
        slack_team_id: str,
        slack_channel_id: str,
        slack_thread_ts: str,
        slack_user_id: str,
        first_message: Optional[str] = None,
    ) -> ChatSession:
        """
        Get existing Slack session or create a new one.

        A Slack session is uniquely identified by team_id + channel_id + thread_ts.

        Args:
            workspace_id: VM Workspace ID
            slack_team_id: Slack team/workspace ID
            slack_channel_id: Slack channel ID
            slack_thread_ts: Slack thread timestamp (identifies the thread)
            slack_user_id: Slack user ID who sent the message
            first_message: First message (used for auto-generating title)

        Returns:
            ChatSession instance
        """
        # Try to find existing session for this Slack thread
        result = await self.db.execute(
            select(ChatSession).where(
                ChatSession.workspace_id == workspace_id,
                ChatSession.source == JobSource.SLACK,
                ChatSession.slack_team_id == slack_team_id,
                ChatSession.slack_channel_id == slack_channel_id,
                ChatSession.slack_thread_ts == slack_thread_ts,
            )
        )
        session = result.scalar_one_or_none()
        if session:
            return session

        # Create new session for this Slack thread
        session = ChatSession(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            source=JobSource.SLACK,
            slack_team_id=slack_team_id,
            slack_channel_id=slack_channel_id,
            slack_thread_ts=slack_thread_ts,
            slack_user_id=slack_user_id,
            title=self._generate_title(first_message) if first_message else None,
        )
        self.db.add(session)
        await self.db.flush()
        logger.info(
            f"Created new Slack chat session: {session.id} for thread {slack_thread_ts}"
        )
        return session

    async def create_job_for_slack_turn(
        self,
        turn: ChatTurn,
        workspace_id: str,
        slack_integration_id: str,
        slack_channel_id: str,
        slack_thread_ts: str,
        slack_team_id: str,
    ) -> Job:
        """
        Create a Job for processing a Slack turn.

        Args:
            turn: Chat turn
            workspace_id: VM Workspace ID
            slack_integration_id: Slack installation ID
            slack_channel_id: Slack channel ID
            slack_thread_ts: Slack thread timestamp
            slack_team_id: Slack team ID

        Returns:
            Job instance
        """
        job = Job(
            id=str(uuid.uuid4()),
            vm_workspace_id=workspace_id,
            source=JobSource.SLACK,
            slack_integration_id=slack_integration_id,
            trigger_channel_id=slack_channel_id,
            trigger_thread_ts=slack_thread_ts,
            status=JobStatus.QUEUED,
            requested_context={
                "query": turn.user_message,
                "turn_id": turn.id,
                "team_id": slack_team_id,
            },
        )
        self.db.add(job)
        await self.db.flush()

        # Link job to turn
        turn.job_id = job.id
        turn.status = TurnStatus.PROCESSING

        logger.info(f"Created Slack job: {job.id} for turn: {turn.id}")
        return job

    async def get_turn_by_id(self, turn_id: str) -> Optional[ChatTurn]:
        """
        Get a turn by its ID (no auth check - for internal/Slack use).

        Args:
            turn_id: Turn ID

        Returns:
            ChatTurn or None
        """
        result = await self.db.execute(select(ChatTurn).where(ChatTurn.id == turn_id))
        return result.scalar_one_or_none()

    # ═══════════════════════════════════════════════════════════════
    # NEW MULTI-USER FEEDBACK METHODS (using turn_feedbacks table)
    # ═══════════════════════════════════════════════════════════════

    async def submit_turn_feedback(
        self,
        turn_id: str,
        user_id: str,
        is_positive: bool,
    ) -> Optional[TurnFeedback]:
        """
        Submit feedback from a web user (upsert - one feedback per user per turn).

        Args:
            turn_id: Turn ID
            user_id: User ID (from auth)
            is_positive: True for thumbs up, False for thumbs down

        Returns:
            TurnFeedback record or None if turn not found
        """
        # Verify turn exists
        turn = await self.get_turn_by_id(turn_id)
        if not turn:
            logger.warning(f"No turn found for turn_id: {turn_id}")
            return None

        # Check for existing feedback from this user
        result = await self.db.execute(
            select(TurnFeedback).where(
                TurnFeedback.turn_id == turn_id,
                TurnFeedback.user_id == user_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing feedback
            existing.is_positive = is_positive
            existing.updated_at = datetime.now(timezone.utc)
            await self.db.flush()
            logger.info(f"Feedback updated for turn {turn_id} by user {user_id}")
            return existing
        else:
            # Create new feedback
            feedback = TurnFeedback(
                id=str(uuid.uuid4()),
                turn_id=turn_id,
                user_id=user_id,
                is_positive=is_positive,
                source=FeedbackSource.WEB,
            )
            self.db.add(feedback)
            await self.db.flush()
            logger.info(f"Feedback created for turn {turn_id} by user {user_id}")
            return feedback

    async def submit_turn_feedback_slack(
        self,
        turn_id: str,
        slack_user_id: str,
        is_positive: bool,
    ) -> Optional[TurnFeedback]:
        """
        Submit feedback from a Slack user (upsert - one feedback per Slack user per turn).

        Args:
            turn_id: Turn ID
            slack_user_id: Slack user ID
            is_positive: True for thumbs up, False for thumbs down

        Returns:
            TurnFeedback record or None if turn not found
        """
        # Verify turn exists
        turn = await self.get_turn_by_id(turn_id)
        if not turn:
            logger.warning(f"No turn found for turn_id: {turn_id}")
            return None

        # Check for existing feedback from this Slack user
        result = await self.db.execute(
            select(TurnFeedback).where(
                TurnFeedback.turn_id == turn_id,
                TurnFeedback.slack_user_id == slack_user_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing feedback
            existing.is_positive = is_positive
            existing.updated_at = datetime.now(timezone.utc)
            await self.db.flush()
            logger.info(
                f"Feedback updated for turn {turn_id} by Slack user {slack_user_id}"
            )
            return existing
        else:
            # Create new feedback
            feedback = TurnFeedback(
                id=str(uuid.uuid4()),
                turn_id=turn_id,
                slack_user_id=slack_user_id,
                is_positive=is_positive,
                source=FeedbackSource.SLACK,
            )
            self.db.add(feedback)
            await self.db.flush()
            logger.info(
                f"Feedback created for turn {turn_id} by Slack user {slack_user_id}"
            )
            return feedback

    async def add_turn_comment(
        self,
        turn_id: str,
        user_id: str,
        comment: str,
    ) -> Optional[TurnComment]:
        """
        Add a comment from a web user.

        Args:
            turn_id: Turn ID
            user_id: User ID (from auth)
            comment: Comment text

        Returns:
            TurnComment record or None if turn not found
        """
        # Verify turn exists
        turn = await self.get_turn_by_id(turn_id)
        if not turn:
            logger.warning(f"No turn found for turn_id: {turn_id}")
            return None

        # Create new comment (multiple comments allowed)
        turn_comment = TurnComment(
            id=str(uuid.uuid4()),
            turn_id=turn_id,
            user_id=user_id,
            comment=comment,
            source=FeedbackSource.WEB,
        )
        self.db.add(turn_comment)
        await self.db.flush()
        logger.info(f"Comment added for turn {turn_id} by user {user_id}")
        return turn_comment

    async def add_turn_comment_slack(
        self,
        turn_id: str,
        slack_user_id: str,
        comment: str,
    ) -> Optional[TurnComment]:
        """
        Add a comment from a Slack user.

        Args:
            turn_id: Turn ID
            slack_user_id: Slack user ID
            comment: Comment text

        Returns:
            TurnComment record or None if turn not found
        """
        # Verify turn exists
        turn = await self.get_turn_by_id(turn_id)
        if not turn:
            logger.warning(f"No turn found for turn_id: {turn_id}")
            return None

        # Create new comment (multiple comments allowed)
        turn_comment = TurnComment(
            id=str(uuid.uuid4()),
            turn_id=turn_id,
            slack_user_id=slack_user_id,
            comment=comment,
            source=FeedbackSource.SLACK,
        )
        self.db.add(turn_comment)
        await self.db.flush()
        logger.info(f"Comment added for turn {turn_id} by Slack user {slack_user_id}")
        return turn_comment

    async def get_turn_feedbacks(self, turn_id: str) -> List[TurnFeedback]:
        """
        Get all feedbacks for a turn.

        Args:
            turn_id: Turn ID

        Returns:
            List of TurnFeedback records
        """
        result = await self.db.execute(
            select(TurnFeedback)
            .where(TurnFeedback.turn_id == turn_id)
            .order_by(TurnFeedback.created_at)
        )
        return list(result.scalars().all())

    async def get_turn_comments(self, turn_id: str) -> List[TurnComment]:
        """
        Get all comments for a turn.

        Args:
            turn_id: Turn ID

        Returns:
            List of TurnComment records
        """
        result = await self.db.execute(
            select(TurnComment)
            .where(TurnComment.turn_id == turn_id)
            .order_by(TurnComment.created_at)
        )
        return list(result.scalars().all())
