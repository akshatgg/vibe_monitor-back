"""
Chat API routes including SSE streaming.
"""

import json
import logging
import re
import uuid
from typing import AsyncIterator, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from app.auth.google.service import AuthService
from app.chat.schemas import (
    AddFeedbackCommentRequest,
    ChatSearchResponse,
    ChatSearchResult,
    ChatSessionResponse,
    ChatSessionSummary,
    ChatTurnResponse,
    FeedbackResponse,
    FileDownloadResponse,
    SendMessageResponse,
    SubmitFeedbackRequest,
    UpdateSessionRequest,
)
from app.chat.service import ChatService
from app.core.config import settings
from app.core.database import get_db
from app.core.redis import subscribe_to_channel
from app.models import ChatFile, JobStatus, TurnStatus, User
from app.services.s3.client import s3_client
from app.services.storage import FileValidationError, FileValidator, TextExtractor
from app.utils.rate_limiter import ResourceType, check_rate_limit_with_byollm_bypass

logger = logging.getLogger(__name__)


def validate_relative_path(path: Optional[str]) -> Optional[str]:
    """
    Validate and sanitize relative path to prevent path traversal attacks.

    Args:
        path: The relative path to validate

    Returns:
        Sanitized path or None if invalid

    Raises:
        HTTPException: If path contains traversal patterns
    """
    if path is None:
        return None

    # Reject empty strings
    if not path.strip():
        return None

    # Reject absolute paths (Unix and Windows)
    if path.startswith("/") or path.startswith("\\"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path: absolute paths not allowed",
        )

    # Check for Windows drive letters (e.g., C:, D:)
    if len(path) >= 2 and path[1] == ":":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path: absolute paths not allowed",
        )

    # Reject path traversal patterns
    # Check for ".." in path segments (handles both / and \ separators)
    # Match ".." as a path segment or at start/end
    if re.search(r"(^|[/\\])\.\.([/\\]|$)", path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path: directory traversal not allowed",
        )

    # Reject null bytes (can be used to truncate paths in some systems)
    if "\x00" in path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path: null bytes not allowed",
        )

    # Normalize path separators to forward slashes and strip leading/trailing whitespace
    sanitized = path.strip().replace("\\", "/")

    # Remove any leading slashes that might have been missed
    sanitized = sanitized.lstrip("/")

    return sanitized if sanitized else None


auth_service = AuthService()

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["chat"])


