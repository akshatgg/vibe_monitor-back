import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from app.workers.base_worker import BaseWorker
from app.services.sqs.client import sqs_client
from app.services.rca.agent import rca_agent_service
from app.services.rca.callbacks import SlackProgressCallback
from app.slack.service import slack_event_service
from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models import Job, JobStatus
from app.github.tools.router import list_repositories_graphql
from app.services.rca.get_service_name.service import extract_service_names_from_repo

logger = logging.getLogger(__name__)


async def scan_repositories_in_batches(
    repositories: list,
    workspace_id: str,
    batch_size: int = None
) -> dict:
    """
    Scan repositories in parallel batches to extract service names efficiently.
    Each concurrent task gets its own database session to avoid session conflicts.

    Args:
        repositories: List of repository dictionaries to scan
        workspace_id: Workspace identifier
        batch_size: Number of repositories to scan concurrently (defaults to RCA_REPO_SCAN_CONCURRENCY)

    Returns:
        Dictionary mapping service names to repository names
    """
    if batch_size is None:
        batch_size = settings.RCA_REPO_SCAN_CONCURRENCY

    service_repo_mapping = {}
    repos_to_scan = repositories[:settings.RCA_MAX_REPOS_TO_SCAN]
    total_repos = len(repos_to_scan)

    async def scan_single_repo(repo: dict, index: int) -> tuple:
        """
        Scan a single repository and return results.
        Creates its own database session to avoid concurrent session conflicts.
        """
        repo_name = repo.get("name")
        if not repo_name:
            return None, None, None

        # Create a new database session for this task
        async with AsyncSessionLocal() as task_db:
            try:
                services = await extract_service_names_from_repo(
                    workspace_id=workspace_id,
                    repo=repo_name,
                    user_id="rca-agent",
                    db=task_db
                )

                if services:
                    logger.info(f"  [{index + 1}/{total_repos}] {repo_name} → {services}")
                    return repo_name, services, None
                else:
                    return repo_name, [], None

            except Exception as e:
                logger.warning(f"Failed to extract service names from {repo_name}: {e}")
                return repo_name, None, str(e)

    # Process repositories in batches
    for batch_start in range(0, len(repos_to_scan), batch_size):
        batch_end = min(batch_start + batch_size, len(repos_to_scan))
        batch = repos_to_scan[batch_start:batch_end]

        logger.info(f"Scanning batch {batch_start // batch_size + 1} ({len(batch)} repos): {[r.get('name') for r in batch]}")

        # Create tasks for all repos in this batch
        tasks = [
            scan_single_repo(repo, batch_start + i)
            for i, repo in enumerate(batch)
        ]

        # Execute batch in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Exception during repo scan: {result}")
                continue

            repo_name, services, error = result

            if repo_name and services:
                for service_name in services:
                    service_repo_mapping[service_name] = repo_name

    return service_repo_mapping


