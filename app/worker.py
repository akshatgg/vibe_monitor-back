import asyncio
import logging
import signal
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from app.chat.notifiers import WebProgressCallback
from app.chat.service import ChatService
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging_config import clear_job_id, set_job_id
from app.core.otel_metrics import JOB_METRICS, AGENT_METRICS
from app.engagement.service import engagement_service
from app.github.tools.router import list_repositories_graphql
from app.integrations.service import get_workspace_integrations
from app.models import Job, JobSource, JobStatus, TurnStatus
from app.services.rca.agent import rca_agent_service
from app.services.rca.callbacks import (
    SlackProgressCallback,
    ToolMetricsCallback,
    markdown_to_slack,
)
from app.services.rca.gemini_agent import gemini_rca_agent_service
from app.services.rca.get_service_name.service import extract_service_names_from_repo
from app.services.sqs.client import sqs_client
from app.slack.service import slack_event_service
from app.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)


async def scan_repositories_in_batches(
    repositories: list, workspace_id: str, batch_size: int = None
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
    repos_to_scan = repositories[: settings.RCA_MAX_REPOS_TO_SCAN]
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
                    db=task_db,
                )

                if services:
                    logger.info(
                        f"  [{index + 1}/{total_repos}] {repo_name} → {services}"
                    )
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

        logger.info(
            f"Scanning batch {batch_start // batch_size + 1} ({len(batch)} repos): {[r.get('name') for r in batch]}"
        )

        # Create tasks for all repos in this batch
        tasks = [
            scan_single_repo(repo, batch_start + i) for i, repo in enumerate(batch)
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


async def fetch_environment_context(workspace_id: str, db: AsyncSessionLocal) -> dict:
    """
    Fetch environment context for RCA agent including:
    - List of all environments
    - Default environment
    - Deployed commits for each environment

    This function queries the database directly (bypassing service layer membership checks)
    since it runs in the internal RCA agent context where the job has already been authenticated.

    Args:
        workspace_id: Workspace identifier
        db: Database session

    Returns:
        Dictionary with environment context for the RCA agent
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models import (
        Deployment,
        DeploymentStatus,
        Environment,
    )

    environment_context = {
        "environments": [],
        "default_environment": None,
        "deployed_commits_by_environment": {},
    }

    try:
        # Fetch all environments for the workspace (direct query, no membership check)
        result = await db.execute(
            select(Environment)
            .options(selectinload(Environment.repository_configs))
            .where(Environment.workspace_id == workspace_id)
            .order_by(Environment.created_at)
        )
        environments = list(result.scalars().all())

        if not environments:
            logger.info(f"No environments configured for workspace {workspace_id}")
            return environment_context

        # Build environment list and find default
        for env in environments:
            env_info = {"name": env.name, "is_default": env.is_default}
            environment_context["environments"].append(env_info)

            if env.is_default:
                environment_context["default_environment"] = env.name

        logger.info(
            f"Found {len(environments)} environments for workspace {workspace_id}, "
            f"default: {environment_context['default_environment']}"
        )

        # Fetch deployed commits for each environment
        for env in environments:
            env_commits = {}

            # Get repository configs (already loaded via selectinload)
            repo_configs = env.repository_configs or []

            if not repo_configs:
                logger.debug(f"No repositories configured for environment {env.name}")
                environment_context["deployed_commits_by_environment"][env.name] = {}
                continue

            # For each repository, get the latest successful deployment
            for repo_config in repo_configs:
                if not repo_config.is_enabled:
                    continue

                try:
                    # Get latest successful deployment for this repo in this environment
                    result = await db.execute(
                        select(Deployment)
                        .where(
                            Deployment.environment_id == env.id,
                            Deployment.repo_full_name == repo_config.repo_full_name,
                            Deployment.status == DeploymentStatus.SUCCESS,
                        )
                        .order_by(Deployment.deployed_at.desc())
                        .limit(1)
                    )
                    latest_deployment = result.scalar_one_or_none()

                    if latest_deployment and latest_deployment.commit_sha:
                        deployed_at = (
                            latest_deployment.deployed_at.isoformat()
                            if latest_deployment.deployed_at
                            else "unknown"
                        )
                        env_commits[repo_config.repo_full_name] = {
                            "commit_sha": latest_deployment.commit_sha,
                            "deployed_at": deployed_at,
                        }
                except Exception as e:
                    logger.warning(
                        f"Failed to fetch latest deployment for {repo_config.repo_full_name} "
                        f"in environment {env.name}: {e}"
                    )

            environment_context["deployed_commits_by_environment"][env.name] = (
                env_commits
            )
            logger.info(f"Environment {env.name}: {len(env_commits)} deployed commits")

        total_commits = sum(
            len(commits)
            for commits in environment_context[
                "deployed_commits_by_environment"
            ].values()
        )
        logger.info(
            f"✅ Environment context complete: {len(environments)} environments, "
            f"{total_commits} total deployed commits"
        )

    except Exception as e:
        logger.error(f"Error fetching environment context: {e}", exc_info=True)

    return environment_context


class RCAOrchestratorWorker(BaseWorker):
    def __init__(self):
        """
        Initialize the RCAOrchestratorWorker and set its worker name to "rca_orchestrator".
        """
        super().__init__("rca_orchestrator")
        self.scheduler_task = None
        self._last_report_date = None  # Track last report date to avoid duplicates
        logger.info("RCA Orchestrator Worker initialized with AI agent")

    async def start(self):
        """Start both the SQS worker and the engagement scheduler."""
        await super().start()
        self.scheduler_task = asyncio.create_task(self._run_engagement_scheduler())
        logger.info("Engagement scheduler started (6 AM IST daily)")

    async def stop(self):
        """Stop both the SQS worker and the engagement scheduler."""
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
            logger.info("Engagement scheduler stopped")
        await super().stop()

    async def _run_engagement_scheduler(self):
        """
        Background task that sends daily engagement report.

        Checks every minute if it's time to send the report.
        Time is configured via ENGAGEMENT_REPORT_HOUR_UTC and ENGAGEMENT_REPORT_MINUTE_UTC.
        """
        target_hour_utc = settings.ENGAGEMENT_REPORT_HOUR_UTC
        target_minute_utc = settings.ENGAGEMENT_REPORT_MINUTE_UTC

        while self.running:
            try:
                now = datetime.now(timezone.utc)
                today = now.date()

                # Check if it's 6 AM IST (00:30 UTC) and we haven't sent today
                if (
                    now.hour == target_hour_utc
                    and now.minute == target_minute_utc
                    and self._last_report_date != today
                ):
                    logger.info("Triggering daily engagement report...")
                    await self._send_engagement_report()
                    self._last_report_date = today

                # Sleep for 60 seconds before next check
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in engagement scheduler: {e}")
                await asyncio.sleep(60)

    async def _send_engagement_report(self):
        """Send the daily engagement report to Slack."""
        try:
            async with AsyncSessionLocal() as db:
                (
                    report,
                    slack_sent,
                    error_msg,
                ) = await engagement_service.send_daily_report(db)

                if slack_sent:
                    logger.info(
                        f"Daily engagement report sent. "
                        f"Signups: {report.signups.last_1_day} (1d), "
                        f"Active workspaces: {report.active_workspaces.last_1_day} (1d)"
                    )
                else:
                    logger.error(f"Failed to send engagement report: {error_msg}")

        except Exception as e:
            logger.exception(f"Error sending engagement report: {e}")

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

            # Record schema validation error
            from app.core.otel_metrics import SQS_METRICS

            if SQS_METRICS:
                SQS_METRICS["sqs_message_parse_errors_total"].add(1)

            return

        # Set job_id in context variables
        # Now ALL logs anywhere in this job will automatically have this job_id
        set_job_id(job_id)

        try:
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
                    if job.backoff_until and job.backoff_until > datetime.now(
                        timezone.utc
                    ):
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

                    # Safely extract context from job (handle None case)
                    requested_context = job.requested_context or {}
                    query = requested_context.get("query", "")

                    logger.info(f"🔍 Processing job {job_id}: {query}")

                    # Update job status to RUNNING
                    job.status = JobStatus.RUNNING
                    job.started_at = datetime.now(timezone.utc)
                    await db.commit()

                    # Initialize start time for agent duration tracking
                    agent_start_time = time.time()

                    # Extract context from job
                    team_id = requested_context.get("team_id")
                    workspace_id = job.vm_workspace_id
                    channel_id = job.trigger_channel_id
                    thread_ts = job.trigger_thread_ts
                    thread_history = requested_context.get("thread_history")

                    # Log thread history detection
                    if thread_history:
                        logger.info(
                            f"📜 Thread history detected: {len(thread_history)} messages in conversation"
                        )
                    else:
                        logger.info("📝 No thread history - this is a new conversation")

                    # PRE-CHECK: Verify GitHub integration exists and is healthy (required)
                    all_integrations = await get_workspace_integrations(
                        workspace_id, db
                    )
                    github_integration = next(
                        (i for i in all_integrations if i.provider == "github"), None
                    )

                    if not github_integration:
                        logger.warning(
                            f"GitHub integration not found for workspace {workspace_id}"
                        )
                        job.status = JobStatus.FAILED
                        job.finished_at = datetime.now(timezone.utc)
                        job.error_message = "GitHub integration not configured"
                        await db.commit()

                        JOB_METRICS["jobs_failed_total"].add(
                            1,
                            {
                                "job_source": job.source.value,
                                "error_type": "MissingGitHubIntegration",
                            },
                        )

                        # Notify client based on source
                        if job.source == JobSource.WEB:
                            turn_id = requested_context.get("turn_id")
                            if turn_id:
                                web_callback = WebProgressCallback(
                                    turn_id=turn_id,
                                    db=db,
                                )
                                await web_callback.send_error(
                                    "GitHub integration not configured. Please connect GitHub first."
                                )
                        elif team_id and channel_id:
                            slack_callback = SlackProgressCallback(
                                team_id=team_id,
                                channel_id=channel_id,
                                thread_ts=thread_ts,
                                send_tool_output=False,
                            )
                            await slack_callback.send_missing_integration_message(
                                "github"
                            )
                        return

                    # Log warning if health_status is not healthy, but proceed anyway
                    # The actual API call will determine real health status
                    if github_integration.health_status not in ("healthy", None):
                        logger.info(
                            f"GitHub integration has health_status={github_integration.health_status}, "
                            f"will verify with actual API call for workspace {workspace_id}"
                        )

                    # PRE-PROCESSING: Discover service→repo mappings
                    logger.info(
                        f"🔍 Pre-processing: Discovering service names for workspace {workspace_id}"
                    )

                    service_repo_mapping = {}
                    try:
                        # Fetch all repositories
                        repos_response = await list_repositories_graphql(
                            workspace_id=workspace_id,
                            first=settings.RCA_MAX_REPOS_TO_FETCH,
                            after=None,
                            user_id="rca-agent",
                            db=db,
                        )

                        if repos_response.get("success"):
                            # GitHub API succeeded - mark integration as healthy
                            if github_integration.health_status != "healthy":
                                github_integration.health_status = "healthy"
                                github_integration.status = "active"
                                github_integration.last_error = None
                                github_integration.last_verified_at = datetime.now(
                                    timezone.utc
                                )
                                await db.commit()
                                logger.info(
                                    f"✅ GitHub integration marked healthy after successful API call: "
                                    f"workspace_id={workspace_id}"
                                )

                            repositories = repos_response.get("repositories", [])
                            total_repos = len(repositories)
                            logger.info(f"Found {total_repos} repositories to scan")

                            # Extract service names from repositories in parallel batches
                            service_repo_mapping = await scan_repositories_in_batches(
                                repositories=repositories, workspace_id=workspace_id
                            )

                            logger.info(
                                f"✅ Service discovery complete: {len(service_repo_mapping)} services mapped"
                            )
                        else:
                            # GitHub API call failed - mark integration as unhealthy
                            github_integration.health_status = "failed"
                            github_integration.status = "error"
                            github_integration.last_error = (
                                "Failed to fetch repositories"
                            )
                            github_integration.last_verified_at = datetime.now(
                                timezone.utc
                            )
                            await db.commit()
                            logger.warning(
                                f"Failed to fetch repositories for service discovery, "
                                f"marked GitHub integration as unhealthy: workspace_id={workspace_id}"
                            )

                    except Exception as e:
                        # GitHub API call threw exception - mark integration as unhealthy
                        github_integration.health_status = "failed"
                        github_integration.status = "error"
                        github_integration.last_error = str(e)
                        github_integration.last_verified_at = datetime.now(timezone.utc)

                        logger.error(
                            f"Error during service discovery pre-processing: {e}"
                        )
                        # Mark job as failed
                        job.status = JobStatus.FAILED
                        job.finished_at = datetime.now(timezone.utc)
                        job.error_message = f"Service discovery failed: {str(e)}"
                        await db.commit()

                        JOB_METRICS["jobs_failed_total"].add(
                            1,
                            {
                                "job_source": job.source.value,
                                "error_type": "ServiceDiscoveryError",
                            },
                        )

                        # Notify client based on source
                        if job.source == JobSource.WEB:
                            turn_id = requested_context.get("turn_id")
                            if turn_id:
                                web_callback = WebProgressCallback(
                                    turn_id=turn_id,
                                    db=db,
                                )
                                await web_callback.send_error(
                                    f"Service discovery failed: {str(e)}"
                                )

                        logger.warning(
                            "Service discovery failed, marking job as FAILED and exiting"
                        )
                        return

                    # Check for unhealthy optional integrations (exclude slack and github)
                    # GitHub is already checked before service discovery
                    # Other integrations are optional - warn but proceed with RCA
                    unhealthy_optional = [
                        i.provider
                        for i in all_integrations
                        if i.provider not in ("slack", "github")
                        and i.health_status not in ("healthy", None)
                    ]

                    if unhealthy_optional:
                        logger.warning(
                            f"Some integrations unhealthy for workspace {workspace_id}: {unhealthy_optional}. "
                            "Proceeding with available tools."
                        )
                        if team_id and channel_id:
                            slack_callback = SlackProgressCallback(
                                team_id=team_id,
                                channel_id=channel_id,
                                thread_ts=thread_ts,
                                send_tool_output=False,
                            )
                            await slack_callback.send_degraded_integrations_warning(
                                unhealthy_providers=unhealthy_optional
                            )

                    # PRE-PROCESSING: Fetch environment context (environments + deployed commits)
                    logger.info(
                        f"🌍 Pre-processing: Fetching environment context for workspace {workspace_id}"
                    )
                    environment_context = await fetch_environment_context(
                        workspace_id=workspace_id, db=db
                    )

                    # Perform RCA analysis using AI agent
                    # Determine which LLM to use based on whether images/videos are present
                    has_images = job.requested_context.get("has_images", False)
                    files = job.requested_context.get("files", [])

                    if has_images:
                        # Count images and videos
                        image_count = sum(
                            1 for f in files if f.get("file_type") == "image"
                        )
                        video_count = sum(
                            1 for f in files if f.get("file_type") == "video"
                        )
                        media_desc = []
                        if image_count > 0:
                            media_desc.append(f"{image_count} image(s)")
                        if video_count > 0:
                            media_desc.append(f"{video_count} video(s)")

                        logger.info(
                            f"🎬 Invoking Gemini RCA agent for job {job_id} (workspace: {workspace_id}) - {' and '.join(media_desc)} detected"
                        )
                        selected_agent = gemini_rca_agent_service
                    else:
                        logger.info(
                            f"🤖 Invoking Groq RCA agent for job {job_id} (workspace: {workspace_id})"
                        )
                        selected_agent = rca_agent_service

                    # Add workspace_id, service mapping, and environment context for RCA tools
                    analysis_context = {
                        **(job.requested_context or {}),
                        "workspace_id": workspace_id,
                        "service_repo_mapping": service_repo_mapping,  # Pre-computed mapping
                        "environment_context": environment_context,  # Environments + deployed commits
                    }

                    # Create appropriate progress callback based on job source
                    progress_callback = None
                    web_callback = None  # Keep reference for web-specific methods

                    if job.source == JobSource.WEB:
                        # Web chat: use WebProgressCallback for SSE streaming
                        turn_id = requested_context.get("turn_id")
                        if turn_id:
                            web_callback = WebProgressCallback(
                                turn_id=turn_id,
                                db=db,
                            )
                            progress_callback = web_callback
                            logger.info(f"🌐 Using web callback for turn {turn_id}")
                        else:
                            logger.warning(
                                f"Web job {job_id} missing turn_id in context"
                            )
                    else:
                        # Slack: use SlackProgressCallback
                        if team_id and channel_id:
                            progress_callback = SlackProgressCallback(
                                team_id=team_id,
                                channel_id=channel_id,
                                thread_ts=thread_ts,
                                send_tool_output=False,
                            )

                    # Create metrics callback for tool execution tracking
                    metrics_callback = ToolMetricsCallback()

                    # Combine callbacks (metrics + progress)
                    callbacks = [metrics_callback]
                    if progress_callback:
                        callbacks.append(progress_callback)

                    result = await selected_agent.analyze_with_retry(
                        user_query=query,
                        context=analysis_context,
                        callbacks=callbacks,
                        db=db,  # Pass db session for capability-based tool resolution
                    )

                    # Process result with null safety
                    if result and result.get("success"):
                        logger.info(f"✅ Job {job_id} completed successfully")

                        # Update job status
                        job.status = JobStatus.COMPLETED
                        job.finished_at = datetime.now(timezone.utc)
                        await db.commit()

                        agent_duration = time.time() - agent_start_time
                        if AGENT_METRICS:
                            AGENT_METRICS["rca_agent_invocations_total"].add(
                                1,
                                {
                                    "status": "success",
                                },
                            )
                            AGENT_METRICS["rca_agent_duration_seconds"].record(
                                agent_duration
                            )

                        JOB_METRICS["jobs_succeeded_total"].add(
                            1,
                            {
                                "job_source": job.source.value,
                            },
                        )

                        # Send final response based on source
                        final_output = result.get("output", "Analysis completed.")

                        if job.source == JobSource.WEB and web_callback:
                            # Web: send via SSE/Redis
                            await web_callback.send_complete(final_output)
                            logger.info(f"📤 Job {job_id} result sent to web client")
                        elif team_id and channel_id:
                            # Slack: update turn status and send message with feedback buttons
                            # Convert Markdown to Slack format
                            slack_output = markdown_to_slack(final_output)

                            turn_id = requested_context.get("turn_id")
                            if turn_id:
                                # Update turn status and response
                                chat_service = ChatService(db)
                                await chat_service.update_turn_status(
                                    turn_id=turn_id,
                                    status=TurnStatus.COMPLETED,
                                    final_response=final_output,
                                )
                                await db.commit()

                                # Send with feedback buttons
                                await slack_event_service.send_message_with_feedback_button(
                                    team_id=team_id,
                                    channel=channel_id,
                                    text=slack_output,
                                    turn_id=turn_id,
                                    thread_ts=thread_ts,
                                )
                                logger.info(
                                    f"📤 Job {job_id} result sent to Slack with feedback buttons"
                                )
                            else:
                                # Fallback: send without feedback button
                                await slack_event_service.send_message(
                                    team_id=team_id,
                                    channel=channel_id,
                                    text=slack_output,
                                    thread_ts=thread_ts,
                                )
                                logger.info(f"📤 Job {job_id} result sent to Slack")

                    else:
                        # Analysis failed - mark as failed
                        error_msg = (result or {}).get(
                            "error", "Unknown error occurred"
                        )
                        error_type = (result or {}).get("error_type")
                        logger.error(f"❌ Job {job_id} failed: {error_msg}")

                        # Mark job as failed
                        job.status = JobStatus.FAILED
                        job.finished_at = datetime.now(timezone.utc)
                        job.error_message = error_msg
                        await db.commit()

                        agent_duration = time.time() - agent_start_time
                        if AGENT_METRICS:
                            AGENT_METRICS["rca_agent_invocations_total"].add(
                                1,
                                {
                                    "status": "failure",
                                },
                            )
                            AGENT_METRICS["rca_agent_duration_seconds"].record(
                                agent_duration
                            )

                        JOB_METRICS["jobs_failed_total"].add(
                            1,
                            {
                                "job_source": job.source.value,
                                "error_type": "UnknownError",
                            },
                        )

                        # Send error based on source
                        if job.source == JobSource.WEB and web_callback:
                            await web_callback.send_error(error_msg)
                        elif progress_callback and hasattr(
                            progress_callback, "send_no_healthy_integrations_message"
                        ):
                            # Slack callback with special methods
                            if error_type == "no_healthy_integrations":
                                await progress_callback.send_no_healthy_integrations_message()
                            else:
                                await progress_callback.send_final_error(
                                    error_msg=error_msg, retry_count=0
                                )

                except Exception as e:
                    logger.exception(
                        f"❌ Unexpected error processing job {job_id}: {e}"
                    )

                    # Try to mark job as failed
                    try:
                        job = await db.get(Job, job_id)
                        if job:
                            job.status = JobStatus.FAILED
                            job.finished_at = datetime.now(timezone.utc)
                            job.error_message = f"Worker exception: {str(e)}"
                            await db.commit()

                            JOB_METRICS["jobs_failed_total"].add(
                                1,
                                {
                                    "job_source": job.source.value,
                                    "error_type": "InternalError",
                                },
                            )

                            # Attempt to send error notification based on source
                            if job.requested_context:
                                if job.source == JobSource.WEB:
                                    turn_id = job.requested_context.get("turn_id")
                                    if turn_id:
                                        error_web_callback = WebProgressCallback(
                                            turn_id=turn_id,
                                            db=db,
                                        )
                                        await error_web_callback.send_error(
                                            "An unexpected error occurred. Please try again."
                                        )
                                else:
                                    team_id = job.requested_context.get("team_id")
                                    if team_id and job.trigger_channel_id:
                                        # Create temporary callback for error notification
                                        error_callback = SlackProgressCallback(
                                            team_id=team_id,
                                            channel_id=job.trigger_channel_id,
                                            thread_ts=job.trigger_thread_ts,
                                        )
                                        await error_callback.send_unexpected_error()
                    except Exception as recovery_error:
                        logger.error(f"Failed to handle job failure: {recovery_error}")
        except Exception:
            # If something fails before we can set job_id, just pass
            pass
        finally:
            # Clear the job_id from context after job completes
            clear_job_id()


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
