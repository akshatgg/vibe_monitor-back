import asyncio
import logging
from dotenv import load_dotenv
from app.workers.base_worker import BaseWorker
from app.services.sqs.client import sqs_client

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RCAOrchestratorWorker(BaseWorker):
    def __init__(self):
        super().__init__("rca_orchestrator")

    async def process_message(self, message_body):
        logger.info(f"Processing message: {message_body}")
        await asyncio.sleep(1)


async def main():
    logger.info("Starting worker process...")

    worker = RCAOrchestratorWorker()

    try:
        await worker.start()

        while worker.running:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await worker.stop()
        await sqs_client.close()
        logger.info("Worker process stopped")


if __name__ == "__main__":
    asyncio.run(main())