class RCAOrchestratorWorker(BaseWorker):
    def __init__(self):
        """
        Initialize the RCAOrchestratorWorker and set its worker name to "rca_orchestrator".
        """
        super().__init__("rca_orchestrator")
        logger.info("RCA Orchestrator Worker initialized with AI agent")

    async def process_message(self, message_body: dict):
        """
        Process a single RCA orchestration message from SQS.

        Expected message_body format:
        {
            "job_id": "uuid-string"
        }

        Parameters:
            message_body (dict): Parsed message payload from SQS containing job_id
        """
        job_id = message_body.get("job_id")

        if not job_id:
            logger.error("No job_id in SQS message, skipping")
            return

        async with AsyncSessionLocal() as db:
            try:
                # Fetch job from database
                job = await db.get(Job, job_id)

                if not job:
                    logger.error(f"Job {job_id} not found in database")
                    return

                # Check if job is in correct state
                if job.status != JobStatus.QUEUED:
                    logger.warning(
                        f"Job {job_id} is not queued (status: {job.status.value}), skipping"
                    )
                    return

                # Check if job should be delayed (backoff)
                if job.backoff_until and job.backoff_until > datetime.now(timezone.utc):
                    # Calculate delay in seconds
                    delay = (
                        job.backoff_until - datetime.now(timezone.utc)
                    ).total_seconds()

                    # SQS has a maximum delay of 900 seconds (15 minutes)
                    # If delay is longer, use max and let it check again
                    delay_seconds = min(int(delay), 900)

                    logger.info(
                        f"Job {job_id} is in backoff until {job.backoff_until}, re-queueing with {delay_seconds}s delay"
                    )

                    # Re-enqueue to SQS with delay
                    await sqs_client.send_message(
                        message_body={"job_id": job_id}, delay_seconds=delay_seconds
                    )
                    return

                logger.info(
                    f"🔍 Processing job {job_id}: {job.requested_context.get('query')}"
                )

                # Update job status to RUNNING
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now(timezone.utc)
                await db.commit()

                # Extract context from job
                query = job.requested_context.get("query", "")
                team_id = job.requested_context.get("team_id")
                workspace_id = job.vm_workspace_id
                channel_id = job.trigger_channel_id
                thread_ts = job.trigger_thread_ts

                # Send initial "thinking" message to Slack
                if team_id and channel_id:
                    await slack_event_service.send_message(
                        team_id=team_id,
                        channel=channel_id,
                        text=f"🤔 Analyzing: *{query}*\n\n_Discovering services..._",
                        thread_ts=thread_ts,
                    )

                # PRE-PROCESSING: Discover service→repo mappings BEFORE invoking AI agent
                logger.info(f"🔍 Pre-processing: Discovering service names for workspace {workspace_id}")

                service_repo_mapping = {}
                try:
                    # Fetch all repositories
                    repos_response = await list_repositories_graphql(
                        workspace_id=workspace_id,
                        first=settings.RCA_MAX_REPOS_TO_FETCH,
                        after=None,
                        user_id="rca-agent",
                        db=db
                    )

                    if repos_response.get("success"):
                        repositories = repos_response.get("repositories", [])
                        total_repos = len(repositories)
                        logger.info(f"Found {total_repos} repositories to scan")

                        if team_id and channel_id:
                            await slack_event_service.send_message(
                                team_id=team_id,
                                channel=channel_id,
                                text=f"📦 Found {total_repos} repositories. Extracting service names...",
                                thread_ts=thread_ts,
                            )

                        # Extract service names from repositories in parallel batches
                        service_repo_mapping = await scan_repositories_in_batches(
                            repositories=repositories,
                            workspace_id=workspace_id
                        )

                        logger.info(f"✅ Service discovery complete: {len(service_repo_mapping)} services mapped")

                        if team_id and channel_id:
                            services_list = ", ".join([f"`{s}`" for s in list(service_repo_mapping.keys())[:10]])
                            more_text = f" and {len(service_repo_mapping) - 10} more" if len(service_repo_mapping) > 10 else ""
                            await slack_event_service.send_message(
                                team_id=team_id,
                                channel=channel_id,
                                text=f"✅ Discovered services: {services_list}{more_text}\n\nAnalyzing logs and metrics...",
                                thread_ts=thread_ts,
                            )
                    else:
                        logger.warning("Failed to fetch repositories for service discovery")

                except Exception as e:
                    logger.error(f"Error during service discovery pre-processing: {e}")
                    # Mark job as failed 
                    job.status = JobStatus.FAILED
                    job.finished_at = datetime.now(timezone.utc)
                    job.error_message = f"Service discovery failed: {str(e)}"
                    await db.commit()
                    
                    logger.warning("Service discovery failed, marking job as FAILED and exiting")
                    return

                # Perform RCA analysis using AI agent
                logger.info(
                    f"🤖 Invoking RCA agent for job {job_id} (workspace: {workspace_id})"
                )

                # Add workspace_id and service mapping to context for RCA tools
                analysis_context = {
                    **(job.requested_context or {}),
                    "workspace_id": workspace_id,
                    "service_repo_mapping": service_repo_mapping,  # Pre-computed mapping
                }

                # Create Slack progress callback for real-time updates
                slack_callback = None
                if team_id and channel_id:
                    slack_callback = SlackProgressCallback(
                        team_id=team_id,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        send_tool_output=False,  # Don't send verbose tool outputs
                    )

                result = await rca_agent_service.analyze_with_retry(
                    user_query=query,
                    context=analysis_context,
                    max_retries=2,
                    callbacks=[slack_callback] if slack_callback else None,
                )

                # Process result
                if result["success"]:
                    logger.info(f"✅ Job {job_id} completed successfully")

                    # Update job status
                    job.status = JobStatus.COMPLETED
                    job.finished_at = datetime.now(timezone.utc)
                    await db.commit()

                    # Send analysis result back to Slack
                    if team_id and channel_id:
                        await slack_event_service.send_message(
                            team_id=team_id,
                            channel=channel_id,
                            text=result["output"],
                            thread_ts=thread_ts,
                        )

                    logger.info(f"📤 Job {job_id} result sent to Slack")

                else:
                    # Analysis failed - implement retry logic
                    error_msg = result.get("error", "Unknown error occurred")
                    logger.error(f"❌ Job {job_id} failed: {error_msg}")

                    job.retries += 1

                    if job.retries < job.max_retries:
                        # Retry with exponential backoff (2^retries * base_backoff)
                        backoff_seconds = (
                            2**job.retries * settings.JOB_RETRY_BASE_BACKOFF_SECONDS
                        )  # 1min, 2min, 4min, etc.
                        job.status = JobStatus.QUEUED
                        job.backoff_until = datetime.now(timezone.utc) + timedelta(
                            seconds=backoff_seconds
                        )
                        job.error_message = (
                            f"Attempt {job.retries}/{job.max_retries}: {error_msg}"
                        )
                        await db.commit()

                        # SQS has max delay of 900s (15 min), use that as cap
                        delay_seconds = min(backoff_seconds, 900)

                        logger.info(
                            f"🔄 Job {job_id} will retry in {backoff_seconds}s (attempt {job.retries}/{job.max_retries})"
                        )

                        # Re-enqueue to SQS for retry with delay
                        await sqs_client.send_message(
                            message_body={"job_id": job_id}, delay_seconds=delay_seconds
                        )

                        # Notify user about retry
                        if slack_callback:
                            await slack_callback.send_retry_notification(
                                retry_count=job.retries,
                                max_retries=job.max_retries,
                                backoff_minutes=backoff_seconds // 60
                            )

                    else:
                        # Max retries exceeded
                        job.status = JobStatus.FAILED
                        job.finished_at = datetime.now(timezone.utc)
                        job.error_message = error_msg
                        await db.commit()

                        logger.error(
                            f"❌ Job {job_id} failed after {job.retries} retries: {error_msg}"
                        )

                        # Send final error message to user (sanitized)
                        if slack_callback:
                            await slack_callback.send_final_error(
                                error_msg=error_msg,
                                retry_count=job.retries
                            )

            except Exception as e:
                logger.exception(f"❌ Unexpected error processing job {job_id}: {e}")

                # Try to mark job as failed
                try:
                    job = await db.get(Job, job_id)
                    if job:
                        job.status = JobStatus.FAILED
                        job.finished_at = datetime.now(timezone.utc)
                        job.error_message = f"Worker exception: {str(e)}"
                        await db.commit()

                        # Attempt to send error notification to Slack (sanitized)
                        if job.requested_context:
                            team_id = job.requested_context.get("team_id")
                            if team_id and job.trigger_channel_id:
                                # Create temporary callback for error notification
                                error_callback = SlackProgressCallback(
                                    team_id=team_id,
                                    channel_id=job.trigger_channel_id,
                                    thread_ts=job.trigger_thread_ts
                                )
                                await error_callback.send_unexpected_error()
                except Exception as recovery_error:
                    logger.error(f"Failed to handle job failure: {recovery_error}")


async def main():
    """
    Run the RCA orchestrator worker until a termination signal is received and perform graceful shutdown.

    Starts the RCAOrchestratorWorker, installs handlers for SIGINT and SIGTERM to trigger shutdown, waits for the shutdown event, and on exit stops the worker and closes the SQS client to ensure resources are cleaned up.
    """
    logger.info("Starting worker process...")

    worker = RCAOrchestratorWorker()

    try:
        await worker.start()
        loop = asyncio.get_running_loop()
        shutdown = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, shutdown.set)
            except NotImplementedError:
                pass  # Windows
        await shutdown.wait()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await worker.stop()
        await sqs_client.close()
        logger.info("Worker process stopped")


if __name__ == "__main__":
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    # Reduce SQLAlchemy logging verbosity
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    asyncio.run(main())
