import asyncio
import logging
import signal
from dotenv import load_dotenv
from app.workers.base_worker import BaseWorker
from app.services.sqs.client import sqs_client

logger = logging.getLogger(__name__)


class RCAOrchestratorWorker(BaseWorker):
    def __init__(self):
        super().__init__("rca_orchestrator")

    async def process_message(self, message_body: dict):
        logger.info(f"Processing message: {message_body}")
        await asyncio.sleep(1)


async def main():
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