@router.post("/chat", response_model=SendMessageResponse)
async def send_message(
    workspace_id: str,
    message: str = Form(..., min_length=1, max_length=10000),
    session_id: Optional[str] = Form(None),
    files: Optional[List[UploadFile]] = File(None),
    file_paths: Optional[str] = Form(None),  # JSON array of relative paths
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Send a chat message and start RCA processing with optional file attachments.

    Creates a new session if session_id not provided.
    Returns turn_id for SSE streaming.

    Connect to GET /turns/{turn_id}/stream to receive real-time updates.

    **File Upload Support:**
    - Up to 10 files per message
    - Max 50MB per file
    - Supported types: images, videos, documents, code files, data

    **Rate Limiting:**
    - VibeMonitor AI users are subject to workspace daily limits
    - BYOLLM users (OpenAI, Azure, Gemini) have NO rate limits
    """

    if files is None:
        files = []

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

    # Validate file count
    if len(files) > settings.MAX_FILES_PER_MESSAGE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many files. Maximum {settings.MAX_FILES_PER_MESSAGE} files per message.",
        )

    # Validate S3 bucket is configured
    if files and settings.CHAT_UPLOADS_BUCKET is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File uploads are not configured. Please contact support.",
        )

    # Parse and validate relative paths JSON (before processing)
    relative_paths_list = []
    if files and file_paths:
        try:
            parsed = json.loads(file_paths)
            # Validate that it's a list
            if not isinstance(parsed, list):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="file_paths must be a JSON array of strings",
                )
            # Validate length matches files
            if len(parsed) != len(files):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"file_paths length ({len(parsed)}) must match files count ({len(files)})",
                )
            relative_paths_list = parsed
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file_paths JSON: {str(e)}",
            )

    # Validate all files first (without storing content)
    # This is a quick pass to fail early on invalid files
    validated_files_metadata = []
    total_upload_bytes = 0
    if files:
        logger.info(
            f"Validating {len(files)} uploaded files for workspace {workspace_id}"
        )

        for index, file in enumerate(files):
            # Get and validate relative path (prevents path traversal attacks)
            relative_path = None
            if index < len(relative_paths_list):
                raw_path = relative_paths_list[index]
                if isinstance(raw_path, str):
                    relative_path = validate_relative_path(raw_path)

            # Early size check before reading entire file into memory
            if file.size is not None and file.size > settings.MAX_FILE_SIZE_BYTES:
                max_mb = settings.MAX_FILE_SIZE_BYTES / (1024 * 1024)
                actual_mb = file.size / (1024 * 1024)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File '{file.filename}' is too large ({actual_mb:.1f}MB). Maximum allowed size is {max_mb:.0f}MB.",
                )

            # Accumulate total bytes for rate limiting
            if file.size is not None:
                total_upload_bytes += file.size

            validated_files_metadata.append(
                {"file": file, "relative_path": relative_path}
            )

        # Check file upload rate limit (total bytes per day)
        # BYOLLM users bypass this limit
        if total_upload_bytes > 0:
            try:
                (
                    allowed,
                    bytes_used,
                    bytes_limit,
                ) = await check_rate_limit_with_byollm_bypass(
                    session=db,
                    workspace_id=workspace_id,
                    resource_type=ResourceType.FILE_UPLOAD_BYTES,
                    limit=settings.DAILY_UPLOAD_LIMIT_BYTES,
                    increment=total_upload_bytes,
                )

                if not allowed:
                    # Convert to MB for user-friendly error message
                    bytes_used_mb = bytes_used / (1024 * 1024)
                    bytes_limit_mb = bytes_limit / (1024 * 1024)
                    upload_mb = total_upload_bytes / (1024 * 1024)

                    logger.warning(
                        f"File upload rate limit exceeded for workspace {workspace_id}: "
                        f"{bytes_used_mb:.1f}MB/{bytes_limit_mb:.1f}MB used, attempted +{upload_mb:.1f}MB"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail={
                            "message": "Daily file upload limit reached",
                            "used_mb": round(bytes_used_mb, 2),
                            "limit_mb": round(bytes_limit_mb, 2),
                            "attempted_mb": round(upload_mb, 2),
                            "tip": "Configure your own LLM (OpenAI, Azure, or Gemini) to remove limits",
                        },
                    )

                # Log rate limit status
                if bytes_limit == -1:
                    logger.info(
                        f"BYOLLM workspace {workspace_id} - unlimited file uploads"
                    )
                else:
                    logger.info(
                        f"File upload rate limit check passed for workspace {workspace_id}: "
                        f"{bytes_used / (1024 * 1024):.1f}MB/{bytes_limit / (1024 * 1024):.1f}MB used "
                        f"(+{total_upload_bytes / (1024 * 1024):.1f}MB)"
                    )

            except HTTPException:
                raise
            except Exception as e:
                # Fail open: allow the request but log the error
                logger.exception(
                    f"Unexpected error in file upload rate limit check: {e}"
                )
                logger.warning(
                    f"File upload rate limit check failed for workspace {workspace_id}, "
                    f"allowing request to proceed"
                )

    service = ChatService(db)

    try:
        # Get or create session
        session = await service.get_or_create_session(
            workspace_id=workspace_id,
            user_id=current_user.id,
            session_id=session_id,
            first_message=message,
        )

        turn = await service.create_turn(session, message)

        processed_files_for_job = []
        uploaded_s3_keys = []  # Track successfully uploaded S3 keys for cleanup on failure

        # Process files one at a time to minimize memory usage
        # Each file is read, validated, uploaded to S3, then content is freed
        if validated_files_metadata:
            logger.info(
                f"Processing and uploading {len(validated_files_metadata)} files"
            )
            try:
                for file_meta in validated_files_metadata:
                    file = file_meta["file"]
                    relative_path = file_meta["relative_path"]

                    try:
                        # Read file content (processed one at a time)
                        file_content = await file.read()

                        # Validate file content
                        mime_type, file_category = FileValidator.validate_file(
                            filename=file.filename,
                            file_content=file_content,
                            max_size_bytes=settings.MAX_FILE_SIZE_BYTES,
                            allowed_extensions=settings.ALLOWED_FILE_EXTENSIONS,
                        )

                        file_size = len(file_content)
                        logger.info(
                            f"File '{file.filename}' validated: {mime_type} ({file_category}), "
                            f"size: {file_size} bytes"
                        )

                        # Extract text for non-image/video files
                        extracted_text = None
                        if file_category not in ("image", "video"):
                            extracted_text = await TextExtractor.extract_text(
                                file_content=file_content,
                                mime_type=mime_type,
                                filename=file.filename,
                            )

                        # Generate S3 key and file ID
                        file_id = str(uuid.uuid4())
                        s3_key = f"{workspace_id}/{turn.id}/{file.filename}"

                        # Upload to S3 immediately
                        upload_success = await s3_client.upload_file(
                            key=s3_key,
                            file_content=file_content,
                            content_type=mime_type,
                        )

                        # Free memory by releasing file content reference
                        # (actual garbage collection happens when no references remain)
                        del file_content

                        if not upload_success:
                            raise HTTPException(
                                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail=f"Failed to upload '{file.filename}' to storage",
                            )

                        # Track successful upload for potential rollback
                        uploaded_s3_keys.append(s3_key)

                        # Create ChatFile record
                        chat_file = ChatFile(
                            id=file_id,
                            turn_id=turn.id,
                            s3_bucket=settings.CHAT_UPLOADS_BUCKET,
                            s3_key=s3_key,
                            filename=file.filename,
                            file_type=file_category,
                            mime_type=mime_type,
                            size_bytes=file_size,
                            relative_path=relative_path,
                            extracted_text=extracted_text,
                            uploaded_by=current_user.id,
                        )
                        db.add(chat_file)

                        # Build minimal file context for job
                        processed_files_for_job.append(
                            {
                                "file_id": file_id,
                                "s3_key": s3_key,
                                "filename": file.filename,
                                "file_type": file_category,
                                "mime_type": mime_type,
                                "size": file_size,
                                "relative_path": relative_path,
                                "extracted_text": extracted_text,
                            }
                        )

                    except FileValidationError:
                        raise
                    except HTTPException:
                        raise
                    except Exception as e:
                        logger.error(f"Failed to process file '{file.filename}': {e}")
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Failed to process file '{file.filename}': {str(e)}",
                        )

            except Exception:
                # On any exception, cleanup S3 files that were successfully uploaded
                if uploaded_s3_keys:
                    logger.error(
                        f"Exception during file processing, cleaning up {len(uploaded_s3_keys)} S3 files"
                    )
                    await s3_client.delete_files(uploaded_s3_keys)
                raise

        # Create and enqueue job
        job = await service.create_job_for_turn(turn, workspace_id)

        # Add file S3 references to job's requested_context
        if processed_files_for_job:
            job.requested_context["has_files"] = True
            job.requested_context["has_images"] = any(
                f["file_type"] in ["image", "video"] for f in processed_files_for_job
            )
            job.requested_context["files"] = processed_files_for_job

            attributes.flag_modified(job, "requested_context")

            logger.info(
                f"Uploaded {len(processed_files_for_job)} files to S3 for job {job.id} "
                f"(has_images: {job.requested_context['has_images']}, images: {sum(1 for f in processed_files_for_job if f['file_type'] == 'image')}, videos: {sum(1 for f in processed_files_for_job if f['file_type'] == 'video')})"
            )

        # IMPORTANT: Commit BEFORE enqueueing to prevent race condition
        # The SQS worker may process the message before this transaction commits
        await db.commit()

        # Now safe to enqueue - job exists in database
        await service.enqueue_job(job)

        return SendMessageResponse(
            turn_id=turn.id,
            session_id=session.id,
        )

    except HTTPException:
        # Re-raise HTTP exceptions without wrapping
        # S3 cleanup already handled in inner exception handler
        await db.rollback()
        raise
    except Exception as e:
        # Clean up S3 files on any unexpected failure
        # This handles failures during job creation, enqueueing, or commit
        if uploaded_s3_keys:
            logger.error(
                f"Unexpected failure after S3 upload, cleaning up {len(uploaded_s3_keys)} files"
            )
            try:
                await s3_client.delete_files(uploaded_s3_keys)
            except Exception as cleanup_error:
                logger.error(
                    f"Failed to cleanup S3 files after error: {cleanup_error}. "
                    f"Manual cleanup may be required for keys: {uploaded_s3_keys}"
                )
        await db.rollback()
        logger.error(f"Failed to send message: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process message",
        )


@router.get("/files/{file_id}/download", response_model=FileDownloadResponse)
async def get_file_download_url(
    workspace_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Generate presigned download URL for a chat file (expires in 1 hour).

    Verifies:
    - File exists and belongs to the workspace
    - User owns the chat session (files are private to session owner)
    - User has access to the workspace
    """
    from sqlalchemy import select

    from app.models import ChatSession, ChatTurn, Membership

    # Query file with session ownership check
    # Users can only download files from their own chat sessions
    result = await db.execute(
        select(ChatFile)
        .join(ChatTurn, ChatFile.turn_id == ChatTurn.id)
        .join(ChatSession, ChatTurn.session_id == ChatSession.id)
        .where(
            ChatFile.id == file_id,
            ChatSession.workspace_id == workspace_id,
            ChatSession.user_id == current_user.id,  # Verify session ownership
        )
    )
    chat_file = result.scalar_one_or_none()

    if not chat_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found or access denied",
        )

    # Verify workspace membership (defense in depth)
    membership_result = await db.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == current_user.id,
        )
    )
    if not membership_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Generate presigned URL with Content-Disposition for security
    download_url = await s3_client.generate_download_url(
        chat_file.s3_key, filename=chat_file.filename
    )

    if not download_url:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="File expired or unavailable (files retained for 60 days)",
        )

    return {
        "file_id": file_id,
        "filename": chat_file.filename,
        "size_bytes": chat_file.size_bytes,
        "mime_type": chat_file.mime_type,
        "download_url": download_url,
        "expires_in_seconds": settings.CHAT_UPLOADS_URL_EXPIRY_SECONDS,
    }


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
    Each user can have one rating per turn (upsert behavior).
    """
    service = ChatService(db)

    # Verify turn exists and user has access
    turn = await service.get_turn(
        turn_id=turn_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )

    if not turn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Turn not found",
        )

    # Submit feedback to new table
    feedback = await service.submit_turn_feedback(
        turn_id=turn_id,
        user_id=current_user.id,
        is_positive=request.is_positive,
    )

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save feedback",
        )

    # If comment provided, add it as well
    comment_text = None
    if request.comment:
        comment = await service.add_turn_comment(
            turn_id=turn_id,
            user_id=current_user.id,
            comment=request.comment,
        )
        comment_text = comment.comment if comment else None

    await db.commit()

    return FeedbackResponse(
        turn_id=turn_id,
        is_positive=feedback.is_positive,
        comment=comment_text,
    )


@router.post("/turns/{turn_id}/comment", response_model=FeedbackResponse)
async def add_feedback_comment(
    workspace_id: str,
    turn_id: str,
    request: AddFeedbackCommentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auth_service.get_current_user),
):
    """
    Add a comment to a turn (separate from thumbs up/down).

    This allows users to provide detailed feedback comments independently
    from the thumbs up/down rating, matching the Slack interface behavior.
    Multiple comments per user are allowed.
    """
    service = ChatService(db)

    # Verify turn exists and user has access
    turn = await service.get_turn(
        turn_id=turn_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )

    if not turn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Turn not found",
        )

    # Add the comment to new table
    comment = await service.add_turn_comment(
        turn_id=turn_id,
        user_id=current_user.id,
        comment=request.comment,
    )

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save comment",
        )

    await db.commit()

    # Get user's current feedback to include in response
    feedbacks = await service.get_turn_feedbacks(turn_id)
    user_feedback = next((f for f in feedbacks if f.user_id == current_user.id), None)

    return FeedbackResponse(
        turn_id=turn_id,
        is_positive=user_feedback.is_positive if user_feedback else False,
        comment=comment.comment,
        message="Comment added successfully.",
    )
