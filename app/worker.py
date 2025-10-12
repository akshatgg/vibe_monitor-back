import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from app.workers.base_worker import BaseWorker
from app.services.sqs.client import sqs_client
from app.services.rca.agent import rca_agent_service
from app.slack.service import slack_event_service
from app.core.database import AsyncSessionLocal
from app.models import Job, JobStatus

logger = logging.getLogger(__name__)


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
                    logger.warning(f"Job {job_id} is not queued (status: {job.status.value}), skipping")
                    return

                # Check if job should be delayed (backoff)
                if job.backoff_until and job.backoff_until > datetime.now(timezone.utc):
                    # Calculate delay in seconds
                    delay = (job.backoff_until - datetime.now(timezone.utc)).total_seconds()

                    # SQS has a maximum delay of 900 seconds (15 minutes)
                    # If delay is longer, use max and let it check again
                    delay_seconds = min(int(delay), 900)

                    logger.info(f"Job {job_id} is in backoff until {job.backoff_until}, re-queueing with {delay_seconds}s delay")

                    # Re-enqueue to SQS with delay
                    await sqs_client.send_message(
                        message_body={"job_id": job_id},
                        delay_seconds=delay_seconds
                    )
                    return

                logger.info(f"🔍 Processing job {job_id}: {job.requested_context.get('query')}")

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
                        text=f"🤔 Analyzing the issue: *{query}*\n\n",
                        thread_ts=thread_ts,
                    )

                # Perform RCA analysis using AI agent
                logger.info(f"🤖 Invoking RCA agent for job {job_id} (workspace: {workspace_id})")

                # Add workspace_id to context for RCA tools
                analysis_context = {
                    **(job.requested_context or {}),
                    "workspace_id": workspace_id
                }

                result = await rca_agent_service.analyze_with_retry(
                    user_query=query,
                    context=analysis_context,
                    max_retries=2,
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
                        # Retry with exponential backoff
                        backoff_seconds = 2 ** job.retries * 60  # 2min, 4min, 8min
                        job.status = JobStatus.QUEUED
                        job.backoff_until = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
                        job.error_message = f"Attempt {job.retries}/{job.max_retries}: {error_msg}"
                        await db.commit()

                        # SQS has max delay of 900s (15 min), use that as cap
                        delay_seconds = min(backoff_seconds, 900)

                        logger.info(f"🔄 Job {job_id} will retry in {backoff_seconds}s (attempt {job.retries}/{job.max_retries})")

                        # Re-enqueue to SQS for retry with delay
                        await sqs_client.send_message(
                            message_body={"job_id": job_id},
                            delay_seconds=delay_seconds
                        )

                        # Notify user about retry
                        if team_id and channel_id:
                            await slack_event_service.send_message(
                                team_id=team_id,
                                channel=channel_id,
                                text=(
                                    f"⚠️ Job encountered an issue. Retrying in {backoff_seconds // 60} minutes...\n"
                                    f"Attempt {job.retries}/{job.max_retries}"
                                ),
                                thread_ts=thread_ts,
                            )

                    else:
                        # Max retries exceeded
                        job.status = JobStatus.FAILED
                        job.finished_at = datetime.now(timezone.utc)
                        job.error_message = error_msg
                        await db.commit()

                        logger.error(f"❌ Job {job_id} failed after {job.retries} retries")

                        # Send final error message to user
                        if team_id and channel_id:
                            await slack_event_service.send_message(
                                team_id=team_id,
                                channel=channel_id,
                                text=(
                                    f"❌ I encountered an issue while analyzing your request:\n\n"
                                    f"```{error_msg}```\n\n"
                                    f"Job ID: `{job_id}`\n"
                                    f"Tried {job.retries} times. Please try rephrasing your query or contact support."
                                ),
                                thread_ts=thread_ts,
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

                        # Attempt to send error notification to Slack
                        if job.requested_context:
                            team_id = job.requested_context.get("team_id")
                            if team_id and job.trigger_channel_id:
                                await slack_event_service.send_message(
                                    team_id=team_id,
                                    channel=job.trigger_channel_id,
                                    text=(
                                        f"⚠️ An unexpected error occurred while processing your request:\n\n"
                                        f"```{str(e)}```\n\n"
                                        f"Job ID: `{job_id}`\n"
                                        f"Our team has been notified. Please try again later."
                                    ),
                                    thread_ts=job.trigger_thread_ts,
                                )
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
    asyncio.run(main())