import asyncio
import logging

from src.processors.score_summarizer import ChatScoreSummarizer

# Create logger instance
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run():
    score_summarizer = ChatScoreSummarizer()
    try:
        await asyncio.gather(
            score_summarizer.start_processing(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await score_summarizer.stop_processing()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
