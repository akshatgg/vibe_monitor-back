import asyncio
import logging
import signal
from dotenv import load_dotenv
from app.workers.base_worker import BaseWorker
from app.services.sqs.client import sqs_client
from app.services.rca.agent import rca_agent_service
from app.slack.service import slack_event_service

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
            "query": "Why is my xyz service slow?",
            "user_id": "U123ABC",
            "channel_id": "C456DEF",
            "team_id": "T789GHI",
            "thread_ts": "1234567890.123456",
            "timestamp": "1234567890.123456"
        }

        Parameters:
            message_body (dict): Parsed message payload from SQS containing Slack event data
        """
        try:
            logger.info(f"🔍 Starting RCA analysis for message: {message_body}")

            # Extract required fields
            user_query = message_body.get("query", "").strip()
            team_id = message_body.get("team_id")
            channel_id = message_body.get("channel_id")
            thread_ts = message_body.get("thread_ts") or message_body.get("timestamp")

            # Validate required fields
            if not user_query:
                logger.warning("Empty query in message body, skipping")
                return

            if not team_id or not channel_id:
                logger.error("Missing team_id or channel_id in message body")
                return

            # Send initial "thinking" message to Slack
            await slack_event_service.send_message(
                team_id=team_id,
                channel=channel_id,
                text=f"🤔 Analyzing the issue: *{user_query}*\n\nI'm investigating logs and metrics... This may take a moment.",
                thread_ts=thread_ts,
            )

            # Perform RCA analysis using AI agent
            logger.info(f"🤖 Invoking RCA agent for query: '{user_query}'")
            result = await rca_agent_service.analyze_with_retry(
                user_query=user_query,
                context=message_body,
                max_retries=2,
            )

            # Process result
            if result["success"]:
                logger.info("✅ RCA analysis completed successfully")

                # Format the response
                analysis_output = result["output"]

                # Send analysis result back to Slack
                await slack_event_service.send_message(
                    team_id=team_id,
                    channel=channel_id,
                    text=analysis_output,
                    thread_ts=thread_ts,
                )

                logger.info(f"📤 RCA result sent to Slack (team: {team_id}, channel: {channel_id})")

            else:
                # Analysis failed
                error_msg = result.get("error", "Unknown error occurred")
                logger.error(f"❌ RCA analysis failed: {error_msg}")

                # Send error message to user
                await slack_event_service.send_message(
                    team_id=team_id,
                    channel=channel_id,
                    text=(
                        f"❌ I encountered an issue while analyzing your request:\n\n"
                        f"```{error_msg}```\n\n"
                        f"Please try rephrasing your query or contact support if the issue persists."
                    ),
                    thread_ts=thread_ts,
                )

        except Exception as e:
            logger.exception(f"❌ Unexpected error processing RCA message: {e}")

            # Attempt to send error notification to Slack
            try:
                if team_id and channel_id:
                    await slack_event_service.send_message(
                        team_id=team_id,
                        channel=channel_id,
                        text=(
                            f"⚠️ An unexpected error occurred while processing your request:\n\n"
                            f"```{str(e)}```\n\n"
                            f"Our team has been notified. Please try again later."
                        ),
                        thread_ts=thread_ts,
                    )
            except Exception as notify_error:
                logger.error(f"Failed to send error notification to Slack: {notify_error}")


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