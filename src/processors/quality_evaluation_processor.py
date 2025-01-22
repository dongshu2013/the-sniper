import logging

import asyncpg

from src.common.agent_client import AgentClient
from src.common.config import DATABASE_URL
from src.helpers.quality_evaluation_helper import evaluate_chat_qualities
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

QUALITY_EVALUATION_INTERVAL_SECONDS = 3600 * 24  # 1 day
# QUALITY_EVALUATION_INTERVAL_SECONDS=10 # test 10 seconds


class QualityEvaluationProcessor(ProcessorBase):
    def __init__(self):
        super().__init__(interval=QUALITY_EVALUATION_INTERVAL_SECONDS)
        self.pg_conn = None
        self.agent_client = AgentClient()

    async def process(self):
        if not self.pg_conn:
            self.pg_conn = await asyncpg.connect(DATABASE_URL)

        logger.info("Evaluating chat quality")
        await evaluate_chat_qualities(self.pg_conn, self.agent_client)
