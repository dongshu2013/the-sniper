import argparse
import asyncio
import logging

from src.processors.entity_extractor import EntityExtractor
from src.processors.msg_queue_processor import MessageQueueProcessor
from src.processors.tg_link_importer import TgLinkImporter

# Create logger instance
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

tasks = {
    "tg_link_importer": TgLinkImporter(),
    "msg_queue_processor": MessageQueueProcessor(),
    "entity_extractor": EntityExtractor(),
}


async def run(task_name=None):
    if task_name:
        if task_name not in tasks:
            logger.error(f"Unknown task: {task_name}")
            return
        try:
            logger.info(f"Starting single task: {task_name}")
            await tasks[task_name].start_processing()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        return

    try:
        await asyncio.gather(*(task.start_processing() for task in tasks.values()))
    except KeyboardInterrupt:
        logger.info("Shutting down...")


def main():
    parser = argparse.ArgumentParser(description="Run aggregator tasks")
    parser.add_argument(
        "--task", type=str, choices=tasks.keys(), help="Specify a single task to run"
    )
    args = parser.parse_args()

    asyncio.run(run(args.task))


if __name__ == "__main__":
    main()
